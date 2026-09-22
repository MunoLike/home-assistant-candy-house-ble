"""Binary sensors for CANDY HOUSE BLE."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CandyHouseConfigEntry
from .const import BOT_MODELS, CONF_MODEL
from .entity import CandyHouseEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CandyHouseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up SESAME diagnostic binary sensors."""
    if entry.data[CONF_MODEL] in BOT_MODELS:
        entities = [SesameMovingSensor(entry)]
    else:
        entities = [
            SesameBatteryLowSensor(entry),
            SesameMovingSensor(entry),
            SesameMechanismErrorSensor(entry),
        ]
    async_add_entities(entities)


class SesameBatteryLowSensor(CandyHouseEntity, BinarySensorEntity):
    """Represent the SESAME low-battery flag."""

    _attr_device_class = BinarySensorDeviceClass.BATTERY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "battery_low"

    def __init__(self, entry: CandyHouseConfigEntry) -> None:
        super().__init__(entry, "battery_low")

    @property
    def is_on(self) -> bool | None:
        """Return whether the lock reports low battery."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.battery_low


class SesameMovingSensor(CandyHouseEntity, BinarySensorEntity):
    """Represent whether the SESAME mechanism is moving."""

    _attr_device_class = BinarySensorDeviceClass.MOVING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "moving"

    def __init__(self, entry: CandyHouseConfigEntry) -> None:
        super().__init__(entry, "moving")

    @property
    def is_on(self) -> bool | None:
        """Return whether the mechanism reports that it is not stopped."""
        if self.coordinator.data is None:
            return None
        return not self.coordinator.data.stopped


class SesameMechanismErrorSensor(CandyHouseEntity, BinarySensorEntity):
    """Represent the SESAME mechanism critical-error flag."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "mechanism_error"

    def __init__(self, entry: CandyHouseConfigEntry) -> None:
        super().__init__(entry, "mechanism_error")

    @property
    def is_on(self) -> bool | None:
        """Return whether the mechanism reports a critical error."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.critical
