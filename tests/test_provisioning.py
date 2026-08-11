"""Tests for read-only Remote Nano provisioning support."""

from __future__ import annotations

from pathlib import Path

import pytest

from custom_components.candy_house_ble.protocol import ProtocolError
from custom_components.candy_house_ble.provisioning import (
    TARGET_SLOT_SIZE,
    parse_remote_nano_target_summary,
)


def test_empty_remote_target_slots_are_redacted_to_counts() -> None:
    summary = parse_remote_nano_target_summary(bytes(TARGET_SLOT_SIZE * 3))

    assert summary.total_slots == 3
    assert summary.occupied_slots == 0
    assert summary.os3_slots == 0
    assert summary.legacy_slots == 0
    assert summary.empty is True


def test_mixed_target_slots_are_counted_without_identifiers() -> None:
    os3 = bytearray(TARGET_SLOT_SIZE)
    os3[:16] = bytes(range(16))
    os3[21] = 0
    os3[22] = 1
    legacy = bytearray(TARGET_SLOT_SIZE)
    legacy[:16] = bytes(range(16, 32))
    legacy[21] = 1
    legacy[22] = 2

    summary = parse_remote_nano_target_summary(
        bytes(os3) + bytes(TARGET_SLOT_SIZE) + bytes(legacy)
    )

    assert summary.total_slots == 3
    assert summary.occupied_slots == 2
    assert summary.os3_slots == 1
    assert summary.legacy_slots == 1
    assert summary.empty is False
    assert not hasattr(summary, "device_ids")


@pytest.mark.parametrize("payload", [b"", bytes(22), bytes(24)])
def test_invalid_target_list_is_rejected(payload: bytes) -> None:
    with pytest.raises(ProtocolError, match="target-list"):
        parse_remote_nano_target_summary(payload)


def test_read_only_module_has_no_target_mutation_item_codes() -> None:
    source = Path(
        "custom_components/candy_house_ble/provisioning.py"
    ).read_text(encoding="utf-8")

    assert "ITEM_TARGET_LIST = 102" in source
    assert "ITEM_ADD_TARGET" not in source
    assert "ITEM_REMOVE_TARGET" not in source
