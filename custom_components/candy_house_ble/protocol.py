"""Constrained CANDY HOUSE SESAME OS3 protocol helpers.

Only login, lock, unlock, and the ten fixed Bot 2/3 script packets can be built.
There is deliberately no generic encrypted-command builder.
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
ITEM_LOCK = 82
ITEM_UNLOCK = 83

# Official Android SDK commit 17b39dd19c0f0a2bb27fb8c6617850fc56f4438a
# maps Bot 2/3 script slots 0..9 to item codes 170..179.
BOT_2_RUN_SCRIPT_ITEM_BASE = 170
BOT_2_SCRIPT_COUNT = 10

HISTORY_TAG_ANDROID_USER_BLE = bytes((0, 14))


class ProtocolError(Exception):
    """Raised for malformed or unauthenticated protocol data."""


class LockState(StrEnum):
    """Position-derived lock states."""

    LOCKED = "locked"
    UNLOCKED = "unlocked"
    MOVED = "moved"


@dataclass(frozen=True, slots=True)
class MechanismStatus:
    """Parsed mechanism status shared by supported OS3 devices."""

    state: LockState
    battery_raw: int
    target: int | None
    position: int | None
    battery_low: bool | None
    critical: bool | None
    stopped: bool
    rssi: int | None = None


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


class SesameSessionCipher:
    """Encrypt and decrypt one authenticated SESAME OS3 BLE session."""

    def __init__(self, session_key: bytes, sesame_token: bytes) -> None:
        if len(session_key) != 16 or len(sesame_token) != 4:
            raise ProtocolError("Invalid OS3 session material")
        self._aes = AESCCM(session_key, tag_length=4)
        self._salt = b"\x00" + sesame_token
        self._encrypt_counter = 0
        self._decrypt_counter = 0

    def _nonce(self, counter: int) -> bytes:
        return counter.to_bytes(8, "little") + self._salt

    def encrypt(self, plaintext: bytes) -> bytes:
        """Encrypt the next outbound packet."""
        nonce = self._nonce(self._encrypt_counter)
        ciphertext = self._aes.encrypt(nonce, plaintext, b"\x00")
        self._encrypt_counter += 1
        return ciphertext

    def decrypt(self, ciphertext: bytes) -> bytes:
        """Decrypt the next inbound notification."""
        nonce = self._nonce(self._decrypt_counter)
        try:
            plaintext = self._aes.decrypt(nonce, ciphertext, b"\x00")
        except Exception as err:
            raise ProtocolError("SESAME notification authentication failed") from err
        self._decrypt_counter += 1
        return plaintext


def build_login_packet(
    secret_key: bytes, sesame_token: bytes
) -> tuple[bytes, SesameSessionCipher]:
    """Build the sole permitted outbound packet: an OS3 login request."""
    if len(secret_key) != 16 or len(sesame_token) != 4:
        raise ProtocolError("Invalid login material")

    signer = cmac.CMAC(algorithms.AES(secret_key))
    signer.update(sesame_token)
    session_key = signer.finalize()

    packet = bytes((3, ITEM_LOGIN)) + session_key[:4]
    return packet, SesameSessionCipher(session_key, sesame_token)


def build_lock_packet(cipher: SesameSessionCipher) -> bytes:
    """Build the only permitted SESAME lock packet."""
    plaintext = bytes((ITEM_LOCK,)) + HISTORY_TAG_ANDROID_USER_BLE
    return bytes(((SEGMENT_CIPHER << 1) | 1,)) + cipher.encrypt(plaintext)


def build_unlock_packet(cipher: SesameSessionCipher) -> bytes:
    """Build the only permitted SESAME unlock packet."""
    plaintext = bytes((ITEM_UNLOCK,)) + HISTORY_TAG_ANDROID_USER_BLE
    return bytes(((SEGMENT_CIPHER << 1) | 1,)) + cipher.encrypt(plaintext)


def bot_2_run_script_item_code(script_index: int) -> int:
    """Return the allowlisted Bot 2/3 item code for a script slot."""
    if type(script_index) is not int or not 0 <= script_index < BOT_2_SCRIPT_COUNT:
        raise ProtocolError("Invalid SESAME Bot 2/3 script index")
    return BOT_2_RUN_SCRIPT_ITEM_BASE + script_index


def build_bot_2_run_script_packet(
    cipher: SesameSessionCipher, script_index: int
) -> bytes:
    """Build one allowlisted SESAME Bot 2/3 script packet."""
    item_code = bot_2_run_script_item_code(script_index)
    plaintext = bytes((item_code,)) + HISTORY_TAG_ANDROID_USER_BLE
    return bytes(((SEGMENT_CIPHER << 1) | 1,)) + cipher.encrypt(plaintext)


def parse_notification(
    segment_type: int, payload: bytes, cipher: SesameSessionCipher | None
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
    """Parse the seven-byte SESAME 5/6 mechanism status."""
    if len(payload) < 7:
        raise ProtocolError("Truncated mechanism status")

    battery_raw = int.from_bytes(payload[0:2], "little")
    raw_target = int.from_bytes(payload[2:4], "little", signed=True)
    target = None if raw_target == -32768 else raw_target
    position = int.from_bytes(payload[4:6], "little", signed=True)
    flags = payload[6]

    # The official CHSesame5MechStatus shared by SESAME 5/6 defines bit 1 as
    # isInLockRange.  Unlike Bot 2/3, bit 2 is not an unlocked-state flag.
    state = (
        LockState.LOCKED
        if flags & 0b00000010
        else LockState.UNLOCKED
    )

    return MechanismStatus(
        state=state,
        battery_raw=battery_raw,
        target=target,
        position=position,
        battery_low=bool(flags & 0b00100000),
        critical=bool(flags & 0b00001000),
        stopped=bool(flags & 0b00010000),
    )


def parse_bot_2_mechanism_status(payload: bytes) -> MechanismStatus:
    """Parse the official three-byte SESAME Bot 2/3 mechanism status."""
    if len(payload) == 7:
        return parse_mechanism_status(payload)
    if len(payload) != 3:
        raise ProtocolError("Invalid SESAME Bot 2/3 mechanism status")

    flags = payload[2]
    return MechanismStatus(
        state=(
            LockState.LOCKED
            if flags & 0b00000010
            else LockState.UNLOCKED
        ),
        battery_raw=int.from_bytes(payload[0:2], "little"),
        target=None,
        position=None,
        battery_low=None,
        critical=None,
        stopped=bool(flags & 0b00000100),
    )
