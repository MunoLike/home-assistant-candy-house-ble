"""Shared entities for CANDY HOUSE BLE."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import CandyHouseConfigEntry
from .const import CONF_DEVICE_ID, CONF_MODEL, DOMAIN, MODEL_NAMES
from .coordinator import SesameStatusCoordinator


class CandyHouseEntity(CoordinatorEntity[SesameStatusCoordinator]):
    """Base entity for one configured CANDY HOUSE device."""

    _attr_has_entity_name = True

    def __init__(self, entry: CandyHouseConfigEntry, suffix: str) -> None:
        super().__init__(entry.runtime_data)
        device_id = entry.data[CONF_DEVICE_ID]
        model = entry.data[CONF_MODEL]
        self._attr_unique_id = f"{device_id}_{suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            manufacturer="CANDY HOUSE",
            model=MODEL_NAMES.get(model, "SESAME"),
            name=entry.title,
        )
