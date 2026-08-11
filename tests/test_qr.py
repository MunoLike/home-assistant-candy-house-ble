"""Tests for local SESAME QR decoding."""

from __future__ import annotations

import base64
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlencode

import pytest
import qrcode

from custom_components.candy_house_ble.qr import (
    QRCodeError,
    decode_share_qr_image,
    decode_uploaded_qr,
    parse_share_uri,
    validate_manager_credential,
)

SECRET_KEY = bytes.fromhex("00112233445566778899aabbccddeeff")
DEVICE_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def build_uri(*, model: int = 7, level: int = 1, name: str = "Test lock") -> str:
    """Build a synthetic SESAME share URI."""
    payload = bytes((model,)) + SECRET_KEY + bytes(6) + DEVICE_ID.bytes
    encoded = base64.b64encode(payload).decode().rstrip("=")
    return f"ssm://UI?{urlencode({'t': 'sk', 'sk': encoded, 'l': level, 'n': name})}"


def write_qr(path: Path, uri: str) -> None:
    """Write a synthetic QR image."""
    image = qrcode.make(uri)
    image.save(path)


@contextmanager
def deleting_upload(path: Path):
    """Model HA's uploaded-file context manager."""
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def test_parse_manager_share_uri() -> None:
    credential = parse_share_uri(build_uri(name="玄関の鍵"))

    assert credential.model == 7
    assert credential.name == "玄関の鍵"
    assert credential.level == 1
    assert credential.secret_key == SECRET_KEY
    assert credential.device_id == DEVICE_ID.bytes
    validate_manager_credential(credential)


def test_parse_bot_2_manager_share_uri() -> None:
    credential = parse_share_uri(build_uri(model=17, name="Test Bot 2"))

    assert credential.model == 17
    assert credential.name == "Test Bot 2"
    assert credential.level == 1
    assert credential.secret_key == SECRET_KEY
    assert credential.device_id == DEVICE_ID.bytes
    validate_manager_credential(credential)


@pytest.mark.parametrize("level", [0, 2, 3])
def test_reject_non_manager_levels(level: int) -> None:
    credential = parse_share_uri(build_uri(level=level))

    with pytest.raises(QRCodeError, match="Manager"):
        validate_manager_credential(credential)


def test_reject_unsupported_model() -> None:
    with pytest.raises(QRCodeError, match="model"):
        parse_share_uri(build_uri(model=99))


@pytest.mark.parametrize(
    "uri",
    [
        "https://example.invalid/?t=sk&sk=AAAA&l=1",
        "ssm://UI?t=unknown&sk=AAAA&l=1",
        "ssm://UI?t=sk&sk=not-base64!&l=1",
    ],
)
def test_reject_invalid_uri(uri: str) -> None:
    with pytest.raises(QRCodeError):
        parse_share_uri(uri)


def test_decode_qr_image(tmp_path: Path) -> None:
    path = tmp_path / "manager.png"
    write_qr(path, build_uri())

    credential = decode_share_qr_image(path)

    assert credential.secret_key == SECRET_KEY
    assert credential.device_id == DEVICE_ID.bytes


def test_uploaded_image_removed_after_success(tmp_path: Path) -> None:
    path = tmp_path / "manager.png"
    write_qr(path, build_uri())

    decode_uploaded_qr(deleting_upload(path))

    assert not path.exists()


def test_uploaded_image_removed_after_failure(tmp_path: Path) -> None:
    path = tmp_path / "invalid.png"
    path.write_bytes(b"not an image")

    with pytest.raises(QRCodeError):
        decode_uploaded_qr(deleting_upload(path))

    assert not path.exists()
