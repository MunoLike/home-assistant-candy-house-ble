"""Tests for CANDY HOUSE BLE config-entry migration."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from homeassistant.const import Platform

from custom_components.candy_house_ble import async_migrate_entry
from custom_components.candy_house_ble.const import (
    CONF_DEVICE_ID,
    CONF_MODEL,
    DOMAIN,
    MODEL_BOT_2,
    MODEL_SESAME_5_PRO,
)

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
        data={
            CONF_DEVICE_ID: DEVICE_UUID,
            CONF_MODEL: MODEL_SESAME_5_PRO,
        },
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
    config_entries.async_update_entry.assert_called_once_with(entry, version=3)


@pytest.mark.asyncio
async def test_version_three_migration_removes_current_script_button(
    monkeypatch,
) -> None:
    legacy_unique_id = f"{DEVICE_UUID}_run_current_script"
    registry = SimpleNamespace(
        async_get_entity_id=Mock(
            side_effect=lambda platform, _domain, unique_id: (
                "button.test_bot_2_run_current_script"
                if platform is Platform.BUTTON
                and unique_id == legacy_unique_id
                else None
            )
        ),
        async_remove=Mock(),
    )
    config_entries = SimpleNamespace(async_update_entry=Mock())
    hass = SimpleNamespace(config_entries=config_entries)
    entry = SimpleNamespace(
        version=2,
        data={CONF_DEVICE_ID: DEVICE_UUID, CONF_MODEL: MODEL_BOT_2},
    )
    monkeypatch.setattr(
        "custom_components.candy_house_ble.er.async_get",
        lambda _hass: registry,
    )

    assert await async_migrate_entry(hass, entry) is True

    registry.async_get_entity_id.assert_called_once_with(
        Platform.BUTTON,
        DOMAIN,
        legacy_unique_id,
    )
    registry.async_remove.assert_called_once_with(
        "button.test_bot_2_run_current_script"
    )
    config_entries.async_update_entry.assert_called_once_with(entry, version=3)
