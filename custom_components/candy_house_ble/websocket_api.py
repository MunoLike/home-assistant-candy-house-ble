"""Admin-only read-only provisioning command."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .provisioning import RemoteNanoReadError, RemoteNanoTargetReader

HEX_16_BYTES = vol.All(str, vol.Match(r"^[0-9a-fA-F]{32}$"))


@callback
def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register the inspection command once when the integration loads."""
    websocket_api.async_register_command(hass, websocket_read_remote_targets)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "candy_house_ble/read_remote_nano_targets",
        vol.Required("device_id"): HEX_16_BYTES,
        vol.Required("secret_key"): HEX_16_BYTES,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_read_remote_targets(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return only redacted target counts from one Remote Nano."""
    reader = RemoteNanoTargetReader(
        hass,
        bytes.fromhex(msg["device_id"]),
        bytes.fromhex(msg["secret_key"]),
    )
    try:
        summary = await reader.async_read()
    except RemoteNanoReadError as err:
        connection.send_error(msg["id"], "read_failed", str(err))
        return
    connection.send_result(
        msg["id"],
        {
            "total_slots": summary.total_slots,
            "occupied_slots": summary.occupied_slots,
            "os3_slots": summary.os3_slots,
            "legacy_slots": summary.legacy_slots,
            "empty": summary.empty,
        },
    )
