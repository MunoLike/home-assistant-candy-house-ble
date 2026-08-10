"""Mechanical security-boundary tests."""

from __future__ import annotations

from pathlib import Path

COMPONENT = Path("custom_components/candy_house_ble")


def test_read_only_protocol_has_no_operation_path() -> None:
    """Keep physical commands out of the read-only milestone."""
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in COMPONENT.glob("*.py")
    )

    assert "ITEM_LOCK" not in source
    assert "ITEM_UNLOCK" not in source
    assert "def encrypt" not in source
    assert "async_lock" not in source
    assert "async_unlock" not in source


def test_manifest_uses_final_domain_and_local_polling() -> None:
    import json

    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["domain"] == "candy_house_ble"
    assert manifest["name"] == "CANDY HOUSE BLE"
    assert manifest["iot_class"] == "local_polling"
    assert manifest["requirements"] == ["pyrxing==0.6.1"]
