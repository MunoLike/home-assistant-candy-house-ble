#!/usr/bin/env python3
"""Ask Home Assistant to read redacted Remote Nano target-slot counts."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import aiohttp

DEFAULT_CREDENTIAL = Path(
    "/config/.tools/home-assistant-candy-house-ble/credentials/"
    "remote-nano-fake-sesame-manager.json"
)


async def async_read(credential_path: Path) -> dict:
    """Send credentials only to the local admin WebSocket command."""
    credential = json.loads(credential_path.read_text(encoding="utf-8"))
    token = os.environ["SUPERVISOR_TOKEN"]
    headers = {"Authorization": f"Bearer {token}"}
    async with (
        aiohttp.ClientSession(headers=headers) as session,
        session.ws_connect(
            "ws://supervisor/core/api/websocket"
        ) as websocket,
    ):
        await websocket.receive_json()
        await websocket.send_json(
            {"type": "auth", "access_token": token}
        )
        auth = await websocket.receive_json()
        if auth.get("type") != "auth_ok":
            raise RuntimeError("Home Assistant WebSocket authentication failed")
        await websocket.send_json(
            {
                "id": 1,
                "type": "candy_house_ble/read_remote_nano_targets",
                "device_id": credential["device_id"],
                "secret_key": credential["secret_key"],
            }
        )
        while True:
            response = await websocket.receive_json()
            if response.get("id") == 1:
                return response


def main() -> None:
    """Read the configured spare Remote and print only the redacted result."""
    credential_path = Path(
        os.environ.get("CREDENTIAL_PATH", DEFAULT_CREDENTIAL)
    )
    response = asyncio.run(async_read(credential_path))
    print(json.dumps(response, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
