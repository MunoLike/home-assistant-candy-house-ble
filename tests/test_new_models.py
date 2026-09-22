"""Regression coverage for the additional OS3 device models."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.const import Platform

from custom_components.candy_house_ble import async_setup_entry, async_unload_entry
from custom_components.candy_house_ble.const import (
    CONF_MODEL,
    MODEL_BOT_3,
    MODEL_SESAME_6_PRO,
)
from custom_components.candy_house_ble.protocol import LockState
from custom_components.candy_house_ble.sensor import SesameBatteryVoltageSensor
from tests.test_bot_2_setup import bot_entry
from tests.test_coordinator import mechanism_status


@pytest.mark.asyncio
async def test_sesame_6_pro_setup_refreshes_before_forwarding_lock(monkeypatch):
    entry = bot_entry()
    entry.data[CONF_MODEL] = MODEL_SESAME_6_PRO
    coordinator = SimpleNamespace(
        async_config_entry_first_refresh=AsyncMock(),
        async_refresh=AsyncMock(),
    )
    monkeypatch.setattr(
        "custom_components.candy_house_ble.SesameStatusCoordinator",
        Mock(return_value=coordinator),
    )

    async def forward(forwarded_entry, platforms):
        coordinator.async_config_entry_first_refresh.assert_awaited_once_with()
        assert forwarded_entry.runtime_data is coordinator
        assert platforms == [Platform.LOCK, Platform.SENSOR, Platform.BINARY_SENSOR]

    hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_forward_entry_setups=AsyncMock(side_effect=forward),
            async_unload_platforms=AsyncMock(return_value=True),
        )
    )
    assert await async_setup_entry(hass, entry)
    coordinator.async_refresh.assert_not_awaited()
    hass.config_entries.async_forward_entry_setups.assert_awaited_once()
    assert await async_unload_entry(hass, entry)
    hass.config_entries.async_unload_platforms.assert_awaited_once_with(
        entry, [Platform.LOCK, Platform.SENSOR, Platform.BINARY_SENSOR]
    )


@pytest.mark.parametrize(
    ("model", "name", "voltage"),
    [(MODEL_SESAME_6_PRO, "SESAME 6 Pro", 5.85), (MODEL_BOT_3, "SESAME Bot 3", 2.925)],
)
def test_new_model_device_info_and_voltage(model, name, voltage):
    entry = bot_entry()
    entry.data[CONF_MODEL] = model
    sensor = SesameBatteryVoltageSensor(entry)
    assert sensor.native_value is None
    entry.runtime_data.data = mechanism_status(LockState.LOCKED)
    assert sensor.native_value == pytest.approx(voltage)
    assert sensor.device_info["model"] == name
