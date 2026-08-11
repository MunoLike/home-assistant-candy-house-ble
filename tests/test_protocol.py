"""Tests for the constrained SESAME OS3 protocol."""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives import cmac
from cryptography.hazmat.primitives.ciphers import algorithms
from cryptography.hazmat.primitives.ciphers.aead import AESCCM

from custom_components.candy_house_ble.protocol import (
    BOT_2_RUN_SCRIPT_ITEM_BASE,
    BOT_2_SCRIPT_COUNT,
    ITEM_LOCK,
    ITEM_LOGIN,
    ITEM_MECH_STATUS,
    ITEM_UNLOCK,
    OP_PUBLISH,
    OP_RESPONSE,
    SEGMENT_CIPHER,
    SEGMENT_PLAIN,
    LockState,
    ProtocolError,
    SegmentReceiver,
    build_bot_2_run_script_packet,
    build_lock_packet,
    build_login_packet,
    build_unlock_packet,
    parse_bot_2_mechanism_status,
    parse_mechanism_status,
    parse_notification,
)

SECRET_KEY = bytes.fromhex("00112233445566778899aabbccddeeff")
TOKEN = bytes.fromhex("a1b2c3d4")


def session_key() -> bytes:
    signer = cmac.CMAC(algorithms.AES(SECRET_KEY))
    signer.update(TOKEN)
    return signer.finalize()


def test_segment_receiver_reassembles_notification() -> None:
    receiver = SegmentReceiver()

    assert receiver.feed(bytes((1,)) + b"first") is None
    result = receiver.feed(bytes((SEGMENT_CIPHER << 1,)) + b"second")

    assert result == (SEGMENT_CIPHER, b"firstsecond")


def test_segment_receiver_rejects_orphan_continuation() -> None:
    with pytest.raises(ProtocolError, match="Continuation"):
        SegmentReceiver().feed(bytes((SEGMENT_CIPHER << 1,)) + b"payload")


def test_build_login_packet_is_the_only_authenticated_transmit() -> None:
    packet, _cipher = build_login_packet(SECRET_KEY, TOKEN)

    assert packet == bytes((3, ITEM_LOGIN)) + session_key()[:4]
    assert len(packet) == 6


@pytest.mark.parametrize(
    ("builder", "expected_item", "expected_packet"),
    [
        (build_lock_packet, ITEM_LOCK, "0549ed1487f28ae9"),
        (build_unlock_packet, ITEM_UNLOCK, "0548ed1489b0abd7"),
    ],
)
def test_build_fixed_actuation_packets(
    builder, expected_item: int, expected_packet: str
) -> None:
    _login, cipher = build_login_packet(SECRET_KEY, TOKEN)

    packet = builder(cipher)

    assert packet.hex() == expected_packet
    assert expected_item in (ITEM_LOCK, ITEM_UNLOCK)


def test_outbound_counter_advances_independently() -> None:
    _login, cipher = build_login_packet(SECRET_KEY, TOKEN)

    first = build_lock_packet(cipher)
    second = build_lock_packet(cipher)

    assert first.hex() == "0549ed1487f28ae9"
    assert second.hex() == "0501f54997b9c40a"


@pytest.mark.parametrize(
    ("script_index", "expected_packet"),
    [
        (0, "05b1ed14f834d8ad"),
        (1, "05b0ed14b3665581"),
        (2, "05b7ed14d1e57e63"),
        (3, "05b6ed148d810eb6"),
        (4, "05b5ed145f76585e"),
        (5, "05b4ed1456643077"),
        (6, "05abed148c099cf3"),
        (7, "05aaed14ad2b66cd"),
        (8, "05a9ed14d672bdfa"),
        (9, "05a8ed14a0b59e21"),
    ],
)
def test_build_fixed_bot_2_script_packets(
    script_index: int, expected_packet: str
) -> None:
    _login, cipher = build_login_packet(SECRET_KEY, TOKEN)

    packet = build_bot_2_run_script_packet(cipher, script_index)

    assert BOT_2_RUN_SCRIPT_ITEM_BASE == 170
    assert BOT_2_SCRIPT_COUNT == 10
    assert packet.hex() == expected_packet


