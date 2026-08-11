"""Sensors for CANDY HOUSE BLE."""

from __future__ import annotations

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
from .const import (
    BOT_2_BATTERY_DIVIDER_RATIO,
    CONF_MODEL,
    MODEL_BOT_2,
    MODEL_SESAME_5_PRO,
    SESAME_5_PRO_BATTERY_DIVIDER_RATIO,
)
from .entity import CandyHouseEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CandyHouseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up read-only SESAME sensors."""
    if entry.data[CONF_MODEL] == MODEL_BOT_2:
        entities = [
            SesameBatteryVoltageSensor(entry),
            SesameSignalStrengthSensor(entry),
        ]
    else:
        entities = [
            SesameBatteryVoltageSensor(entry),
            SesameSignalStrengthSensor(entry),
            SesamePositionSensor(entry),
        ]
    async_add_entities(entities)


class SesameBatteryVoltageSensor(CandyHouseEntity, SensorEntity):
    """Represent the model-corrected battery voltage."""

    _divider_ratio = SESAME_5_PRO_BATTERY_DIVIDER_RATIO
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 3
    _attr_translation_key = "battery_voltage"

    def __init__(self, entry: CandyHouseConfigEntry) -> None:
        super().__init__(entry, "battery_voltage")
        if entry.data[CONF_MODEL] != MODEL_SESAME_5_PRO:
            self._divider_ratio = BOT_2_BATTERY_DIVIDER_RATIO

    @property
    def native_value(self) -> float | None:
        """Return the reported battery voltage in volts."""
        if self.coordinator.data is None:
            return None
        return (
            self.coordinator.data.battery_raw
            * self._divider_ratio
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
