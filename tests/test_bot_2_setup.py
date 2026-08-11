"""Tests for read-only SESAME Bot 2 platform isolation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.const import EntityCategory, Platform

from custom_components.candy_house_ble import (
    async_setup_entry,
    async_unload_entry,
    platforms_for_model,
)
from custom_components.candy_house_ble.binary_sensor import (
    SesameBatteryLowSensor,
    SesameMechanismErrorSensor,
    SesameMovingSensor,
)
from custom_components.candy_house_ble.binary_sensor import (
    async_setup_entry as async_setup_binary_sensors,
)
from custom_components.candy_house_ble.button import (
    SesameBot2RunScriptButton,
)
from custom_components.candy_house_ble.button import (
    async_setup_entry as async_setup_buttons,
)
from custom_components.candy_house_ble.const import (
    CONF_DEVICE_ID,
    CONF_MODEL,
    MODEL_BOT_2,
    MODEL_SESAME_5_PRO,
)
from custom_components.candy_house_ble.protocol import LockState, MechanismStatus
from custom_components.candy_house_ble.sensor import (
    SesameBatteryVoltageSensor,
    SesamePositionSensor,
    SesameSignalStrengthSensor,
)
from custom_components.candy_house_ble.sensor import (
    async_setup_entry as async_setup_sensors,
)


def bot_entry() -> SimpleNamespace:
    """Return the minimum config entry consumed by entity constructors."""
    return SimpleNamespace(
        data={
            CONF_DEVICE_ID: "12345678-1234-5678-1234-567812345678",
            CONF_MODEL: MODEL_BOT_2,
        },
        runtime_data=SimpleNamespace(data=None),
        title="Test Bot 2",
        async_on_unload=Mock(),
        add_update_listener=Mock(),
    )


def test_bot_2_never_forwards_the_lock_platform() -> None:
    assert platforms_for_model(MODEL_BOT_2) == [
        Platform.BUTTON,
        Platform.SENSOR,
        Platform.BINARY_SENSOR,
    ]
    assert Platform.LOCK not in platforms_for_model(MODEL_BOT_2)
    assert platforms_for_model(MODEL_SESAME_5_PRO) == [
        Platform.LOCK,
        Platform.SENSOR,
        Platform.BINARY_SENSOR,
    ]
    with pytest.raises(ValueError, match="Unsupported"):
        platforms_for_model(99)


@pytest.mark.asyncio
async def test_bot_2_exposes_ten_scripts_and_diagnostics() -> None:
    entry = bot_entry()
    sensor_add = Mock()
    binary_add = Mock()
    button_add = Mock()

    await async_setup_buttons(SimpleNamespace(), entry, button_add)
    await async_setup_sensors(SimpleNamespace(), entry, sensor_add)
    await async_setup_binary_sensors(SimpleNamespace(), entry, binary_add)

    sensors = sensor_add.call_args.args[0]
    binary_sensors = binary_add.call_args.args[0]
    buttons = button_add.call_args.args[0]
    assert len(buttons) == 10
    assert all(type(entity) is SesameBot2RunScriptButton for entity in buttons)
    assert [entity.script_index for entity in buttons] == list(range(10))
    assert [entity.unique_id for entity in buttons] == [
        f"12345678-1234-5678-1234-567812345678_run_script_{index}"
        for index in range(10)
    ]
    assert [type(entity) for entity in sensors] == [
        SesameBatteryVoltageSensor,
        SesameSignalStrengthSensor,
    ]
    assert [type(entity) for entity in binary_sensors] == [
        SesameMovingSensor
    ]
    assert all(
        entity.entity_category is EntityCategory.DIAGNOSTIC
        for entity in [*sensors, *binary_sensors]
    )


@pytest.mark.asyncio
async def test_bot_2_full_setup_and_unload_never_forward_lock(
    monkeypatch,
) -> None:
    entry = bot_entry()
    coordinator = SimpleNamespace(
        async_config_entry_first_refresh=AsyncMock(),
        async_refresh=AsyncMock(),
    )
    constructor = Mock(return_value=coordinator)
    monkeypatch.setattr(
        "custom_components.candy_house_ble.SesameStatusCoordinator",
        constructor,
    )
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_forward_entry_setups=AsyncMock(),
            async_unload_platforms=AsyncMock(return_value=True),
        )
    )

    assert await async_setup_entry(hass, entry) is True
    assert await async_unload_entry(hass, entry) is True

    coordinator.async_refresh.assert_awaited_once_with()
    coordinator.async_config_entry_first_refresh.assert_not_awaited()
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        entry,
        [Platform.BUTTON, Platform.SENSOR, Platform.BINARY_SENSOR],
    )
    entry.add_update_listener.assert_not_called()
    hass.config_entries.async_unload_platforms.assert_awaited_once_with(
        entry,
        [Platform.BUTTON, Platform.SENSOR, Platform.BINARY_SENSOR],
    )


@pytest.mark.asyncio
async def test_bot_2_script_button_delegates_its_index_exactly_once() -> None:
    entry = bot_entry()
    entry.runtime_data.async_run_script = AsyncMock()
    entity = SesameBot2RunScriptButton(entry, 7)

    assert entity.available is False
    entry.runtime_data.data = object()
    assert entity.available is True
    await entity.async_press()

    entry.runtime_data.async_run_script.assert_awaited_once_with(7)


def test_bot_2_battery_voltage_uses_single_cell_scale() -> None:
    entry = bot_entry()
    entry.runtime_data.data = MechanismStatus(
        state=LockState.LOCKED,
        battery_raw=3051,
        target=0,
        position=0,
        battery_low=False,
        critical=False,
        stopped=True,
    )
    entity = SesameBatteryVoltageSensor(entry)

    assert entity.native_value == pytest.approx(3.051)


@pytest.mark.asyncio
async def test_model_7_keeps_original_entity_order() -> None:
    entry = bot_entry()
    entry.data[CONF_MODEL] = MODEL_SESAME_5_PRO
    sensor_add = Mock()
    binary_add = Mock()

    await async_setup_sensors(SimpleNamespace(), entry, sensor_add)
    await async_setup_binary_sensors(SimpleNamespace(), entry, binary_add)

    assert [type(entity) for entity in sensor_add.call_args.args[0]] == [
        SesameBatteryVoltageSensor,
        SesameSignalStrengthSensor,
        SesamePositionSensor,
    ]
    assert [type(entity) for entity in binary_add.call_args.args[0]] == [
        SesameBatteryLowSensor,
        SesameMovingSensor,
        SesameMechanismErrorSensor,
    ]
