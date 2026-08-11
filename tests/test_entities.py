"""Tests for CANDY HOUSE BLE sensor values."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.candy_house_ble.binary_sensor import (
    SesameMechanismErrorSensor,
    SesameMovingSensor,
)
from custom_components.candy_house_ble.binary_sensor import (
    async_setup_entry as async_setup_binary_sensors,
)
from custom_components.candy_house_ble.const import CONF_DEVICE_ID, CONF_MODEL
from custom_components.candy_house_ble.lock import SesameLock
from custom_components.candy_house_ble.lock import (
    async_setup_entry as async_setup_lock,
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


def status(**overrides: object) -> MechanismStatus:
    """Build a representative mechanism status."""
    values = {
        "state": LockState.LOCKED,
        "battery_raw": 2925,
        "target": None,
        "position": -86,
        "battery_low": False,
        "critical": False,
        "stopped": True,
        "rssi": -63,
    }
    values.update(overrides)
    return MechanismStatus(**values)


def entity_with_status(entity_type, mechanism_status: MechanismStatus):
    """Create an entity around coordinator data without an HA instance."""
    entity = object.__new__(entity_type)
    entity.coordinator = SimpleNamespace(data=mechanism_status)
    return entity


def fake_entry(mechanism_status: MechanismStatus):
    """Build the config-entry fields used by entity setup."""
    return SimpleNamespace(
        data={
            CONF_DEVICE_ID: "12345678-1234-5678-1234-567812345678",
            CONF_MODEL: 7,
        },
        runtime_data=SimpleNamespace(data=mechanism_status),
        title="Test lock",
    )


def test_diagnostic_sensor_values() -> None:
    mechanism_status = status()

    assert (
        entity_with_status(
            SesameBatteryVoltageSensor, mechanism_status
        ).native_value
        == pytest.approx(5.85)
    )
    assert (
        entity_with_status(
            SesameSignalStrengthSensor, mechanism_status
        ).native_value
        == -63
    )
    assert (
        entity_with_status(SesamePositionSensor, mechanism_status).native_value
        == -86
    )


@pytest.mark.asyncio
async def test_platform_setup_adds_all_entities() -> None:
    entry = fake_entry(status())
    sensor_entities: list[object] = []
    binary_sensor_entities: list[object] = []
    lock_entities: list[object] = []

    await async_setup_sensors(None, entry, sensor_entities.extend)
    await async_setup_binary_sensors(None, entry, binary_sensor_entities.extend)
    await async_setup_lock(None, entry, lock_entities.extend)

    assert len(sensor_entities) == 3
    assert len(binary_sensor_entities) == 3
    assert len(lock_entities) == 1
    assert {entity.unique_id.rsplit("_", 1)[-1] for entity in sensor_entities} == {
        "voltage",
        "strength",
        "position",
    }
    assert {
        entity.unique_id.rsplit("_", 1)[-1] for entity in binary_sensor_entities
    } == {"low", "moving", "error"}
    assert lock_entities[0].unique_id.endswith("_lock")
    rssi_entity = next(
        entity
        for entity in sensor_entities
        if isinstance(entity, SesameSignalStrengthSensor)
    )
    assert rssi_entity.entity_registry_enabled_default is False


@pytest.mark.parametrize(
    ("lock_state", "is_locked"),
    [
        (LockState.LOCKED, True),
        (LockState.UNLOCKED, False),
        (LockState.MOVED, None),
    ],
)
def test_lock_state_mapping(
    lock_state: LockState, is_locked: bool | None
) -> None:
    entry = fake_entry(status(state=lock_state))
    entity = SesameLock(entry)

    assert entity.is_locked is is_locked
    assert entity.is_jammed is False


def test_lock_maps_critical_to_jammed() -> None:
    entity = SesameLock(fake_entry(status(critical=True)))

    assert entity.is_jammed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["lock", "unlock"])
async def test_lock_operation_exposes_pending_state(operation: str) -> None:
    entity = SesameLock(fake_entry(status()))
    entity.async_write_ha_state = Mock()

    async def assert_pending() -> None:
        assert entity.is_locking is (operation == "lock")
        assert entity.is_unlocking is (operation == "unlock")

    action = AsyncMock(side_effect=assert_pending)
    setattr(entity.coordinator, f"async_{operation}", action)

    await getattr(entity, f"async_{operation}")()

    action.assert_awaited_once_with()
    assert entity.is_locking is False
    assert entity.is_unlocking is False
    assert entity.async_write_ha_state.call_count == 2


@pytest.mark.asyncio
async def test_lock_operation_clears_pending_state_after_failure() -> None:
    entity = SesameLock(fake_entry(status()))
    entity.async_write_ha_state = Mock()
    entity.coordinator.async_unlock = AsyncMock(
        side_effect=RuntimeError("operation failed")
    )

    with pytest.raises(RuntimeError, match="operation failed"):
        await entity.async_unlock()

    assert entity.is_unlocking is False
    assert entity.async_write_ha_state.call_count == 2


@pytest.mark.asyncio
async def test_duplicate_entity_operation_is_rejected() -> None:
    entity = SesameLock(fake_entry(status()))
    entity.async_write_ha_state = Mock()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def block() -> None:
        entered.set()
        await release.wait()

    entity.coordinator.async_lock = block
    entity.coordinator.async_unlock = AsyncMock()
    first = asyncio.create_task(entity.async_lock())
    await entered.wait()

    with pytest.raises(HomeAssistantError, match="already in progress"):
        await entity.async_unlock()

    assert entity.is_locking is True
    release.set()
    await first


@pytest.mark.parametrize(
    ("stopped", "critical", "moving", "mechanism_error"),
    [(True, False, False, False), (False, True, True, True)],
)
def test_diagnostic_binary_sensor_values(
    stopped: bool,
    critical: bool,
    moving: bool,
    mechanism_error: bool,
) -> None:
    mechanism_status = status(stopped=stopped, critical=critical)

    assert (
        entity_with_status(SesameMovingSensor, mechanism_status).is_on
        is moving
    )
    assert (
        entity_with_status(SesameMechanismErrorSensor, mechanism_status).is_on
        is mechanism_error
    )


@pytest.mark.parametrize(
    "entity_type",
    [
        SesameBatteryVoltageSensor,
        SesameSignalStrengthSensor,
        SesamePositionSensor,
        SesameMovingSensor,
        SesameMechanismErrorSensor,
    ],
)
def test_diagnostic_entities_return_unknown_without_data(entity_type) -> None:
    entity = object.__new__(entity_type)
    entity.coordinator = SimpleNamespace(data=None)

    value = entity.is_on if hasattr(entity_type, "is_on") else entity.native_value

    assert value is None
