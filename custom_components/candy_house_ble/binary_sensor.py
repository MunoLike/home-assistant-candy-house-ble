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
from .entity import CandyHouseEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CandyHouseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up SESAME diagnostic binary sensors."""
    async_add_entities([SesameBatteryLowSensor(entry)])


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
