"""Read-only CANDY HOUSE SESAME OS3 protocol helpers.

This module deliberately has no encrypted transmit path and no generic command
builder. The only packet it can build is the OS3 login packet.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from cryptography.hazmat.primitives import cmac
from cryptography.hazmat.primitives.ciphers import algorithms
from cryptography.hazmat.primitives.ciphers.aead import AESCCM

SEGMENT_PLAIN = 1
SEGMENT_CIPHER = 2

OP_RESPONSE = 7
OP_PUBLISH = 8

ITEM_LOGIN = 2
ITEM_INITIAL = 14
ITEM_MECH_STATUS = 81


class ProtocolError(Exception):
    """Raised for malformed or unauthenticated protocol data."""


class LockState(StrEnum):
    """Position-derived lock states."""

    LOCKED = "locked"
    UNLOCKED = "unlocked"
    MOVED = "moved"


@dataclass(frozen=True, slots=True)
class MechanismStatus:
    """Parsed SESAME 5 mechanism status."""

    state: LockState
    battery_raw: int
    target: int | None
    position: int
    battery_low: bool
    critical: bool
    stopped: bool


@dataclass(frozen=True, slots=True)
class Notification:
    """Decoded protocol notification."""

    opcode: int
    item_code: int
    result_code: int | None
    payload: bytes


class SegmentReceiver:
    """Reassemble the 20-byte GATT segmentation used by SESAME."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, packet: bytes) -> tuple[int, bytes] | None:
        """Feed a characteristic notification and return a complete segment."""
        if not packet:
            raise ProtocolError("Empty BLE segment")

        header = packet[0]
        is_start = bool(header & 1)
        segment_type = header >> 1

        if is_start:
            self._buffer = bytearray(packet[1:])
        elif not self._buffer:
            raise ProtocolError("Continuation segment without a start segment")
        else:
            self._buffer.extend(packet[1:])

        if segment_type == 0:
            return None
        if segment_type not in (SEGMENT_PLAIN, SEGMENT_CIPHER):
            self._buffer.clear()
            raise ProtocolError("Unsupported BLE segment type")

        payload = bytes(self._buffer)
        self._buffer.clear()
        return segment_type, payload


class ReadOnlyCipher:
    """Decrypt SESAME OS3 notifications; encryption is intentionally absent."""

    def __init__(self, session_key: bytes, sesame_token: bytes) -> None:
        if len(session_key) != 16 or len(sesame_token) != 4:
            raise ProtocolError("Invalid OS3 session material")
        self._aes = AESCCM(session_key, tag_length=4)
        self._salt = b"\x00" + sesame_token
        self._decrypt_counter = 0

    def decrypt(self, ciphertext: bytes) -> bytes:
        """Decrypt the next inbound notification."""
        nonce = self._decrypt_counter.to_bytes(8, "little") + self._salt
        self._decrypt_counter += 1
        try:
            return self._aes.decrypt(nonce, ciphertext, b"\x00")
        except Exception as err:
            raise ProtocolError("SESAME notification authentication failed") from err


def build_login_packet(
    secret_key: bytes, sesame_token: bytes
) -> tuple[bytes, ReadOnlyCipher]:
    """Build the sole permitted outbound packet: an OS3 login request."""
    if len(secret_key) != 16 or len(sesame_token) != 4:
        raise ProtocolError("Invalid login material")

    signer = cmac.CMAC(algorithms.AES(secret_key))
    signer.update(sesame_token)
    session_key = signer.finalize()

    packet = bytes((3, ITEM_LOGIN)) + session_key[:4]
    return packet, ReadOnlyCipher(session_key, sesame_token)


def parse_notification(
    segment_type: int, payload: bytes, cipher: ReadOnlyCipher | None
) -> Notification:
    """Parse a complete plain or encrypted notification."""
    if segment_type == SEGMENT_CIPHER:
        if cipher is None:
            raise ProtocolError("Encrypted notification arrived before login")
        payload = cipher.decrypt(payload)
    elif segment_type != SEGMENT_PLAIN:
        raise ProtocolError("Unsupported notification segment type")

    if len(payload) < 2:
        raise ProtocolError("Truncated notification")

    opcode = payload[0]
    item_code = payload[1]
    if opcode == OP_PUBLISH:
        return Notification(opcode, item_code, None, payload[2:])
    if opcode == OP_RESPONSE:
        if len(payload) < 3:
            raise ProtocolError("Truncated response notification")
        return Notification(opcode, item_code, payload[2], payload[3:])
    raise ProtocolError("Unsupported notification opcode")


def parse_mechanism_status(payload: bytes) -> MechanismStatus:
    """Parse the seven-byte SESAME 5 mechanism status."""
    if len(payload) < 7:
        raise ProtocolError("Truncated mechanism status")

    battery_raw = int.from_bytes(payload[0:2], "little")
    raw_target = int.from_bytes(payload[2:4], "little", signed=True)
    target = None if raw_target == -32768 else raw_target
    position = int.from_bytes(payload[4:6], "little", signed=True)
    flags = payload[6]

    if flags & 0b00000010:
        state = LockState.LOCKED
    elif flags & 0b00000100:
        state = LockState.UNLOCKED
    else:
        state = LockState.MOVED

    return MechanismStatus(
        state=state,
        battery_raw=battery_raw,
        target=target,
        position=position,
        battery_low=bool(flags & 0b00100000),
        critical=bool(flags & 0b00001000),
        stopped=bool(flags & 0b00010000),
    )
