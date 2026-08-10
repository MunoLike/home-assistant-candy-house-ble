"""Tests for the temporary protected history probe sink."""

from __future__ import annotations

import json
import stat
from pathlib import Path

from custom_components.candy_house_ble.history_probe import (
    append_history_probe_records,
)


def test_history_probe_is_private_and_append_only(tmp_path: Path) -> None:
    path = append_history_probe_records(str(tmp_path), (b"first", b"second"))
    assert path is not None
    append_history_probe_records(str(tmp_path), (b"second", b"third"))

    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert [item["payload_hex"] for item in records] == [
        b"first".hex(),
        b"second".hex(),
        b"third".hex(),
    ]
    assert [item["length"] for item in records] == [5, 6, 5]


def test_empty_history_probe_writes_nothing(tmp_path: Path) -> None:
    assert append_history_probe_records(str(tmp_path), ()) is None
    assert not (tmp_path / ".tools").exists()
