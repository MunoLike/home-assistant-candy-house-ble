"""Tests for bounded one-session status and history collection."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.hazmat.primitives import cmac
from cryptography.hazmat.primitives.ciphers import algorithms
from cryptography.hazmat.primitives.ciphers.aead import AESCCM

from custom_components.candy_house_ble import client as client_module
from custom_components.candy_house_ble.client import SesameStatusClient
from custom_components.candy_house_ble.const import SERVICE_UUID
from custom_components.candy_house_ble.protocol import (
    ITEM_HISTORY,
    ITEM_INITIAL,
    ITEM_LOGIN,
    ITEM_MECH_STATUS,
    OP_PUBLISH,
    OP_RESPONSE,
    SEGMENT_CIPHER,
    SEGMENT_PLAIN,
    LockState,
)

SECRET_KEY = bytes.fromhex("00112233445566778899aabbccddeeff")
TOKEN = bytes.fromhex("a1b2c3d4")
DEVICE_ID = bytes.fromhex("12345678123456781234567812345678")


def session_key() -> bytes:
    signer = cmac.CMAC(algorithms.AES(SECRET_KEY))
    signer.update(TOKEN)
    return signer.finalize()


class FakeHomeAssistant:
    """Minimal task scheduler used by notification callbacks."""

    def async_create_task(self, coroutine, name: str):
        return asyncio.create_task(coroutine, name=name)


class FakeSesame:
    """Deterministic SESAME peripheral with two history records."""

    def __init__(
        self, history_records: list[bytes], *, terminate_history: bool = True
    ) -> None:
        self.is_connected = True
        self.history_records = [*history_records]
        if terminate_history:
            self.history_records.append(b"")
        self.history_requests = 0
        self._callback = None
        self._notify_counter = 0
        self._request_counter = 0
        self._aes = AESCCM(session_key(), tag_length=4)

    async def start_notify(self, _uuid: str, callback) -> None:
        self._callback = callback
        self._send_plain(bytes((OP_PUBLISH, ITEM_INITIAL)) + TOKEN)

    async def write_gatt_char(
        self, _uuid: str, packet: bytes, *, response: bool
    ) -> None:
        assert response is False
        if packet[0] == (SEGMENT_PLAIN << 1) | 1:
            assert packet == bytes((3, ITEM_LOGIN)) + session_key()[:4]
            self._send_encrypted(bytes((OP_RESPONSE, ITEM_LOGIN, 0)))
            mechanism = bytes(6) + bytes((0b10,))
            self._send_encrypted(
                bytes((OP_PUBLISH, ITEM_MECH_STATUS)) + mechanism
            )
            return

        assert packet[0] == (SEGMENT_CIPHER << 1) | 1
        nonce = (
            self._request_counter.to_bytes(8, "little") + b"\x00" + TOKEN
        )
        self._request_counter += 1
        assert self._aes.decrypt(nonce, packet[1:], b"\x00") == bytes(
            (ITEM_HISTORY, 1)
        )
        self.history_requests += 1
        if not self.history_records:
            return
        self._send_encrypted(
            bytes((OP_RESPONSE, ITEM_HISTORY, 0)) + self.history_records.pop(0)
        )

    async def disconnect(self) -> None:
        self.is_connected = False

    def _send_plain(self, payload: bytes) -> None:
        assert self._callback is not None
        packet = bytes(((SEGMENT_PLAIN << 1) | 1,)) + payload
        self._callback(None, bytearray(packet))

    def _send_encrypted(self, payload: bytes) -> None:
        assert self._callback is not None
        nonce = self._notify_counter.to_bytes(8, "little") + b"\x00" + TOKEN
        self._notify_counter += 1
        packet = bytes(((SEGMENT_CIPHER << 1) | 1,)) + self._aes.encrypt(
            nonce, payload, b"\x00"
        )
        self._callback(None, bytearray(packet))


def service_info(*, has_history: bool) -> Any:
    flags = 0b10 if has_history else 0
    return SimpleNamespace(
        service_uuids=[SERVICE_UUID],
        manufacturer_data={0x055A: bytes((7, 0, flags)) + DEVICE_ID},
        device=SimpleNamespace(address="rotating-address"),
    )


async def install_fake_transport(
    monkeypatch: pytest.MonkeyPatch, peripheral: FakeSesame, *, has_history: bool
) -> None:
    async def resolve(*_args, **_kwargs):
        return service_info(has_history=has_history)

    async def establish(*_args, **_kwargs):
        return peripheral

    monkeypatch.setattr(client_module, "async_resolve_service_info", resolve)
    monkeypatch.setattr(client_module, "establish_connection", establish)


@pytest.mark.asyncio
async def test_status_and_history_are_collected_in_one_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    peripheral = FakeSesame([b"record-one", b"record-two"])
    await install_fake_transport(monkeypatch, peripheral, has_history=True)
    client = SesameStatusClient(
        FakeHomeAssistant(),  # type: ignore[arg-type]
        7,
        DEVICE_ID,
        SECRET_KEY,
        "Test lock",
    )

    result = await client.async_read_status()

    assert result.status.state is LockState.LOCKED
    assert result.history_records == (b"record-one",)
    assert peripheral.history_requests == 1
    assert peripheral.is_connected is False


@pytest.mark.asyncio
async def test_history_is_skipped_without_advertised_pending_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    peripheral = FakeSesame([b"must-not-be-read"])
    await install_fake_transport(monkeypatch, peripheral, has_history=False)
    client = SesameStatusClient(
        FakeHomeAssistant(),  # type: ignore[arg-type]
        7,
        DEVICE_ID,
        SECRET_KEY,
        "Test lock",
    )

    result = await client.async_read_status()

    assert result.history_records == ()
    assert peripheral.history_requests == 0
    assert peripheral.is_connected is False


@pytest.mark.asyncio
async def test_history_timeout_does_not_fail_the_status_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    peripheral = FakeSesame([], terminate_history=False)
    await install_fake_transport(monkeypatch, peripheral, has_history=True)
    monkeypatch.setattr(client_module, "HISTORY_TIMEOUT", 0.01)
    client = SesameStatusClient(
        FakeHomeAssistant(),  # type: ignore[arg-type]
        7,
        DEVICE_ID,
        SECRET_KEY,
        "Test lock",
    )

    result = await client.async_read_status()

    assert result.status.state is LockState.LOCKED
    assert result.history_records == ()
    assert peripheral.history_requests == 1
    assert peripheral.is_connected is False
