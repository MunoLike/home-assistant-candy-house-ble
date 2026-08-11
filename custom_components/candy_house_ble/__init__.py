"""CANDY HOUSE BLE integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_DEVICE_ID,
    CONF_MODEL,
    DOMAIN,
    MODEL_BOT_2,
    MODEL_SESAME_5_PRO,
)
from .coordinator import SesameStatusCoordinator

LOCK_PLATFORMS = [Platform.LOCK, Platform.SENSOR, Platform.BINARY_SENSOR]
BOT_2_PLATFORMS = [Platform.BUTTON, Platform.SENSOR, Platform.BINARY_SENSOR]

type CandyHouseConfigEntry = ConfigEntry[SesameStatusCoordinator]


def platforms_for_model(model: int) -> list[Platform]:
    """Return only the platforms supported for one device model."""
    if model == MODEL_SESAME_5_PRO:
        return LOCK_PLATFORMS
    if model == MODEL_BOT_2:
        return BOT_2_PLATFORMS
    raise ValueError(f"Unsupported CANDY HOUSE model {model}")


async def async_migrate_entry(
    hass: HomeAssistant, entry: CandyHouseConfigEntry
) -> bool:
    """Remove entities superseded by newer platform layouts."""
    registry = None
    if entry.version < 2:
        registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id(
            Platform.SENSOR,
            DOMAIN,
            f"{entry.data[CONF_DEVICE_ID]}_state",
        )
        if entity_id is not None:
            registry.async_remove(entity_id)
    if entry.version < 3 and entry.data[CONF_MODEL] == MODEL_BOT_2:
        if registry is None:
            registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id(
            Platform.BUTTON,
            DOMAIN,
            f"{entry.data[CONF_DEVICE_ID]}_run_current_script",
        )
        if entity_id is not None:
            registry.async_remove(entity_id)
    if entry.version < 3:
        hass.config_entries.async_update_entry(entry, version=3)
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
    if entry.data[CONF_MODEL] == MODEL_BOT_2:
        await coordinator.async_refresh()
    else:
        await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(
        entry, platforms_for_model(entry.data[CONF_MODEL])
    )
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: CandyHouseConfigEntry
) -> bool:
    """Unload a CANDY HOUSE BLE config entry."""
    return await hass.config_entries.async_unload_platforms(
        entry, platforms_for_model(entry.data[CONF_MODEL])
    )
