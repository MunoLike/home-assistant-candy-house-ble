"""Sensors for CANDY HOUSE BLE."""

from __future__ import annotations

from typing import Any, ClassVar

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    DEGREE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfElectricPotential,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CandyHouseConfigEntry
from .const import SESAME_5_PRO_BATTERY_DIVIDER_RATIO
from .entity import CandyHouseEntity
from .protocol import LockState


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CandyHouseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up read-only SESAME sensors."""
    async_add_entities(
        [
            SesameStateSensor(entry),
            SesameBatteryVoltageSensor(entry),
            SesameSignalStrengthSensor(entry),
            SesamePositionSensor(entry),
        ]
    )


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


class SesameBatteryVoltageSensor(CandyHouseEntity, SensorEntity):
    """Represent SESAME 5 Pro battery voltage through its 1:2 divider."""

    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 3
    _attr_translation_key = "battery_voltage"

    def __init__(self, entry: CandyHouseConfigEntry) -> None:
        super().__init__(entry, "battery_voltage")

    @property
    def native_value(self) -> float | None:
        """Return the reported battery voltage in volts."""
        if self.coordinator.data is None:
            return None
        return (
            self.coordinator.data.battery_raw
            * SESAME_5_PRO_BATTERY_DIVIDER_RATIO
            / 1000
        )


class SesameSignalStrengthSensor(CandyHouseEntity, SensorEntity):
    """Represent advertisement RSSI at the scanner selected by HA."""

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "signal_strength"
    _attr_entity_registry_enabled_default = False

    def __init__(self, entry: CandyHouseConfigEntry) -> None:
        super().__init__(entry, "signal_strength")

    @property
    def native_value(self) -> int | None:
        """Return the RSSI from the advertisement used for this poll."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.rssi


class SesamePositionSensor(CandyHouseEntity, SensorEntity):
    """Represent the current SESAME thumb-turn angle."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = DEGREE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "position"

    def __init__(self, entry: CandyHouseConfigEntry) -> None:
        super().__init__(entry, "position")

    @property
    def native_value(self) -> int | None:
        """Return the current thumb-turn angle in degrees."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.position
