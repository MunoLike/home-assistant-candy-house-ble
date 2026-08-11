"""Mechanical security-boundary tests."""

from __future__ import annotations

from pathlib import Path

COMPONENT = Path("custom_components/candy_house_ble")


def test_protocol_operation_surface_is_fixed() -> None:
    """Keep the physical command surface limited to lock and unlock."""
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in COMPONENT.glob("*.py")
    )

    assert source.count("def build_lock_packet") == 1
    assert source.count("def build_unlock_packet") == 1
    assert "def build_command_packet" not in source
    assert "ITEM_TOGGLE" not in source
    assert "ITEM_OPEN" not in source
    assert "ITEM_REGISTER" not in source


def test_manifest_uses_final_domain_and_local_polling() -> None:
    import json

    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["domain"] == "candy_house_ble"
    assert manifest["name"] == "CANDY HOUSE BLE"
    assert manifest["iot_class"] == "local_polling"
    assert manifest["requirements"] == ["pyrxing==0.6.1"]
