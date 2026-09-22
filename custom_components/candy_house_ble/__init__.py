"""CANDY HOUSE BLE integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    BOT_MODELS,
    CONF_DEVICE_ID,
    CONF_MODEL,
    CONF_REMOTES,
    DOMAIN,
    LOCK_MODELS,
    MODEL_BOT_2,
    MODEL_FAKE_SESAME_BUTTON,
)
from .coordinator import SesameStatusCoordinator

LOCK_PLATFORMS = [Platform.LOCK, Platform.SENSOR, Platform.BINARY_SENSOR]
BOT_2_PLATFORMS = [Platform.BUTTON, Platform.SENSOR, Platform.BINARY_SENSOR]
FAKE_SESAME_PLATFORMS = [Platform.EVENT]

# Version 3 stored these optional Hub/Web API settings. Version 4 is BLE-only,
# so migration removes precisely these known keys while preserving unknown
# options for forward compatibility.
REMOVED_V3_OPTION_KEYS = frozenset(
    {
        "command_transport",
        "cloud_api_key",
        "cloud_secret_key",
        "cloud_unlock_enabled",
    }
)

type CandyHouseConfigEntry = ConfigEntry[SesameStatusCoordinator | None]


async def async_setup(hass: HomeAssistant, _config: dict) -> bool:
    """Register admin-only, read-only provisioning support."""
    from .websocket_api import async_register_websocket_commands

    async_register_websocket_commands(hass)
    return True


def platforms_for_model(model: int) -> list[Platform]:
    """Return only the platforms supported for one device model."""
    if model in LOCK_MODELS:
        return LOCK_PLATFORMS
    if model in BOT_MODELS:
        return BOT_2_PLATFORMS
    if model == MODEL_FAKE_SESAME_BUTTON:
        return FAKE_SESAME_PLATFORMS
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
    data = dict(entry.data)
    options = dict(getattr(entry, "options", {}))
    if entry.version < 4:
        options = {
            key: value
            for key, value in options.items()
            if key not in REMOVED_V3_OPTION_KEYS
        }
    if entry.version < 5 and entry.data[CONF_MODEL] == MODEL_FAKE_SESAME_BUTTON:
        if registry is None:
            registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id(
            Platform.EVENT,
            DOMAIN,
            f"{entry.data[CONF_DEVICE_ID]}_remote_button",
        )
        if entity_id is not None:
            registry.async_remove(entity_id)
        data.setdefault(CONF_REMOTES, [])
    if entry.version < 5:
        hass.config_entries.async_update_entry(
            entry,
            version=5,
            data=data,
            options=options,
        )
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: CandyHouseConfigEntry
) -> bool:
    """Set up a CANDY HOUSE BLE device from a config entry."""
    if entry.data[CONF_MODEL] == MODEL_FAKE_SESAME_BUTTON:
        entry.runtime_data = None
        await hass.config_entries.async_forward_entry_setups(
            entry, FAKE_SESAME_PLATFORMS
        )
        return True

    coordinator = SesameStatusCoordinator(hass, entry)
    if entry.data[CONF_MODEL] in BOT_MODELS:
        await coordinator.async_refresh()
    else:
        await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
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
