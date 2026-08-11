"""CANDY HOUSE BLE integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CONF_DEVICE_ID, DOMAIN
from .coordinator import SesameStatusCoordinator

PLATFORMS = [Platform.LOCK, Platform.SENSOR, Platform.BINARY_SENSOR]

type CandyHouseConfigEntry = ConfigEntry[SesameStatusCoordinator]


async def async_migrate_entry(
    hass: HomeAssistant, entry: CandyHouseConfigEntry
) -> bool:
    """Remove the superseded state sensor from version 1 entries."""
    if entry.version < 2:
        registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id(
            Platform.SENSOR,
            DOMAIN,
            f"{entry.data[CONF_DEVICE_ID]}_state",
        )
        if entity_id is not None:
            registry.async_remove(entity_id)
        hass.config_entries.async_update_entry(entry, version=2)
    return True


async def _async_reload_entry(
    hass: HomeAssistant, entry: CandyHouseConfigEntry
) -> None:
    """Reload the integration when command transport options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(
    hass: HomeAssistant, entry: CandyHouseConfigEntry
) -> bool:
    """Set up a CANDY HOUSE BLE device from a config entry."""
    coordinator = SesameStatusCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: CandyHouseConfigEntry
) -> bool:
    """Unload a CANDY HOUSE BLE config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
