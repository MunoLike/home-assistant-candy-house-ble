"""Diagnostics for CANDY HOUSE BLE."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import CandyHouseConfigEntry
from .const import CONF_MODEL, CONF_SECRET_KEY, MODEL_FAKE_SESAME_BUTTON


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CandyHouseConfigEntry
) -> dict[str, Any]:
    """Return diagnostics with the device secret removed."""
    del hass
    if entry.data[CONF_MODEL] == MODEL_FAKE_SESAME_BUTTON:
        return {
            "config_entry": {
                "title": entry.title,
                "data": dict(entry.data),
            },
            "event_transport": "esphome_native_api",
        }
    return {
        "config_entry": {
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), {CONF_SECRET_KEY}),
        },
        "status": asdict(entry.runtime_data.data)
        if entry.runtime_data.data is not None
        else None,
        "ble_runtime": entry.runtime_data.client.diagnostics_snapshot(),
    }
