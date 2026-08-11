"""Tests for CANDY HOUSE BLE config-entry migration."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from homeassistant.const import Platform

from custom_components.candy_house_ble import async_migrate_entry
from custom_components.candy_house_ble.const import CONF_DEVICE_ID, DOMAIN

DEVICE_UUID = "12345678-1234-5678-1234-567812345678"


@pytest.mark.asyncio
async def test_version_two_migration_removes_legacy_state_entity(
    monkeypatch,
) -> None:
    registry = SimpleNamespace(
        async_get_entity_id=Mock(return_value="sensor.test_lock_state"),
        async_remove=Mock(),
    )
    config_entries = SimpleNamespace(async_update_entry=Mock())
    hass = SimpleNamespace(config_entries=config_entries)
    entry = SimpleNamespace(
        version=1,
        data={CONF_DEVICE_ID: DEVICE_UUID},
    )
    monkeypatch.setattr(
        "custom_components.candy_house_ble.er.async_get",
        lambda _hass: registry,
    )

    assert await async_migrate_entry(hass, entry) is True

    registry.async_get_entity_id.assert_called_once_with(
        Platform.SENSOR,
        DOMAIN,
        f"{DEVICE_UUID}_state",
    )
    registry.async_remove.assert_called_once_with("sensor.test_lock_state")
    config_entries.async_update_entry.assert_called_once_with(entry, version=2)
