"""Host-side reference model for the constrained fake SESAME peripheral.

This module is intentionally independent from ESPHome.  It fixes the protocol
state machine and crypto vectors before the same behavior is implemented in
firmware.  It never provisions a Remote and exposes no generic command path.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from cryptography.hazmat.primitives import cmac
from cryptography.hazmat.primitives.ciphers import algorithms
from cryptography.hazmat.primitives.ciphers.aead import AESCCM

COMPONENT_VERSION = (
    Path(__file__).parents[1] / "components/fake_sesame/VERSION"
).read_text(encoding="utf-8").strip()

SEGMENT_PLAIN = 1
SEGMENT_CIPHER = 2
MAX_FRAME_SIZE = 256

OP_RESPONSE = 7
OP_PUBLISH = 8

ITEM_LOGIN = 2
ITEM_VERSION_TAG = 5
ITEM_TIME = 8
ITEM_INITIAL = 14
ITEM_MECH_SETTING = 80
ITEM_MECH_STATUS = 81
ITEM_LOCK = 82
ITEM_UNLOCK = 83

SESAME_5_MODEL = 5
SESAME_SERVICE_UUID = 0xFD81
COMPANY_ID = 0x055A


class FakeSesameProtocolError(Exception):
    """Raised when a peer violates the constrained fake SESAME protocol."""


class FakeSesameEvent(StrEnum):
    """The only two events emitted by the fake peripheral."""

    LOCK = "lock"
    UNLOCK = "unlock"


@dataclass(frozen=True, slots=True)
class ServerResult:
    """Result of processing one Remote write."""

    notifications: tuple[bytes, ...] = ()
    event: FakeSesameEvent | None = None


def _aes_cmac(key: bytes, data: bytes) -> bytes:
    if len(key) != 16:
        raise FakeSesameProtocolError("AES-CMAC key must be 16 bytes")
    signer = cmac.CMAC(algorithms.AES(key))
    signer.update(data)
    return signer.finalize()


def derive_device_address(device_id: bytes) -> bytes:
    """Derive the six ESP-IDF/display-order static-random address bytes."""
    if len(device_id) != 16:
        raise FakeSesameProtocolError("Device ID must be 16 bytes")
    address = bytearray(_aes_cmac(device_id, b"candy")[:6])
    address[5] = (address[5] & 0x3F) | 0xC0
    return bytes(reversed(address))


def build_advertisement(device_id: bytes) -> bytes:
    """Build the exact 30-byte legacy SESAME 5 advertising payload."""
    if len(device_id) != 16:
        raise FakeSesameProtocolError("Device ID must be 16 bytes")
    return (
        bytes((2, 1, 6, 0x16, 0xFF, COMPANY_ID & 0xFF, COMPANY_ID >> 8))
        + bytes((SESAME_5_MODEL, 0, 1))
        + device_id
        + bytes((3, 3, SESAME_SERVICE_UUID & 0xFF, SESAME_SERVICE_UUID >> 8))
    )


def derive_session_key(secret_key: bytes, challenge: bytes) -> bytes:
    """Derive one session key from the disposable fake-device secret."""
    if len(secret_key) != 16 or len(challenge) != 4:
        raise FakeSesameProtocolError("Invalid session material")
    return _aes_cmac(secret_key, challenge)


def segment_payload(segment_type: int, payload: bytes) -> tuple[bytes, ...]:
    """Split a logical payload into the SESAME 20-byte GATT framing."""
    if segment_type not in (SEGMENT_PLAIN, SEGMENT_CIPHER):
        raise FakeSesameProtocolError("Unsupported segment type")
    if not payload:
        raise FakeSesameProtocolError("Empty logical payload")

    chunks = tuple(payload[index : index + 19] for index in range(0, len(payload), 19))
    if len(chunks) == 1:
        return (bytes(((segment_type << 1) | 1,)) + chunks[0],)
    packets = [b"\x01" + chunks[0]]
    packets.extend(b"\x00" + chunk for chunk in chunks[1:-1])
    packets.append(bytes((segment_type << 1,)) + chunks[-1])
    return tuple(packets)


class SegmentAccumulator:
    """Bounded SESAME frame reassembly for writes from a Remote."""

    def __init__(self, max_size: int = MAX_FRAME_SIZE) -> None:
        self._buffer = bytearray()
        self._max_size = max_size

    def reset(self) -> None:
        """Discard an incomplete frame."""
        self._buffer.clear()

    def feed(self, packet: bytes) -> tuple[int, bytes] | None:
        """Accept one GATT packet and return a completed logical payload."""
        if not packet:
            raise FakeSesameProtocolError("Empty BLE segment")
        header = packet[0]
        is_start = bool(header & 1)
        segment_type = header >> 1

        if is_start:
            self._buffer = bytearray(packet[1:])
        elif not self._buffer:
            raise FakeSesameProtocolError("Continuation without start")
        else:
            self._buffer.extend(packet[1:])

        if len(self._buffer) > self._max_size:
            self.reset()
            raise FakeSesameProtocolError("Frame exceeds bounded buffer")
        if segment_type == 0:
            return None
        if segment_type not in (SEGMENT_PLAIN, SEGMENT_CIPHER):
            self.reset()
            raise FakeSesameProtocolError("Unsupported segment type")

        payload = bytes(self._buffer)
        self.reset()
        return segment_type, payload


class _ServerCipher:
    """AES-CCM directions as observed from the fake peripheral."""

    def __init__(self, session_key: bytes, challenge: bytes) -> None:
        self._aes = AESCCM(session_key, tag_length=4)
        self._salt = b"\x00" + challenge
        self._tx_counter = 0
        self._rx_counter = 0

    def _nonce(self, counter: int) -> bytes:
        return counter.to_bytes(8, "little") + self._salt

    def encrypt(self, plaintext: bytes) -> bytes:
        ciphertext = self._aes.encrypt(
            self._nonce(self._tx_counter), plaintext, b"\x00"
        )
        self._tx_counter += 1
        return ciphertext

    def decrypt(self, ciphertext: bytes) -> bytes:
        try:
            plaintext = self._aes.decrypt(
                self._nonce(self._rx_counter), ciphertext, b"\x00"
            )
        except Exception as err:
            raise FakeSesameProtocolError(
                "Encrypted write authentication failed"
            ) from err
        self._rx_counter += 1
        return plaintext


class FakeSesameSession:
    """One single-client, fail-closed fake SESAME BLE session."""

    def __init__(self, secret_key: bytes, challenge: bytes) -> None:
        if len(secret_key) != 16 or len(challenge) != 4:
            raise FakeSesameProtocolError("Invalid session material")
        self._secret_key = secret_key
        self._challenge = challenge
        self._session_key = derive_session_key(secret_key, challenge)
        self._cipher = _ServerCipher(self._session_key, challenge)
        self._receiver = SegmentAccumulator()
        self.authenticated = False
        self.closed = False

    def initial_notification(self) -> tuple[bytes, ...]:
        """Return the challenge publication sent after notification subscribe."""
        payload = bytes((OP_PUBLISH, ITEM_INITIAL)) + self._challenge
        return segment_payload(SEGMENT_PLAIN, payload)

    def mech_status_notification(self, *, locked: bool = True) -> tuple[bytes, ...]:
        """Publish a stationary synthetic mechanism state after login."""
        if not self.authenticated or self.closed:
            self._fail("Mechanism status requires an authenticated session")
        flags = 0x10 | (0x02 if locked else 0)
        payload = bytes(
            (OP_PUBLISH, ITEM_MECH_STATUS, 0x70, 0x17, 0x00, 0x80, 0, 0, flags)
        )
        return segment_payload(SEGMENT_CIPHER, self._cipher.encrypt(payload))

    def mech_setting_notification(self) -> tuple[bytes, ...]:
        """Publish safe synthetic settings before the logged-in state."""
        if not self.authenticated or self.closed:
            self._fail("Mechanism setting requires an authenticated session")
        payload = bytes(
            (OP_PUBLISH, ITEM_MECH_SETTING, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00)
        )
        return segment_payload(SEGMENT_CIPHER, self._cipher.encrypt(payload))

    def _fail(self, message: str) -> None:
        self.closed = True
        self.authenticated = False
        self._receiver.reset()
        raise FakeSesameProtocolError(message)

    def process_write(self, packet: bytes, timestamp: int) -> ServerResult:
        """Process one write; only authenticated lock/unlock can emit an event."""
        if self.closed:
            raise FakeSesameProtocolError("Session is closed")
        if not 0 <= timestamp <= 0xFFFFFFFF:
            self._fail("Timestamp out of range")

        try:
            complete = self._receiver.feed(packet)
        except FakeSesameProtocolError:
            self.closed = True
            raise
        if complete is None:
            return ServerResult()

        segment_type, payload = complete
        if not self.authenticated:
            if segment_type != SEGMENT_PLAIN or len(payload) != 5:
                self._fail("Expected login before command")
            if payload[0] != ITEM_LOGIN or not hmac.compare_digest(
                payload[1:], self._session_key[:4]
            ):
                self._fail("Login authentication failed")
            self.authenticated = True
            response = bytes((OP_RESPONSE, ITEM_LOGIN, 0)) + timestamp.to_bytes(
                4, "little"
            )
            notifications = segment_payload(
                SEGMENT_CIPHER, self._cipher.encrypt(response)
            )
            return ServerResult(notifications)

        if segment_type != SEGMENT_CIPHER:
            self._fail("Plaintext command after login")
        try:
            plaintext = self._cipher.decrypt(payload)
        except FakeSesameProtocolError:
            self.closed = True
            raise
        if not plaintext:
            self._fail("Empty command")

        item_code = plaintext[0]
        response_payload = b""
        if item_code == ITEM_VERSION_TAG:
            if len(plaintext) != 1:
                self._fail("Invalid version command")
            event = None
            response_payload = f"fake-{COMPONENT_VERSION}".encode()
        elif item_code == ITEM_TIME:
            if len(plaintext) != 5:
                self._fail("Invalid time command")
            event = None
        elif item_code == ITEM_LOCK:
            event = FakeSesameEvent.LOCK
        elif item_code == ITEM_UNLOCK:
            event = FakeSesameEvent.UNLOCK
        else:
            self._fail("Unsupported command")

        response = bytes((OP_RESPONSE, item_code, 0)) + response_payload
        return ServerResult(
            segment_payload(SEGMENT_CIPHER, self._cipher.encrypt(response)),
            event,
        )
