"""Tests for the constrained SESAME OS3 protocol."""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives import cmac
from cryptography.hazmat.primitives.ciphers import algorithms
from cryptography.hazmat.primitives.ciphers.aead import AESCCM

from custom_components.candy_house_ble.protocol import (
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
    build_lock_packet,
    build_login_packet,
    build_unlock_packet,
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
