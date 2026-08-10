"""State sensor for CANDY HOUSE BLE."""

from __future__ import annotations

from typing import Any, ClassVar

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CandyHouseConfigEntry
from .entity import CandyHouseEntity
from .protocol import LockState


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CandyHouseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the read-only lock-state sensor."""
    async_add_entities([SesameStateSensor(entry)])


class SesameStateSensor(CandyHouseEntity, SensorEntity):
    """Represent the observed SESAME mechanism state."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = [state.value for state in LockState]
    _attr_translation_key = "state"

    def __init__(self, entry: CandyHouseConfigEntry) -> None:
        super().__init__(entry, "state")

    @property
    def native_value(self) -> str | None:
        """Return locked, unlocked, or moved."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.state.value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return non-secret mechanism diagnostics."""
        if self.coordinator.data is None:
            return {}
        status = self.coordinator.data
        return {
            "battery_raw": status.battery_raw,
            "target": status.target,
            "position": status.position,
            "critical": status.critical,
            "stopped": status.stopped,
        }
