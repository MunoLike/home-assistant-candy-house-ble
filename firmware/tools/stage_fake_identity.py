#!/usr/bin/env python3
"""Stage a disposable fake identity for ESPHome without printing its values."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import tempfile
import uuid
from pathlib import Path

DEFAULT_IDENTITY = Path(
    "/config/.tools/home-assistant-candy-house-ble/credentials/"
    "fake-sesame-identity.json"
)
DEFAULT_OUTPUT = Path(
    "/config/.tools/home-assistant-candy-house-ble/credentials/"
    "fake-sesame-esphome-substitutions.yaml"
)


def _hex_16_bytes(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 32:
        raise ValueError(f"{field} must contain exactly 16 hexadecimal bytes")
    try:
        bytes.fromhex(value)
    except ValueError as err:
        raise ValueError(f"{field} must be hexadecimal") from err
    return value.lower()


def _atomic_write(output_path: Path, content: str) -> None:
    """Atomically write sensitive text with owner-only permissions."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.", dir=output_path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
        temporary_path.replace(output_path)
        output_path.chmod(0o600)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def rotate(identity_path: Path) -> None:
    """Replace only the disposable fake-device identity without revealing it."""
    name = "Fake SESAME Bridge"
    if identity_path.exists():
        current = json.loads(identity_path.read_text(encoding="utf-8"))
        if isinstance(current.get("name"), str):
            name = current["name"]
    identity = {
        "model": 5,
        "name": name,
        "device_id": uuid.uuid4().hex,
        "secret_key": secrets.token_hex(16),
    }
    _atomic_write(identity_path, json.dumps(identity, indent=2) + "\n")


def stage(identity_path: Path, output_path: Path) -> None:
    """Validate JSON identity and atomically write mode-0600 substitutions."""
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    if identity.get("model") != 5:
        raise ValueError("identity must represent a disposable SESAME 5 target")
    device_id = _hex_16_bytes(identity.get("device_id"), "device_id")
    secret_key = _hex_16_bytes(identity.get("secret_key"), "secret_key")

    content = (
        f'fake_sesame_device_id: "{device_id}"\n'
        f'fake_sesame_secret_key: "{secret_key}"\n'
    )
    _atomic_write(output_path, content)


def main() -> None:
    """Parse paths and stage the identity."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--identity", type=Path, default=DEFAULT_IDENTITY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="replace the disposable identity before staging it",
    )
    args = parser.parse_args()
    if args.rotate:
        rotate(args.identity)
    stage(args.identity, args.output)
    print(f"Staged ESPHome substitutions at {args.output} (mode 0600)")


if __name__ == "__main__":
    main()
