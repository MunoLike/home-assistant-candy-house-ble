"""Tests for Fake SESAME automatic discovery and event delivery."""

from __future__ import annotations

import json
from ipaddress import ip_address
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.const import Platform
from homeassistant.core import Event
from homeassistant.data_entry_flow import AbortFlow, FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from custom_components.candy_house_ble import (
    async_setup_entry,
    platforms_for_model,
)
from custom_components.candy_house_ble.config_flow import CandyHouseBLEConfigFlow
from custom_components.candy_house_ble.const import (
    CONF_DEVICE_ID,
    CONF_MODEL,
    CONF_REMOTE_ID,
    CONF_REMOTES,
    CONF_SECRET_KEY,
    FAKE_SESAME_EVENT,
    FAKE_SESAME_MDNS_KIND,
    FAKE_SESAME_MDNS_TYPE,
    FAKE_SESAME_PROTOCOL_VERSION,
    MODEL_FAKE_SESAME_BUTTON,
)
from custom_components.candy_house_ble.event import FakeSesameRemoteEvent
from custom_components.candy_house_ble.event import (
    async_setup_entry as async_setup_events,
)

DEVICE_ID = "12345678-1234-5678-1234-567812345678"
REMOTE_ID = "1120041e-0507-0608-9700-1300ffffffff"
REMOTE_ID_2 = "1120041e-0507-0608-9f00-4d00ffffffff"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def service_info(
    *,
    service_type: str = FAKE_SESAME_MDNS_TYPE,
    kind: str = FAKE_SESAME_MDNS_KIND,
    version: str = FAKE_SESAME_PROTOCOL_VERSION,
    device_id: object = DEVICE_ID,
) -> ZeroconfServiceInfo:
    """Build a representative Fake SESAME mDNS record."""
    address = ip_address("192.0.2.10")
    return ZeroconfServiceInfo(
        ip_address=address,
        ip_addresses=[address],
        port=6053,
        hostname="fake-sesame-bridge.local.",
        type=service_type,
        name=f"fake-sesame-bridge.{service_type}",
        properties={
            "kind": kind,
            "version": version,
            CONF_DEVICE_ID: device_id,
            "name": "Hallway buttons",
        },
    )


def test_manifest_and_reference_publish_the_dedicated_transport() -> None:
    manifest = json.loads(
        (
            REPOSITORY_ROOT
            / "custom_components/candy_house_ble/manifest.json"
        ).read_text(encoding="utf-8")
    )
    reference = (
        REPOSITORY_ROOT
        / "firmware/examples/fake-sesame-atom-s3-lite.yaml"
    ).read_text(encoding="utf-8")

    assert manifest["zeroconf"] == [FAKE_SESAME_MDNS_TYPE]
    assert "service: _candyhouseble" in reference
    assert f"kind: {FAKE_SESAME_MDNS_KIND}" in reference
    assert f'version: "{FAKE_SESAME_PROTOCOL_VERSION}"' in reference
    assert reference.count(f"event: {FAKE_SESAME_EVENT}") == 2
    assert reference.count("device_id: ${fake_sesame_device_id}") == 4
    assert reference.count("remote_id: !lambda return remote_id;") == 2


def discovery_flow() -> CandyHouseBLEConfigFlow:
    """Create a config flow for direct zeroconf-step unit tests."""
    flow = CandyHouseBLEConfigFlow()
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = Mock()
    return flow


@pytest.mark.asyncio
async def test_zeroconf_creates_secret_free_fake_sesame_entry() -> None:
    flow = discovery_flow()

    result = await flow.async_step_zeroconf(service_info())

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Hallway buttons"
    assert result["data"] == {
        CONF_DEVICE_ID: DEVICE_ID,
        CONF_MODEL: MODEL_FAKE_SESAME_BUTTON,
        CONF_REMOTES: [],
    }
    assert CONF_SECRET_KEY not in result["data"]
    flow.async_set_unique_id.assert_awaited_once_with(DEVICE_ID)
    flow._abort_if_unique_id_configured.assert_called_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"service_type": "_other._tcp.local."}, "unsupported_discovery"),
        ({"kind": "other"}, "unsupported_discovery"),
        ({"version": "2"}, "unsupported_discovery"),
        ({"device_id": "not-a-uuid"}, "invalid_discovery"),
        ({"device_id": None}, "invalid_discovery"),
    ],
)
async def test_zeroconf_rejects_invalid_records(
    changes: dict[str, object], reason: str
) -> None:
    result = await discovery_flow().async_step_zeroconf(
        service_info(**changes)
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason


@pytest.mark.asyncio
async def test_zeroconf_aborts_duplicate_unique_id() -> None:
    flow = discovery_flow()
    flow._abort_if_unique_id_configured.side_effect = AbortFlow(
        "already_configured"
    )

    with pytest.raises(AbortFlow, match="already_configured"):
        await flow.async_step_zeroconf(service_info())


def fake_entry(*, remotes: list[str] | None = None) -> SimpleNamespace:
    """Return a minimal discovered Fake SESAME config entry."""
    return SimpleNamespace(
        title="Hallway buttons",
        entry_id="fake-entry-id",
        data={
            CONF_DEVICE_ID: DEVICE_ID,
            CONF_MODEL: MODEL_FAKE_SESAME_BUTTON,
            CONF_REMOTES: list(remotes or []),
        },
        async_on_unload=Mock(),
    )


@pytest.mark.asyncio
async def test_fake_sesame_setup_loads_only_event_without_coordinator(
    monkeypatch,
) -> None:
    entry = fake_entry()
    constructor = Mock()
    monkeypatch.setattr(
        "custom_components.candy_house_ble.SesameStatusCoordinator",
        constructor,
    )
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_forward_entry_setups=AsyncMock())
    )

    assert platforms_for_model(MODEL_FAKE_SESAME_BUTTON) == [Platform.EVENT]
    assert await async_setup_entry(hass, entry) is True

    constructor.assert_not_called()
    assert entry.runtime_data is None
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        entry, [Platform.EVENT]
    )


