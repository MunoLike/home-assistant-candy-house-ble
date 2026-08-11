"""CANDY HOUSE BLE integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import SesameStatusCoordinator

PLATFORMS = [Platform.LOCK, Platform.SENSOR, Platform.BINARY_SENSOR]

type CandyHouseConfigEntry = ConfigEntry[SesameStatusCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: CandyHouseConfigEntry
) -> bool:
    """Set up a CANDY HOUSE BLE device from a config entry."""
    coordinator = SesameStatusCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: CandyHouseConfigEntry
) -> bool:
    """Unload a CANDY HOUSE BLE config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
