"""Deterministic tests for the fake SESAME host-side reference model."""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESCCM

from firmware.reference.fake_sesame_protocol import (
    COMPONENT_VERSION,
    ITEM_LOCK,
    ITEM_MECH_SETTING,
    ITEM_MECH_STATUS,
    ITEM_TIME,
    ITEM_UNLOCK,
    ITEM_VERSION_TAG,
    SEGMENT_CIPHER,
    FakeSesameEvent,
    FakeSesameProtocolError,
    FakeSesameSession,
    SegmentAccumulator,
    build_advertisement,
    derive_device_address,
    derive_session_key,
    segment_payload,
)

DEVICE_ID = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
SECRET_KEY = bytes.fromhex("00112233445566778899aabbccddeeff")
CHALLENGE = bytes.fromhex("a1b2c3d4")

LOGIN_PACKET = bytes.fromhex("0302ca62eb0c")
LOCK_PACKET = bytes.fromhex("0549ed1487f28ae9")
UNLOCK_PACKET = bytes.fromhex("0548ed1489b0abd7")


def test_public_address_vector_and_static_random_bits() -> None:
    address = derive_device_address(DEVICE_ID)

    assert address.hex() == "e950b4bd11ae"
    assert address[0] & 0xC0 == 0xC0


def test_exact_legacy_advertisement() -> None:
    advertisement = build_advertisement(DEVICE_ID)

    assert advertisement.hex() == (
        "02010616ff5a05050001"
        "000102030405060708090a0b0c0d0e0f"
        "030381fd"
    )
    assert len(advertisement) == 30


def test_public_session_and_login_response_vectors() -> None:
    assert derive_session_key(SECRET_KEY, CHALLENGE).hex() == (
        "ca62eb0cf87a39b1b4d0638b695299bf"
    )
    session = FakeSesameSession(SECRET_KEY, CHALLENGE)

    assert session.initial_notification() == (bytes.fromhex("03080ea1b2c3d4"),)
    result = session.process_write(LOGIN_PACKET, 0x12345678)

    assert result.event is None
    assert result.notifications == (
        bytes.fromhex("051cef1a689934b7d8b77b12"),
    )
    assert session.authenticated is True


@pytest.mark.parametrize(
    ("command", "event", "ack"),
    [
        (LOCK_PACKET, FakeSesameEvent.LOCK, "0554a7479b1bda59"),
        (UNLOCK_PACKET, FakeSesameEvent.UNLOCK, "0554a647b9a879d9"),
    ],
)
def test_only_authenticated_lock_and_unlock_emit_events(
    command: bytes, event: FakeSesameEvent, ack: str
) -> None:
    session = FakeSesameSession(SECRET_KEY, CHALLENGE)
    session.process_write(LOGIN_PACKET, 0x12345678)

    result = session.process_write(command, 0)

    assert result.event is event
    assert result.notifications == (bytes.fromhex(ack),)


def test_authenticated_time_update_is_acknowledged_without_event() -> None:
    session = FakeSesameSession(SECRET_KEY, CHALLENGE)
    session.process_write(LOGIN_PACKET, 0x12345678)
    session_key = derive_session_key(SECRET_KEY, CHALLENGE)
    nonce = bytes(8) + b"\x00" + CHALLENGE
    command = AESCCM(session_key, tag_length=4).encrypt(
        nonce, bytes((ITEM_TIME, 0x78, 0x56, 0x34, 0x12)), b"\x00"
    )

    result = session.process_write(bytes((5,)) + command, 0)

    assert result.event is None
    assert len(result.notifications) == 1
    response_packet = result.notifications[0]
    response_nonce = (1).to_bytes(8, "little") + b"\x00" + CHALLENGE
    assert AESCCM(session_key, tag_length=4).decrypt(
        response_nonce, response_packet[1:], b"\x00"
    ) == bytes((7, ITEM_TIME, 0))
    assert session.closed is False


def test_authenticated_version_read_returns_fixed_fake_version() -> None:
    session = FakeSesameSession(SECRET_KEY, CHALLENGE)
    session.process_write(LOGIN_PACKET, 0x12345678)
    session_key = derive_session_key(SECRET_KEY, CHALLENGE)
    command_nonce = bytes(8) + b"\x00" + CHALLENGE
    command = AESCCM(session_key, tag_length=4).encrypt(
        command_nonce, bytes((ITEM_VERSION_TAG,)), b"\x00"
    )

    result = session.process_write(bytes((5,)) + command, 0)

    assert result.event is None
    response_nonce = (1).to_bytes(8, "little") + b"\x00" + CHALLENGE
    assert AESCCM(session_key, tag_length=4).decrypt(
        response_nonce, result.notifications[0][1:], b"\x00"
    ) == bytes((7, ITEM_VERSION_TAG, 0)) + f"fake-{COMPONENT_VERSION}".encode()


