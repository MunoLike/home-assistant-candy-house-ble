"""Tests for BLE client behavior and runtime diagnostics."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.candy_house_ble.client import (
    SesameConnectionError,
    SesamePollPreempted,
    SesameStatusClient,
    service_info_rssi,
)
from custom_components.candy_house_ble.const import WRITE_CHARACTERISTIC_UUID
from custom_components.candy_house_ble.protocol import (
    ITEM_INITIAL,
    ITEM_LOGIN,
    ITEM_MECH_STATUS,
    OP_PUBLISH,
    OP_RESPONSE,
    SEGMENT_CIPHER,
    SEGMENT_PLAIN,
    LockState,
    MechanismStatus,
    build_login_packet,
)

SECRET_KEY = bytes.fromhex("00112233445566778899aabbccddeeff")
TOKEN = bytes.fromhex("a1b2c3d4")


def segment(segment_type: int, payload: bytes) -> bytes:
    """Build one complete inbound BLE segment."""
    return bytes(((segment_type << 1) | 1,)) + payload


class BrokenRSSI:
    """Model service information whose RSSI property cannot be read."""

    @property
    def rssi(self) -> int:
        raise RuntimeError("scanner data unavailable")


class FakeHass:
    """Run HA-created notification tasks on the current event loop."""

    def __init__(self) -> None:
        self.tasks: set[asyncio.Task] = set()

    def async_create_task(self, coro, _name):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task


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


def status_client(model: int = 7) -> SesameStatusClient:
    """Build a client without touching Home Assistant Bluetooth."""
    return SesameStatusClient(
        SimpleNamespace(),
        model,
        bytes.fromhex("12345678123456781234567812345678"),
        SECRET_KEY,
        "Test lock",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("model", [17, 35])
async def test_bot_2_login_and_status_are_read_only(model) -> None:
    client = SesameStatusClient(
        SimpleNamespace(),
        model,
        bytes.fromhex("12345678123456781234567812345678"),
        SECRET_KEY,
        "Test Bot 2",
    )
    gatt = SimpleNamespace(write_gatt_char=AsyncMock())
    client._client = gatt
    client._session_generation = 1
    client._notify_ready_event.set()

    await client._async_handle_notification(
        1,
        segment(
            SEGMENT_PLAIN,
            bytes((OP_PUBLISH, ITEM_INITIAL)) + TOKEN,
        ),
    )
    expected_login, server_cipher = build_login_packet(SECRET_KEY, TOKEN)
    await client._async_handle_notification(
        1,
        segment(
            SEGMENT_CIPHER,
            server_cipher.encrypt(bytes((OP_RESPONSE, ITEM_LOGIN, 0))),
        ),
    )
    await client._async_handle_notification(
        1,
        segment(
            SEGMENT_CIPHER,
            server_cipher.encrypt(
                bytes((OP_PUBLISH, ITEM_MECH_STATUS))
                + (3012).to_bytes(2, "little")
                + bytes((0b00000110,))
            ),
        ),
    )

    gatt.write_gatt_char.assert_awaited_once_with(
        WRITE_CHARACTERISTIC_UUID, expected_login, response=False
    )
    assert client._status is not None
    assert client._status.battery_raw == 3012
    assert client._status.state is LockState.LOCKED
    assert client._status.stopped is True
    assert client._status.position is None


@pytest.mark.asyncio
@pytest.mark.parametrize("model", [7, 17, 21, 35])
async def test_complete_os3_poll_writes_only_login(model, monkeypatch) -> None:
    hass = FakeHass()
    client = SesameStatusClient(
        hass,
        model,
        bytes.fromhex("12345678123456781234567812345678"),
        SECRET_KEY,
        "Test Bot 2",
    )
    status_payload = (
        (3012).to_bytes(2, "little") + bytes((0b00000110,))
        if model in (17, 35)
        else (3012).to_bytes(2, "little") + bytes.fromhex("0080aaff12")
    )
    expected_login, server_cipher = build_login_packet(SECRET_KEY, TOKEN)
    notify_callback = None

    async def start_notify(_characteristic, callback) -> None:
        nonlocal notify_callback
        notify_callback = callback
        callback(
            None,
            bytearray(
                segment(
                    SEGMENT_PLAIN,
                    bytes((OP_PUBLISH, ITEM_INITIAL)) + TOKEN,
                )
            ),
        )
        await asyncio.sleep(0)
        assert gatt.write_gatt_char.await_count == 0

    async def write_gatt_char(characteristic, packet, response=False) -> None:
        assert characteristic == WRITE_CHARACTERISTIC_UUID
        assert packet == expected_login
        assert response is False
        assert notify_callback is not None
        notify_callback(
            None,
            bytearray(
                segment(
                    SEGMENT_CIPHER,
                    server_cipher.encrypt(
                        bytes((OP_RESPONSE, ITEM_LOGIN, 0))
                    ),
                )
            ),
        )
        notify_callback(
            None,
            bytearray(
                segment(
                    SEGMENT_CIPHER,
                    server_cipher.encrypt(
                        bytes((OP_PUBLISH, ITEM_MECH_STATUS))
                        + status_payload
                    ),
                )
            ),
        )

    gatt = SimpleNamespace(
        is_connected=True,
        start_notify=AsyncMock(side_effect=start_notify),
        write_gatt_char=AsyncMock(side_effect=write_gatt_char),
        disconnect=AsyncMock(),
    )
    monkeypatch.setattr(
        "custom_components.candy_house_ble.client."
        "async_resolve_service_info",
        AsyncMock(return_value=SimpleNamespace(device=object(), rssi=-55)),
    )
    establish = AsyncMock(return_value=gatt)
    monkeypatch.setattr(
        "custom_components.candy_house_ble.client.establish_connection",
        establish,
    )

    status = await client.async_read_status()
    if hass.tasks:
        await asyncio.gather(*tuple(hass.tasks))

    assert status.battery_raw == 3012
    assert status.stopped is True
    assert status.state is LockState.LOCKED
    assert status.position == (None if model in (17, 35) else -86)
    assert establish.await_args.kwargs["use_services_cache"] is False
    assert gatt.write_gatt_char.await_count == 1
    gatt.write_gatt_char.assert_awaited_once_with(
        WRITE_CHARACTERISTIC_UUID, expected_login, response=False
    )
    gatt.disconnect.assert_awaited_once_with()


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
@pytest.mark.parametrize("model", [7, 21])
async def test_fixed_command_success(
    model,
    monkeypatch,
    method_name: str,
    expected_packet: str,
    terminal_state: LockState,
) -> None:
    client = status_client(model)
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
@pytest.mark.parametrize("model", [7, 21])
async def test_rejected_command_is_reported(model, monkeypatch) -> None:
    client = status_client(model)
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
@pytest.mark.parametrize("model", [7, 21])
async def test_authentication_error_sends_no_command(model, monkeypatch) -> None:
    client = status_client(model)
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
@pytest.mark.parametrize("method_name", ["async_lock", "async_unlock"])
@pytest.mark.parametrize("model", [17, 35])
async def test_bot_2_rejects_lock_commands_before_connecting(
    model,
    method_name: str,
) -> None:
    client = SesameStatusClient(
        SimpleNamespace(),
        model,
        bytes.fromhex("12345678123456781234567812345678"),
        SECRET_KEY,
        "Test Bot 2",
    )

    with pytest.raises(SesameConnectionError, match="not supported"):
        await getattr(client, method_name)()


@pytest.mark.asyncio
@pytest.mark.parametrize("model", [17, 35])
async def test_bot_2_fixed_script_success(model, monkeypatch) -> None:
    client = SesameStatusClient(
        SimpleNamespace(),
        model,
        bytes.fromhex("12345678123456781234567812345678"),
        SECRET_KEY,
        "Test Bot 2",
    )
    gatt = SimpleNamespace(is_connected=False, write_gatt_char=AsyncMock())

    async def acknowledge(*_args, **_kwargs) -> None:
        client._command_result = 0
        client._command_event.set()

    gatt.write_gatt_char.side_effect = acknowledge

    async def connect():
        _login, client._cipher = build_login_packet(SECRET_KEY, TOKEN)
        client._client = gatt
        client._login_event.set()
        return SimpleNamespace(rssi=-63)

    monkeypatch.setattr(client, "_async_connect", connect)

    await client.async_run_script(7)

    gatt.write_gatt_char.assert_awaited_once_with(
        WRITE_CHARACTERISTIC_UUID,
        bytes.fromhex("05aaed14ad2b66cd"),
        response=False,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("model", [7, 21])
async def test_lock_model_rejects_bot_2_script_before_connecting(model) -> None:
    client = status_client(model)

    with pytest.raises(SesameConnectionError, match="not supported"):
        await client.async_run_script(7)


@pytest.mark.asyncio
@pytest.mark.parametrize("script_index", [-1, 10, True, 1.5, "1"])
@pytest.mark.parametrize("model", [17, 35])
async def test_bot_2_rejects_invalid_script_before_connecting(
    model,
    script_index, monkeypatch
) -> None:
    client = SesameStatusClient(
        SimpleNamespace(),
        model,
        bytes.fromhex("12345678123456781234567812345678"),
        SECRET_KEY,
        "Test Bot 2",
    )
    connect = AsyncMock()
    monkeypatch.setattr(client, "_async_connect", connect)

    with pytest.raises(SesameConnectionError, match="script index"):
        await client.async_run_script(script_index)

    connect.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("model", [17, 35])
async def test_bot_2_ack_starts_double_tap_cooldown(model, monkeypatch) -> None:
    client = SesameStatusClient(
        SimpleNamespace(),
        model,
        bytes.fromhex("12345678123456781234567812345678"),
        SECRET_KEY,
        "Test Bot 2",
    )
    gatt = SimpleNamespace(is_connected=False, write_gatt_char=AsyncMock())

    async def acknowledge(*_args, **_kwargs) -> None:
        client._command_result = 0
        client._command_event.set()

    gatt.write_gatt_char.side_effect = acknowledge

    async def connect():
        _login, client._cipher = build_login_packet(SECRET_KEY, TOKEN)
        client._client = gatt
        client._login_event.set()
        return SimpleNamespace(rssi=-63)

    monkeypatch.setattr(client, "_async_connect", connect)

    await client.async_run_script(2)
    with pytest.raises(SesameConnectionError, match="cooldown"):
        await client.async_run_script(2)

    assert gatt.write_gatt_char.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("model", [17, 35])
async def test_bot_2_lost_ack_blocks_ambiguous_retry(model, monkeypatch) -> None:
    client = SesameStatusClient(
        SimpleNamespace(),
        model,
        bytes.fromhex("12345678123456781234567812345678"),
        SECRET_KEY,
        "Test Bot 2",
    )
    gatt = SimpleNamespace(is_connected=False, write_gatt_char=AsyncMock())

    async def connect():
        _login, client._cipher = build_login_packet(SECRET_KEY, TOKEN)
        client._client = gatt
        client._login_event.set()
        return SimpleNamespace(rssi=-63)

    monkeypatch.setattr(client, "_async_connect", connect)
    monkeypatch.setattr(
        "custom_components.candy_house_ble.client.COMMAND_TIMEOUT", 0.01
    )

    with pytest.raises(SesameConnectionError, match="indeterminate"):
        await client.async_run_script(5)
    with pytest.raises(SesameConnectionError, match="cooldown"):
        await client.async_run_script(5)

    gatt.write_gatt_char.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("model", [17, 35])
async def test_bot_2_write_failure_is_indeterminate_and_not_retried(
    model,
    monkeypatch,
) -> None:
    client = SesameStatusClient(
        SimpleNamespace(),
        model,
        bytes.fromhex("12345678123456781234567812345678"),
        SECRET_KEY,
        "Test Bot 2",
    )
    gatt = SimpleNamespace(
        is_connected=False,
        write_gatt_char=AsyncMock(side_effect=RuntimeError("transport lost")),
    )

    async def connect():
        _login, client._cipher = build_login_packet(SECRET_KEY, TOKEN)
        client._client = gatt
        client._login_event.set()
        return SimpleNamespace(rssi=-63)

    monkeypatch.setattr(client, "_async_connect", connect)

    with pytest.raises(SesameConnectionError, match="indeterminate"):
        await client.async_run_script(8)
    with pytest.raises(SesameConnectionError, match="cooldown"):
        await client.async_run_script(8)

    gatt.write_gatt_char.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("model", [17, 35])
async def test_bot_2_connect_failure_reports_no_command_sent(
    model,
    monkeypatch,
) -> None:
    client = SesameStatusClient(
        SimpleNamespace(),
        model,
        bytes.fromhex("12345678123456781234567812345678"),
        SECRET_KEY,
        "Test Bot 2",
    )
    connect = AsyncMock(side_effect=RuntimeError("proxy disconnected"))
    monkeypatch.setattr(client, "_async_connect", connect)

    with pytest.raises(SesameConnectionError, match="no command was sent"):
        await client.async_run_script(7)
    with pytest.raises(SesameConnectionError, match="no command was sent"):
        await client.async_run_script(7)

    assert connect.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("model", [7, 21])
async def test_critical_terminal_status_is_reported(model, monkeypatch) -> None:
    client = status_client(model)
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
@pytest.mark.parametrize("model", [7, 21])
async def test_stopped_outside_requested_range_is_reported(model, monkeypatch) -> None:
    client = status_client(model)
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
@pytest.mark.parametrize("model", [7, 21])
async def test_disconnect_after_acknowledgement_is_reported(model, monkeypatch) -> None:
    client = status_client(model)
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
@pytest.mark.parametrize("model", [7, 21])
async def test_command_preempts_poll_without_overlapping_sessions(
    model,
    monkeypatch,
) -> None:
    client = status_client(model)
    active = 0
    maximum_active = 0
    poll_started = asyncio.Event()

    async def execute(*_args):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0)
        active -= 1
        return mechanism_status(LockState.UNLOCKED)

    async def read_status():
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        poll_started.set()
        await client._status_event.wait()
        active -= 1
        if client._poll_preempted:
            raise SesamePollPreempted
        return mechanism_status(LockState.LOCKED)

    monkeypatch.setattr(client, "_async_execute_command", execute)
    monkeypatch.setattr(client, "_async_read_status_locked", read_status)

    poll = asyncio.create_task(client.async_read_status())
    await poll_started.wait()
    result = await client.async_unlock()

    assert maximum_active == 1
    assert result.state is LockState.UNLOCKED
    with pytest.raises(SesamePollPreempted):
        await poll


@pytest.mark.asyncio
@pytest.mark.parametrize("model", [7, 21])
async def test_command_waits_for_preempted_poll_subscription_cleanup(
    model, monkeypatch
) -> None:
    client = status_client(model)
    connect_started = asyncio.Event()
    finish_connect = asyncio.Event()
    command_started = asyncio.Event()

    async def connect():
        connect_started.set()
        await finish_connect.wait()

    async def execute(*_args):
        command_started.set()
        return mechanism_status(LockState.UNLOCKED)

    monkeypatch.setattr(client, "_async_connect", connect)
    monkeypatch.setattr(client, "_async_execute_command", execute)

    poll = asyncio.create_task(client.async_read_status())
    await connect_started.wait()
    command = asyncio.create_task(client.async_unlock())
    await asyncio.sleep(0)

    assert not command_started.is_set()
    finish_connect.set()
    result = await command
    assert result.state is LockState.UNLOCKED
    assert command_started.is_set()
    with pytest.raises(SesamePollPreempted):
        await poll


@pytest.mark.asyncio
@pytest.mark.parametrize("model", [7, 21])
async def test_cancelling_poll_also_cancels_connection_task(model, monkeypatch) -> None:
    client = status_client(model)
    connect_started = asyncio.Event()
    connect_cancelled = asyncio.Event()

    async def connect():
        connect_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            connect_cancelled.set()

    monkeypatch.setattr(client, "_async_connect", connect)

    poll = asyncio.create_task(client.async_read_status())
    await connect_started.wait()
    poll.cancel()

    with pytest.raises(asyncio.CancelledError):
        await poll
    assert connect_cancelled.is_set()
    diagnostics = client.diagnostics_snapshot()
    assert diagnostics["operations"]["poll"]["cancellations"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("model", [7, 21])
async def test_stale_session_notification_is_ignored(model) -> None:
    client = status_client(model)
    client._session_generation = 2

    await client._async_handle_notification(1, b"\xff")

    assert client._notification_error is None


@pytest.mark.asyncio
@pytest.mark.parametrize("model", [7, 21])
async def test_duplicate_command_is_rejected_instead_of_queued(
    model, monkeypatch
) -> None:
    client = status_client(model)
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
