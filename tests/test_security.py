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
    assert source.count("def build_bot_2_run_script_packet") == 1
    assert "def build_bot_2_click_packet" not in source
    assert "def build_command_packet" not in source
    assert "ITEM_TOGGLE" not in source
    assert "ITEM_OPEN" not in source
    assert "ITEM_REGISTER" not in source
    assert "build_bot_command_packet" not in source


def test_current_script_entity_surface_is_removed() -> None:
    """Allow the legacy ID only in migration code, never as an entity."""
    button_source = (COMPONENT / "button.py").read_text(encoding="utf-8")
    translation_sources = [
        (COMPONENT / "strings.json").read_text(encoding="utf-8"),
        (COMPONENT / "translations" / "en.json").read_text(encoding="utf-8"),
        (COMPONENT / "translations" / "ja.json").read_text(encoding="utf-8"),
    ]

    assert "run_current_script" not in button_source
    assert all("run_current_script" not in source for source in translation_sources)
    assert all('"run_script"' in source for source in translation_sources)


def test_manifest_uses_final_domain_and_local_polling() -> None:
    import json

    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["domain"] == "candy_house_ble"
    assert manifest["name"] == "CANDY HOUSE BLE"
    assert manifest["iot_class"] == "local_polling"
    assert manifest["requirements"] == ["pyrxing==0.6.1"]
