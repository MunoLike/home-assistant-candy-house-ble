"""Event entities for ESPHome Fake SESAME button bridges."""

from __future__ import annotations

import uuid

from homeassistant.components.event import (
    EventDeviceClass,
    EventEntity,
    EventEntityDescription,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CandyHouseConfigEntry
from .const import (
    CONF_DEVICE_ID,
    CONF_REMOTE_ID,
    CONF_REMOTES,
    DOMAIN,
    FAKE_SESAME_EVENT,
    FAKE_SESAME_EVENT_TYPES,
    MODEL_FAKE_SESAME_BUTTON,
    MODEL_NAMES,
)

DESCRIPTION = EventEntityDescription(
    key="remote_button",
    translation_key="remote_button",
    device_class=EventDeviceClass.BUTTON,
    event_types=list(FAKE_SESAME_EVENT_TYPES),
)


def _canonical_uuid(value: object) -> str | None:
    """Return a canonical UUID, or None for malformed input."""
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


def _remote_name(remote_id: str) -> str:
    """Build a short, stable label from the distinctive UUID bytes."""
    compact = remote_id.replace("-", "")
    return f"Remote nano {compact[16:24].upper()}"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CandyHouseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up persisted Remotes and discover new ones on first press."""
    manager = FakeSesameRemoteManager(hass, entry, async_add_entities)
    manager.async_setup()
    entry.async_on_unload(manager.async_unload)


class FakeSesameRemoteManager:
    """Own one bridge listener and its dynamically discovered Remotes."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: CandyHouseConfigEntry,
        async_add_entities: AddConfigEntryEntitiesCallback,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._async_add_entities = async_add_entities
        self._bridge_id = entry.data[CONF_DEVICE_ID]
        self._entities: dict[str, FakeSesameRemoteEvent] = {}
        self._remove_listener = None

    @callback
    def async_setup(self) -> None:
        """Create the parent bridge, restore Remotes, and listen for presses."""
        dr.async_get(self._hass).async_get_or_create(
            config_entry_id=self._entry.entry_id,
            identifiers={(DOMAIN, self._bridge_id)},
            manufacturer="ESPHome",
            model=MODEL_NAMES[MODEL_FAKE_SESAME_BUTTON],
            name=self._entry.title,
        )

        entities = []
        for stored_remote_id in self._entry.data.get(CONF_REMOTES, []):
            remote_id = _canonical_uuid(stored_remote_id)
            if remote_id is None or remote_id in self._entities:
                continue
            entity = self._create_entity(remote_id)
            entities.append(entity)
        if entities:
            self._async_add_entities(entities)

        self._remove_listener = self._hass.bus.async_listen(
            FAKE_SESAME_EVENT, self._handle_button_event
        )

    @callback
    def async_unload(self) -> None:
        """Remove the bridge-wide event listener."""
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None

    def _create_entity(self, remote_id: str) -> FakeSesameRemoteEvent:
        entity = FakeSesameRemoteEvent(
            self._bridge_id,
            remote_id,
            self._entry.title,
        )
        self._entities[remote_id] = entity
        return entity

    @callback
    def _handle_button_event(self, event: Event) -> None:
        """Route one authenticated press to its physical Remote entity."""
        bridge_id = _canonical_uuid(event.data.get(CONF_DEVICE_ID))
        remote_id = _canonical_uuid(event.data.get(CONF_REMOTE_ID))
        action = event.data.get("action")
        if (
            bridge_id != self._bridge_id
            or remote_id is None
            or action not in FAKE_SESAME_EVENT_TYPES
        ):
            return

        entity = self._entities.get(remote_id)
        if entity is None:
            entity = self._create_entity(remote_id)
            entity.receive_event(action)
            self._async_add_entities([entity])
            data = dict(self._entry.data)
            data[CONF_REMOTES] = sorted(self._entities)
            self._hass.config_entries.async_update_entry(
                self._entry, data=data
            )
            return
        entity.receive_event(action)


class FakeSesameRemoteEvent(EventEntity):
    """Represent button commands received from one physical Remote."""

    _attr_has_entity_name = True
    entity_description = DESCRIPTION

    def __init__(
        self, bridge_id: str, remote_id: str, _bridge_name: str
    ) -> None:
        self._remote_id = remote_id
        self._pending_actions: list[str] = []
        self._added = False
        self._attr_unique_id = f"{bridge_id}_{remote_id}_remote_button"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{bridge_id}:{remote_id}")},
            via_device=(DOMAIN, bridge_id),
            manufacturer="CANDY HOUSE",
            model="SESAME Remote Nano",
            name=_remote_name(remote_id),
        )

    async def async_added_to_hass(self) -> None:
        """Publish a press that discovered this entity before it was added."""
        await super().async_added_to_hass()
        self._added = True
        for action in self._pending_actions:
            self._trigger_event(action)
            self.async_write_ha_state()
        self._pending_actions.clear()

    @callback
    def receive_event(self, action: str) -> None:
        """Publish or temporarily queue a validated Remote action."""
        if not self._added:
            self._pending_actions.append(action)
            return
        self._trigger_event(action)
        self.async_write_ha_state()