@pytest.mark.asyncio
def fake_event_hass(monkeypatch) -> tuple[SimpleNamespace, Mock, Mock]:
    """Return a minimal HA facade and captured event listener."""
    listener = Mock()
    remove_listener = Mock()
    bus = SimpleNamespace(
        async_listen=Mock(
            side_effect=lambda _event_type, callback: (
                listener.configure_mock(side_effect=callback)
                or remove_listener
            )
        )
    )
    config_entries = SimpleNamespace(async_update_entry=Mock())
    hass = SimpleNamespace(bus=bus, config_entries=config_entries)
    registry = SimpleNamespace(async_get_or_create=Mock())
    monkeypatch.setattr(
        "custom_components.candy_house_ble.event.dr.async_get",
        lambda _hass: registry,
    )
    return hass, listener, registry


@pytest.mark.asyncio
async def test_event_platform_starts_empty_until_first_remote_press(
    monkeypatch,
) -> None:
    add_entities = Mock()
    hass, _listener, registry = fake_event_hass(monkeypatch)
    entry = fake_entry()

    await async_setup_events(hass, entry, add_entities)

    add_entities.assert_not_called()
    registry.async_get_or_create.assert_called_once()
    entry.async_on_unload.assert_called_once()


@pytest.mark.asyncio
async def test_event_platform_restores_each_persisted_remote(
    monkeypatch,
) -> None:
    add_entities = Mock()
    hass, _listener, _registry = fake_event_hass(monkeypatch)

    await async_setup_events(
        hass,
        fake_entry(remotes=[REMOTE_ID, REMOTE_ID_2]),
        add_entities,
    )

    entities = add_entities.call_args.args[0]
    assert len(entities) == 2
    assert all(type(entity) is FakeSesameRemoteEvent for entity in entities)
    assert {entity.unique_id for entity in entities} == {
        f"{DEVICE_ID}_{REMOTE_ID}_remote_button",
        f"{DEVICE_ID}_{REMOTE_ID_2}_remote_button",
    }
    assert all(entity.device_class == "button" for entity in entities)
    assert all(entity.event_types == ["lock", "unlock"] for entity in entities)
    assert {entity.device_info["name"] for entity in entities} == {
        "Remote nano 97001300",
        "Remote nano 9F004D00",
    }
    assert all(
        entity.device_info["model"] == "SESAME Remote Nano"
        for entity in entities
    )


@pytest.mark.asyncio
async def test_first_press_creates_persists_and_queues_remote_entity(
    monkeypatch,
) -> None:
    add_entities = Mock()
    hass, listener, _registry = fake_event_hass(monkeypatch)
    entry = fake_entry()
    await async_setup_events(hass, entry, add_entities)

    listener(
        Event(
            FAKE_SESAME_EVENT,
            {
                CONF_DEVICE_ID: DEVICE_ID.replace("-", ""),
                CONF_REMOTE_ID: REMOTE_ID.replace("-", ""),
                "action": "lock",
            },
        )
    )

    entity = add_entities.call_args.args[0][0]
    assert entity.unique_id == f"{DEVICE_ID}_{REMOTE_ID}_remote_button"
    assert entity._pending_actions == ["lock"]
    hass.config_entries.async_update_entry.assert_called_once_with(
        entry,
        data={**entry.data, CONF_REMOTES: [REMOTE_ID]},
    )

    receive_event = Mock()
    entity.receive_event = receive_event
    listener(
        Event(
            FAKE_SESAME_EVENT,
            {
                CONF_DEVICE_ID: DEVICE_ID,
                CONF_REMOTE_ID: REMOTE_ID,
                "action": "unlock",
            },
        )
    )
    receive_event.assert_called_once_with("unlock")
    assert add_entities.call_count == 1
    assert hass.config_entries.async_update_entry.call_count == 1


@pytest.mark.asyncio
async def test_event_manager_filters_bridge_remote_and_action(
    monkeypatch,
) -> None:
    add_entities = Mock()
    hass, listener, _registry = fake_event_hass(monkeypatch)
    await async_setup_events(hass, fake_entry(), add_entities)

    for data in (
        {
            CONF_DEVICE_ID: "87654321-4321-8765-4321-876543218765",
            CONF_REMOTE_ID: REMOTE_ID,
            "action": "unlock",
        },
        {
            CONF_DEVICE_ID: DEVICE_ID,
            CONF_REMOTE_ID: REMOTE_ID,
            "action": "toggle",
        },
        {CONF_DEVICE_ID: DEVICE_ID, "action": "unlock"},
        {
            CONF_DEVICE_ID: DEVICE_ID,
            CONF_REMOTE_ID: "not-a-uuid",
            "action": "lock",
        },
        {},
    ):
        listener(Event(FAKE_SESAME_EVENT, data))

    add_entities.assert_not_called()
    hass.config_entries.async_update_entry.assert_not_called()


def test_same_remote_is_scoped_to_its_bridge() -> None:
    other_bridge = "87654321-4321-8765-4321-876543218765"
    first = FakeSesameRemoteEvent(DEVICE_ID, REMOTE_ID, "First")
    second = FakeSesameRemoteEvent(other_bridge, REMOTE_ID, "Second")

    assert first.unique_id != second.unique_id
    assert first.device_info["identifiers"] != second.device_info["identifiers"]
