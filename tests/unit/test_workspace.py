"""Tests for WorkspacePaths."""

from __future__ import annotations

from pathlib import Path

import pytest

from avbpowertool.domain.errors import WorkspaceError
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths


class TestWorkspacePathsDiscover:
    def test_discover_from_root(self, tmp_path: Path) -> None:
        ws = WorkspacePaths.discover(tmp_path)
        assert ws.root == tmp_path.resolve()
        assert ws.images == tmp_path / "Images"
        assert ws.profiles == tmp_path / "profiles"
        assert ws.logs == tmp_path / "Logs"
        assert ws.staging == tmp_path / ".avbpowertool-staging"
        assert ws.avbtool_script == tmp_path / "avbtool.py"

    def test_discover_nonexistent_raises(self, tmp_path: Path) -> None:
        with pytest.raises(WorkspaceError, match="does not exist"):
            WorkspacePaths.discover(tmp_path / "nonexistent")

    def test_frozen(self, tmp_path: Path) -> None:
        ws = WorkspacePaths.discover(tmp_path)
        with pytest.raises(AttributeError):
            ws.root = Path("/other")  # type: ignore[misc]


class TestWorkspacePathsHelpers:
    def test_resolve_profile_dir(self, tmp_path: Path) -> None:
        ws = WorkspacePaths.discover(tmp_path)
        assert ws.resolve_profile_dir("myprofile") == tmp_path / "profiles" / "myprofile"

    def test_resolve_key_dir(self, tmp_path: Path) -> None:
        ws = WorkspacePaths.discover(tmp_path)
        assert ws.resolve_key_dir("myprofile") == tmp_path / "profiles" / "myprofile" / "keys"

    def test_resolve_image_path(self, tmp_path: Path) -> None:
        ws = WorkspacePaths.discover(tmp_path)
        ws.images.mkdir(parents=True)
        (ws.images / "boot.img").write_bytes(b"fake")

        result = ws.resolve_image_path("boot.img")
        assert result.name == "boot.img"
        assert result.exists()

    def test_resolve_image_path_auto_ext(self, tmp_path: Path) -> None:
        ws = WorkspacePaths.discover(tmp_path)
        ws.images.mkdir(parents=True)
        (ws.images / "boot.img").write_bytes(b"fake")

        result = ws.resolve_image_path("boot")
        assert result.name == "boot.img"

    def test_resolve_image_path_escape_raises(self, tmp_path: Path) -> None:
        ws = WorkspacePaths.discover(tmp_path)
        with pytest.raises(WorkspaceError, match="escapes"):
            ws.resolve_image_path("../../etc/passwd")


class TestWorkspacePathsEnsureDirs:
    def test_creates_directories(self, tmp_path: Path) -> None:
        ws = WorkspacePaths.discover(tmp_path)
        ws.ensure_dirs()
        assert ws.images.exists()
        assert ws.profiles.exists()
        assert ws.logs.exists()
        assert ws.staging.exists()
