"""Parse and decode SESAME share QR data without logging credentials."""

from __future__ import annotations

import base64
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import zxingcpp
from PIL import Image, UnidentifiedImageError

from .const import MODEL_NAMES


class QRCodeError(Exception):
    """Raised when a QR share credential is invalid or unsupported."""


class ManagerCredentialRequired(QRCodeError):
    """Raised when the shared credential is not a manager key."""


@dataclass(frozen=True, slots=True)
class SesameCredential:
    """Minimal credential parsed from a SESAME share QR."""

    model: int
    name: str
    level: int
    secret_key: bytes
    device_id: bytes


def parse_share_uri(uri: str) -> SesameCredential:
    """Parse the compact 39-byte SESAME OS3 share-key payload."""
    try:
        parsed = urlsplit(uri.strip())
        if parsed.scheme.lower() != "ssm":
            raise QRCodeError("Unsupported QR scheme")

        params = parse_qs(parsed.query, keep_blank_values=True)
        if params.get("t", [""])[0] != "sk":
            raise QRCodeError("Unsupported QR type")

        encoded = params["sk"][0].replace(" ", "+")
        encoded += "=" * ((4 - len(encoded) % 4) % 4)
        payload = base64.b64decode(encoded, altchars=b"-_", validate=True)
        if len(payload) != 39:
            raise QRCodeError("Unsupported QR payload length")

        model = payload[0]
        if model not in MODEL_NAMES:
            raise QRCodeError("Unsupported SESAME model")

        level = int(params.get("l", ["-1"])[0])
        return SesameCredential(
            model=model,
            name=params.get("n", [MODEL_NAMES[model]])[0] or MODEL_NAMES[model],
            level=level,
            secret_key=payload[1:17],
            device_id=payload[23:39],
        )
    except QRCodeError:
        raise
    except Exception as err:
        raise QRCodeError("Invalid SESAME share QR") from err


def validate_manager_credential(credential: SesameCredential) -> None:
    """Require a manager credential for local Home Assistant access."""
    if credential.level != 1:
        raise ManagerCredentialRequired("Manager credential required")


def decode_share_qr_image(path: Path) -> SesameCredential:
    """Decode one QR image and parse its SESAME share credential."""
    try:
        with Image.open(path) as image:
            result = zxingcpp.read_barcode(image)
    except (OSError, UnidentifiedImageError) as err:
        raise QRCodeError("Invalid QR image") from err

    if (
        result is None
        or result.format != zxingcpp.BarcodeFormat.QRCode
        or not result.text
    ):
        raise QRCodeError("No QR code found")

    credential = parse_share_uri(result.text)
    validate_manager_credential(credential)
    return credential


def decode_uploaded_qr(
    uploaded_file: AbstractContextManager[Path],
) -> SesameCredential:
    """Decode an HA upload while guaranteeing context-managed cleanup."""
    with uploaded_file as path:
        return decode_share_qr_image(path)
