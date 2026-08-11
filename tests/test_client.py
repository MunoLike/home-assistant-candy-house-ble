"""Tests for optional BLE transport diagnostics."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.candy_house_ble.client import (
    SesameConnectionError,
    SesameStatusClient,
    service_info_rssi,
)
from custom_components.candy_house_ble.const import WRITE_CHARACTERISTIC_UUID
from custom_components.candy_house_ble.protocol import (
    LockState,
    MechanismStatus,
    build_login_packet,
)

SECRET_KEY = bytes.fromhex("00112233445566778899aabbccddeeff")
TOKEN = bytes.fromhex("a1b2c3d4")


class BrokenRSSI:
    """Model service information whose RSSI property cannot be read."""

    @property
    def rssi(self) -> int:
        raise RuntimeError("scanner data unavailable")


@pytest.mark.parametrize(
    ("service_info", "expected"),
    [
        (SimpleNamespace(rssi=-63), -63),
        (SimpleNamespace(rssi=None), None),
        (SimpleNamespace(), None),
        (BrokenRSSI(), None),
        (SimpleNamespace(rssi=-63.5), None),
    ],
)
def test_service_info_rssi_is_optional(
    service_info: object, expected: int | None
) -> None:
    assert service_info_rssi(service_info) == expected


def status_client() -> SesameStatusClient:
    """Build a client without touching Home Assistant Bluetooth."""
    return SesameStatusClient(
        SimpleNamespace(),
        7,
        bytes.fromhex("12345678123456781234567812345678"),
        SECRET_KEY,
        "Test lock",
    )


def mechanism_status(
    state: LockState,
    *,
    critical: bool = False,
    stopped: bool = True,
) -> MechanismStatus:
    """Build one synthetic mechanism notification."""
    return MechanismStatus(
        state=state,
        battery_raw=2925,
        target=None,
        position=-86,
        battery_low=False,
        critical=critical,
        stopped=stopped,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "expected_packet", "terminal_state"),
    [
        ("async_lock", "0549ed1487f28ae9", LockState.LOCKED),
        ("async_unlock", "0548ed1489b0abd7", LockState.UNLOCKED),
    ],
)
async def test_fixed_command_success(
    monkeypatch,
    method_name: str,
    expected_packet: str,
    terminal_state: LockState,
) -> None:
    client = status_client()
    gatt = SimpleNamespace(is_connected=False, write_gatt_char=AsyncMock())

    async def acknowledge(*_args, **_kwargs) -> None:
        client._command_result = 0
        client._command_event.set()
        client._status_queue.put_nowait(mechanism_status(terminal_state))

    gatt.write_gatt_char.side_effect = acknowledge

    async def connect():
        _login, client._cipher = build_login_packet(SECRET_KEY, TOKEN)
        client._client = gatt
        client._login_event.set()
        return SimpleNamespace(rssi=-63)

    monkeypatch.setattr(client, "_async_connect", connect)

    result = await getattr(client, method_name)()

    gatt.write_gatt_char.assert_awaited_once_with(
        WRITE_CHARACTERISTIC_UUID,
        bytes.fromhex(expected_packet),
        response=False,
    )
    assert result.state is terminal_state
    assert result.rssi == -63


@pytest.mark.asyncio
async def test_rejected_command_is_reported(monkeypatch) -> None:
    client = status_client()
    gatt = SimpleNamespace(is_connected=False, write_gatt_char=AsyncMock())

    async def reject(*_args, **_kwargs) -> None:
        client._command_result = 8
        client._command_event.set()

    gatt.write_gatt_char.side_effect = reject

    async def connect():
        _login, client._cipher = build_login_packet(SECRET_KEY, TOKEN)
        client._client = gatt
        client._login_event.set()
        return SimpleNamespace(rssi=-63)

    monkeypatch.setattr(client, "_async_connect", connect)

    with pytest.raises(SesameConnectionError, match="result 8"):
        await client.async_lock()

    gatt.write_gatt_char.assert_awaited_once()


@pytest.mark.asyncio
async def test_authentication_error_sends_no_command(monkeypatch) -> None:
    client = status_client()
    gatt = SimpleNamespace(is_connected=False, write_gatt_char=AsyncMock())

    async def connect():
        client._client = gatt
        client._notification_error = SesameConnectionError("bad credential")
        client._login_event.set()
        return SimpleNamespace(rssi=-63)

    monkeypatch.setattr(client, "_async_connect", connect)

    with pytest.raises(SesameConnectionError, match="bad credential"):
        await client.async_unlock()

    gatt.write_gatt_char.assert_not_awaited()


@pytest.mark.asyncio
async def test_critical_terminal_status_is_reported(monkeypatch) -> None:
    client = status_client()
    gatt = SimpleNamespace(is_connected=False, write_gatt_char=AsyncMock())

    async def acknowledge(*_args, **_kwargs) -> None:
        client._command_result = 0
        client._command_event.set()
        client._status_queue.put_nowait(
            mechanism_status(LockState.MOVED, critical=True)
        )

    gatt.write_gatt_char.side_effect = acknowledge

    async def connect():
        _login, client._cipher = build_login_packet(SECRET_KEY, TOKEN)
        client._client = gatt
        client._login_event.set()
        return SimpleNamespace(rssi=-63)

    monkeypatch.setattr(client, "_async_connect", connect)

    with pytest.raises(SesameConnectionError, match="critical mechanism"):
        await client.async_lock()


@pytest.mark.asyncio
async def test_stopped_outside_requested_range_is_reported(monkeypatch) -> None:
    client = status_client()
    gatt = SimpleNamespace(is_connected=False, write_gatt_char=AsyncMock())

    async def acknowledge(*_args, **_kwargs) -> None:
        client._command_result = 0
        client._command_event.set()
        client._status_queue.put_nowait(mechanism_status(LockState.MOVED))

    gatt.write_gatt_char.side_effect = acknowledge

    async def connect():
        _login, client._cipher = build_login_packet(SECRET_KEY, TOKEN)
        client._client = gatt
        client._login_event.set()
        return SimpleNamespace(rssi=-63)

    monkeypatch.setattr(client, "_async_connect", connect)

    with pytest.raises(SesameConnectionError, match="outside the requested"):
        await client.async_unlock()


@pytest.mark.asyncio
async def test_disconnect_after_acknowledgement_is_reported(monkeypatch) -> None:
    client = status_client()
    gatt = SimpleNamespace(is_connected=False, write_gatt_char=AsyncMock())

    async def acknowledge_then_disconnect(*_args, **_kwargs) -> None:
        client._command_result = 0
        client._command_event.set()
        client._status_queue.put_nowait(None)

    gatt.write_gatt_char.side_effect = acknowledge_then_disconnect

    async def connect():
        _login, client._cipher = build_login_packet(SECRET_KEY, TOKEN)
        client._client = gatt
        client._login_event.set()
        return SimpleNamespace(rssi=-63)

    monkeypatch.setattr(client, "_async_connect", connect)

    with pytest.raises(SesameConnectionError, match="disconnected before"):
        await client.async_lock()


@pytest.mark.asyncio
async def test_poll_and_commands_share_one_operation_lock(monkeypatch) -> None:
    client = status_client()
    active = 0
    maximum_active = 0

    async def execute(*_args) -> None:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0)
        active -= 1

    async def read_status():
        await execute()
        return SimpleNamespace()

    monkeypatch.setattr(client, "_async_execute_command", execute)
    monkeypatch.setattr(client, "_async_read_status_locked", read_status)

    await asyncio.gather(client.async_read_status(), client.async_unlock())

    assert maximum_active == 1


@pytest.mark.asyncio
async def test_duplicate_command_is_rejected_instead_of_queued(monkeypatch) -> None:
    client = status_client()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def execute(*_args):
        entered.set()
        await release.wait()
        return mechanism_status(LockState.LOCKED)

    monkeypatch.setattr(client, "_async_execute_command", execute)

    first = asyncio.create_task(client.async_lock())
    await entered.wait()
    with pytest.raises(SesameConnectionError, match="already in progress"):
        await client.async_unlock()
    release.set()
    await first