@pytest.mark.parametrize(("locked", "flags"), [(True, 0x12), (False, 0x10)])
def test_mechanism_status_publish_completes_app_login(
    locked: bool, flags: int
) -> None:
    session = FakeSesameSession(SECRET_KEY, CHALLENGE)
    session.process_write(LOGIN_PACKET, 0x12345678)
    session_key = derive_session_key(SECRET_KEY, CHALLENGE)

    packet = session.mech_status_notification(locked=locked)[0]

    nonce = (1).to_bytes(8, "little") + b"\x00" + CHALLENGE
    plaintext = AESCCM(session_key, tag_length=4).decrypt(
        nonce, packet[1:], b"\x00"
    )
    assert plaintext == bytes(
        (8, ITEM_MECH_STATUS, 0x70, 0x17, 0x00, 0x80, 0, 0, flags)
    )


def test_mechanism_setting_publish_precedes_logged_in_state() -> None:
    session = FakeSesameSession(SECRET_KEY, CHALLENGE)
    session.process_write(LOGIN_PACKET, 0x12345678)
    session_key = derive_session_key(SECRET_KEY, CHALLENGE)

    packet = session.mech_setting_notification()[0]

    nonce = (1).to_bytes(8, "little") + b"\x00" + CHALLENGE
    plaintext = AESCCM(session_key, tag_length=4).decrypt(
        nonce, packet[1:], b"\x00"
    )
    assert plaintext == bytes(
        (8, ITEM_MECH_SETTING, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00)
    )


def test_wrong_login_fails_closed_without_event() -> None:
    session = FakeSesameSession(SECRET_KEY, CHALLENGE)

    with pytest.raises(FakeSesameProtocolError, match="Login authentication"):
        session.process_write(bytes.fromhex("030200000000"), 0)

    assert session.authenticated is False
    assert session.closed is True


def test_command_before_login_fails_closed_without_event() -> None:
    session = FakeSesameSession(SECRET_KEY, CHALLENGE)

    with pytest.raises(FakeSesameProtocolError, match="Expected login"):
        session.process_write(LOCK_PACKET, 0)

    assert session.closed is True


def test_replay_does_not_emit_a_second_event() -> None:
    session = FakeSesameSession(SECRET_KEY, CHALLENGE)
    session.process_write(LOGIN_PACKET, 0)
    assert session.process_write(LOCK_PACKET, 0).event is FakeSesameEvent.LOCK

    with pytest.raises(FakeSesameProtocolError, match="authentication"):
        session.process_write(LOCK_PACKET, 0)

    assert session.closed is True


def test_tampered_command_fails_closed_without_event() -> None:
    session = FakeSesameSession(SECRET_KEY, CHALLENGE)
    session.process_write(LOGIN_PACKET, 0)
    tampered = bytearray(LOCK_PACKET)
    tampered[-1] ^= 1

    with pytest.raises(FakeSesameProtocolError, match="authentication"):
        session.process_write(bytes(tampered), 0)

    assert session.closed is True


def test_unknown_authenticated_command_fails_closed_without_event() -> None:
    session = FakeSesameSession(SECRET_KEY, CHALLENGE)
    session.process_write(LOGIN_PACKET, 0)
    # This valid packet decrypts to unlock, but the item byte is changed by using
    # an independent session-compatible ciphertext from a non-allowlisted item.
    session_key = derive_session_key(SECRET_KEY, CHALLENGE)
    nonce = bytes(8) + b"\x00" + CHALLENGE
    ciphertext = AESCCM(session_key, tag_length=4).encrypt(
        nonce, bytes((ITEM_LOCK - 1, 0, 14)), b"\x00"
    )

    with pytest.raises(FakeSesameProtocolError, match="Unsupported command"):
        session.process_write(bytes((5,)) + ciphertext, 0)

    assert session.closed is True


def test_segment_round_trip_and_bound() -> None:
    payload = bytes(range(100))
    receiver = SegmentAccumulator()
    result = None

    for packet in segment_payload(SEGMENT_CIPHER, payload):
        assert len(packet) <= 20
        result = receiver.feed(packet)

    assert result == (SEGMENT_CIPHER, payload)

    receiver = SegmentAccumulator(max_size=20)
    assert receiver.feed(b"\x01" + bytes(19)) is None
    with pytest.raises(FakeSesameProtocolError, match="bounded"):
        receiver.feed(b"\x00" + bytes(2))


def test_constants_match_remote_commands() -> None:
    assert ITEM_LOCK == 82
    assert ITEM_UNLOCK == 83
