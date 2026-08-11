"""Tests for repository release version synchronization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.version import (
    README_UNRELEASED,
    VersionError,
    check_versions,
    parse_version,
    require_newer,
    sync_version,
)


def version_tree(root: Path, *, readme_line: str = README_UNRELEASED) -> Path:
    """Create a minimal repository version fixture."""
    component = root / "custom_components/candy_house_ble"
    component.mkdir(parents=True)
    (component / "manifest.json").write_text(
        json.dumps({"domain": "candy_house_ble", "version": "0.0.0"}),
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        f"# Integration\n\n## Status\n\n{readme_line}\n", encoding="utf-8"
    )
    return root


def test_sync_bootstraps_first_release(tmp_path: Path) -> None:
    root = version_tree(tmp_path)

    sync_version(root, "0.1.0")

    assert check_versions(root) == "0.1.0"
    assert (root / "VERSION").read_text(encoding="utf-8") == "0.1.0\n"
    assert "Current version: **0.1.0**." in (root / "README.md").read_text(
        encoding="utf-8"
    )


def test_sync_updates_existing_release(tmp_path: Path) -> None:
    root = version_tree(tmp_path, readme_line="Current version: **0.1.0**.")
    (root / "VERSION").write_text("0.1.0\n", encoding="utf-8")

    sync_version(root, "0.2.0")

    assert check_versions(root) == "0.2.0"


def test_check_rejects_mismatched_versions(tmp_path: Path) -> None:
    root = version_tree(tmp_path, readme_line="Current version: **0.1.0**.")
    (root / "VERSION").write_text("0.2.0\n", encoding="utf-8")

    with pytest.raises(VersionError, match="Version mismatch"):
        check_versions(root)


def test_sync_rejects_ambiguous_readme(tmp_path: Path) -> None:
    root = version_tree(
        tmp_path,
        readme_line=(
            "Current version: **0.1.0**.\n\nCurrent version: **0.1.0**."
        ),
    )

    with pytest.raises(VersionError, match="exactly one"):
        sync_version(root, "0.2.0")

    assert not (root / "VERSION").exists()


@pytest.mark.parametrize(
    "version", ["v0.1.0", "01.0.0", "0.1", "0.1.0-beta.1", "0.1.0\n1.0.0"]
)
def test_parse_version_rejects_non_stable_semver(version: str) -> None:
    with pytest.raises(VersionError, match="Invalid stable version"):
        parse_version(version)


def test_require_newer_uses_numeric_semver_order() -> None:
    require_newer("0.10.0", "0.9.9")

    with pytest.raises(VersionError, match="must be newer"):
        require_newer("0.9.9", "0.10.0")
