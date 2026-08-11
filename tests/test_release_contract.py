"""Structural checks for the unified HACS and ESPHome release contract."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_validate_workflow_compiles_the_firmware_example() -> None:
    workflow = (ROOT / ".github/workflows/validate.yml").read_text(
        encoding="utf-8"
    )

    assert "esphome config firmware/examples/fake-sesame-atom-s3-lite.yaml" in workflow
    assert "esphome compile firmware/examples/fake-sesame-atom-s3-lite.yaml" in workflow


def test_release_workflow_versions_and_validates_both_products() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(
        encoding="utf-8"
    )

    assert "firmware/components/fake_sesame/VERSION" in workflow
    assert "esphome compile" in workflow
    assert "git push --atomic" in workflow
    assert 'gh release create "$RELEASE_TAG"' in workflow


def test_readme_pins_esphome_to_the_shared_release_version() -> None:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert (
        f"github://Khronos31/home-assistant-candy-house-ble@v{version}"
        in readme
    )


def test_firmware_build_define_uses_the_synchronized_version() -> None:
    component = (
        ROOT / "firmware/components/fake_sesame/__init__.py"
    ).read_text(encoding="utf-8")
    implementation = (
        ROOT / "firmware/components/fake_sesame/fake_sesame.cpp"
    ).read_text(encoding="utf-8")

    assert 'cg.add_define("FAKE_SESAME_VERSION", COMPONENT_VERSION)' in component
    assert 'VERSION[] = "fake-" FAKE_SESAME_VERSION' in implementation
