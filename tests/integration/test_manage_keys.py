"""Integration tests for key management use cases."""

from __future__ import annotations

from pathlib import Path

from avbpowertool.application.commands import KeyDiscoveryRequest
from avbpowertool.application.services.manage_keys import KeyDiscoveryUseCase
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths


def _setup_key_dir(tmp_path: Path) -> WorkspacePaths:
    ws = WorkspacePaths(
        root=tmp_path,
        profiles=tmp_path / "profiles",
        logs=tmp_path / "Logs",
        staging=tmp_path / ".avbpowertool-staging",
        avbtool_script=tmp_path / "avbtool.py",
    )
    ws.ensure_dirs()
    key_dir = ws.resolve_key_dir("current")
    key_dir.mkdir(parents=True, exist_ok=True)
    return ws


class TestKeyDiscoveryUseCase:
    def test_discover_pem_files(self, tmp_path: Path) -> None:
        ws = _setup_key_dir(tmp_path)
        key_dir = ws.resolve_key_dir("current")
        (key_dir / "testkey.pem").write_text("fake key 1")
        (key_dir / "release.pem").write_text("fake key 2")

        uc = KeyDiscoveryUseCase(ws)
        result = uc.execute(KeyDiscoveryRequest(profile_id="current"))

        assert result.discovered_count == 2
        assert len(result.manifest_entries) == 2
        # Manifest should be written
        assert (key_dir / "manifest.json").exists()

    def test_discover_empty_directory(self, tmp_path: Path) -> None:
        ws = _setup_key_dir(tmp_path)
        uc = KeyDiscoveryUseCase(ws)
        result = uc.execute(KeyDiscoveryRequest(profile_id="current"))

        assert result.discovered_count == 0
        assert len(result.manifest_entries) == 0

    def test_discover_nonexistent_directory(self, tmp_path: Path) -> None:
        ws = WorkspacePaths(
            root=tmp_path,
            profiles=tmp_path / "profiles",
            logs=tmp_path / "Logs",
            staging=tmp_path / ".avbpowertool-staging",
            avbtool_script=tmp_path / "avbtool.py",
        )
        ws.ensure_dirs()
        uc = KeyDiscoveryUseCase(ws)
        result = uc.execute(KeyDiscoveryRequest(profile_id="nonexistent"))

        assert any(i.error_code == "keys.directory_not_found" for i in result.issues)