@pytest.mark.parametrize("script_index", [-1, 10, True, 1.5, "1"])
def test_bot_2_script_packet_rejects_invalid_index(script_index) -> None:
    _login, cipher = build_login_packet(SECRET_KEY, TOKEN)

    with pytest.raises(ProtocolError, match="script index"):
        build_bot_2_run_script_packet(cipher, script_index)


def test_parse_encrypted_mechanism_notification() -> None:
    mechanism = (
        (5000).to_bytes(2, "little")
        + (-32768).to_bytes(2, "little", signed=True)
        + (-123).to_bytes(2, "little", signed=True)
        + bytes((0b00111010,))
    )
    plaintext = bytes((OP_PUBLISH, ITEM_MECH_STATUS)) + mechanism
    nonce = bytes(8) + b"\x00" + TOKEN
    encrypted = AESCCM(session_key(), tag_length=4).encrypt(
        nonce, plaintext, b"\x00"
    )
    _packet, cipher = build_login_packet(SECRET_KEY, TOKEN)

    notification = parse_notification(SEGMENT_CIPHER, encrypted, cipher)
    status = parse_mechanism_status(notification.payload)

    assert notification.opcode == OP_PUBLISH
    assert notification.item_code == ITEM_MECH_STATUS
    assert status.state is LockState.LOCKED
    assert status.battery_raw == 5000
    assert status.target is None
    assert status.position == -123
    assert status.battery_low is True
    assert status.critical is True
    assert status.stopped is True
    assert status.rssi is None


def test_parse_plain_response() -> None:
    notification = parse_notification(
        SEGMENT_PLAIN, bytes((OP_RESPONSE, ITEM_LOGIN, 0)) + b"ok", None
    )

    assert notification.result_code == 0
    assert notification.payload == b"ok"


@pytest.mark.parametrize(
    ("flags", "state", "stopped"),
    [
        (0b00000010, LockState.LOCKED, False),
        (0b00000100, LockState.UNLOCKED, True),
        (0b00000110, LockState.LOCKED, True),
        (0, LockState.UNLOCKED, False),
    ],
)
def test_parse_bot_2_status(
    flags: int, state: LockState, stopped: bool
) -> None:
    status = parse_bot_2_mechanism_status(
        (3012).to_bytes(2, "little") + bytes((flags,))
    )

    assert status.state is state
    assert status.battery_raw == 3012
    assert status.target is None
    assert status.position is None
    assert status.battery_low is None
    assert status.critical is None
    assert status.stopped is stopped


def test_bot_2_accepts_official_seven_byte_compatibility_status() -> None:
    payload = (
        (5000).to_bytes(2, "little")
        + (-32768).to_bytes(2, "little", signed=True)
        + (-123).to_bytes(2, "little", signed=True)
        + bytes((0b00010010,))
    )

    status = parse_bot_2_mechanism_status(payload)

    assert status.battery_raw == 5000
    assert status.state is LockState.LOCKED
    assert status.position == -123
    assert status.stopped is True


@pytest.mark.parametrize(
    "payload", [b"", b"\x01\x02", bytes(4), bytes(6), bytes(8)]
)
def test_reject_invalid_bot_2_status(payload: bytes) -> None:
    with pytest.raises(ProtocolError, match="Bot 2"):
        parse_bot_2_mechanism_status(payload)


@pytest.mark.parametrize(
    ("flags", "state"),
    [
        (0b00000010, LockState.LOCKED),
        (0b00000100, LockState.UNLOCKED),
        (0, LockState.MOVED),
    ],
)
def test_parse_lock_states(flags: int, state: LockState) -> None:
    payload = bytes(6) + bytes((flags,))

    assert parse_mechanism_status(payload).state is state


def test_reject_bad_encrypted_notification() -> None:
    _packet, cipher = build_login_packet(SECRET_KEY, TOKEN)

    with pytest.raises(ProtocolError, match="authentication"):
        parse_notification(SEGMENT_CIPHER, b"not-authenticated", cipher)
