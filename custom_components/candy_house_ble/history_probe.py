"""Temporary protected sink for reverse-engineering local OS3 history records."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

PROBE_DIRECTORY = Path(".tools/home-assistant-candy-house-ble/history-probe")
PROBE_FILENAME = "records.jsonl"


def append_history_probe_records(
    config_dir: str, records: tuple[bytes, ...]
) -> Path | None:
    """Append opaque records outside Git without logging or exposing them."""
    if not records:
        return None

    directory = Path(config_dir) / PROBE_DIRECTORY
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    path = directory / PROBE_FILENAME
    existing_payloads: set[str] = set()
    if path.exists():
        try:
            existing_payloads = {
                json.loads(line)["payload_hex"]
                for line in path.read_text(encoding="utf-8").splitlines()
                if line
            }
        except (json.JSONDecodeError, KeyError, OSError, TypeError):
            existing_payloads = set()

    records = tuple(
        record for record in records if record.hex() not in existing_payloads
    )
    if not records:
        return path

    received_at = datetime.now(UTC).isoformat()
    lines = "".join(
        json.dumps(
            {
                "received_at": received_at,
                "length": len(record),
                "payload_hex": record.hex(),
            },
            separators=(",", ":"),
        )
        + "\n"
        for record in records
    )
    descriptor = os.open(
        path,
        os.O_APPEND | os.O_CREAT | os.O_WRONLY,
        0o600,
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as probe_file:
            descriptor = -1
            probe_file.write(lines)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return path
