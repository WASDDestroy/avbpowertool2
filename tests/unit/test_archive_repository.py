"""Tests for ArchiveRepository — export/import with manifest validation."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from avbpowertool.domain.errors import ConfigError
from avbpowertool.infrastructure.persistence.archive_repository import ArchiveRepository


def _setup_profile(profiles: Path, profile_id: str) -> None:
    """Create a minimal profile directory for testing."""
    profile_dir = profiles / profile_id
    profile_dir.mkdir(parents=True, exist_ok=True)
    key_dir = profile_dir / "keys"
    key_dir.mkdir(exist_ok=True)

    profile = {
        "schema_version": 2,
        "profile": {"id": profile_id, "name": f"Test {profile_id}"},
        "key_store_path": "keys",
        "partitions": {},
    }
    (profile_dir / "profile.json").write_text(
        json.dumps(profile, indent=2), encoding="utf-8"
    )
    (key_dir / "test.pem").write_text("fake key", encoding="utf-8")
    manifest = {"testkey": {"private_key": "test.pem"}}
    (key_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )


class TestArchiveRepositoryExport:
    def test_export_creates_zip(self, tmp_path: Path) -> None:
        profiles = tmp_path / "profiles"
        profiles.mkdir()
        staging = tmp_path / "staging"
        staging.mkdir()
        _setup_profile(profiles, "test")

        repo = ArchiveRepository(profiles, staging)
        output = tmp_path / "export.zip"
        repo.export_profile("test", output)

        assert output.exists()
        with zipfile.ZipFile(output) as zf:
            names = zf.namelist()
            assert "manifest.json" in names
            assert "profile.json" in names
            assert "keys/test.pem" in names
            assert "keys/manifest.json" in names

    def test_export_manifest_has_checksums(self, tmp_path: Path) -> None:
        profiles = tmp_path / "profiles"
        profiles.mkdir()
        staging = tmp_path / "staging"
        staging.mkdir()
        _setup_profile(profiles, "test")

        repo = ArchiveRepository(profiles, staging)
        output = tmp_path / "export.zip"
        repo.export_profile("test", output)

        with zipfile.ZipFile(output) as zf:
            manifest = json.loads(zf.read("manifest.json"))
            assert manifest["format_version"] == 1
            assert manifest["profile_id"] == "test"
            assert manifest["schema_version"] == 3
            file_paths = {e["path"] for e in manifest["files"]}
            assert "profile.json" in file_paths
            assert all("sha256" in e for e in manifest["files"])

    def test_export_nonexistent_raises(self, tmp_path: Path) -> None:
        profiles = tmp_path / "profiles"
        profiles.mkdir()
        staging = tmp_path / "staging"
        staging.mkdir()

        repo = ArchiveRepository(profiles, staging)
        with pytest.raises(ConfigError, match="not found"):
            repo.export_profile("nonexistent", tmp_path / "out.zip")


class TestArchiveRepositoryImport:
    def test_import_round_trip(self, tmp_path: Path) -> None:
        profiles = tmp_path / "profiles"
        profiles.mkdir()
        staging = tmp_path / "staging"
        staging.mkdir()
        _setup_profile(profiles, "original")

        repo = ArchiveRepository(profiles, staging)
        archive = tmp_path / "export.zip"
        repo.export_profile("original", archive)

        # Delete original and re-import
        import shutil
        shutil.rmtree(profiles / "original")

        profile_id = repo.import_profile(archive)
        assert profile_id == "original"
        assert (profiles / "original" / "profile.json").exists()

    def test_import_with_new_id(self, tmp_path: Path) -> None:
        profiles = tmp_path / "profiles"
        profiles.mkdir()
        staging = tmp_path / "staging"
        staging.mkdir()
        _setup_profile(profiles, "original")

        repo = ArchiveRepository(profiles, staging)
        archive = tmp_path / "export.zip"
        repo.export_profile("original", archive)

        profile_id = repo.import_profile(archive, new_profile_id="renamed")
        assert profile_id == "renamed"
        assert (profiles / "renamed" / "profile.json").exists()

    def test_import_conflict_raises(self, tmp_path: Path) -> None:
        profiles = tmp_path / "profiles"
        profiles.mkdir()
        staging = tmp_path / "staging"
        staging.mkdir()
        _setup_profile(profiles, "test")

        repo = ArchiveRepository(profiles, staging)
        archive = tmp_path / "export.zip"
        repo.export_profile("test", archive)

        with pytest.raises(ConfigError, match="already exists"):
            repo.import_profile(archive)

    def test_import_nonexistent_raises(self, tmp_path: Path) -> None:
        profiles = tmp_path / "profiles"
        profiles.mkdir()
        staging = tmp_path / "staging"
        staging.mkdir()

        repo = ArchiveRepository(profiles, staging)
        with pytest.raises(ConfigError, match="not found"):
            repo.import_profile(tmp_path / "missing.zip")

    def test_import_no_manifest_raises(self, tmp_path: Path) -> None:
        profiles = tmp_path / "profiles"
        profiles.mkdir()
        staging = tmp_path / "staging"
        staging.mkdir()

        # Create a zip without manifest.json
        bad_zip = tmp_path / "bad.zip"
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.writestr("profile.json", "{}")

        repo = ArchiveRepository(profiles, staging)
        with pytest.raises(ConfigError, match="manifest"):
            repo.import_profile(bad_zip)


class TestArchiveRepositoryValidate:
    def test_validate_valid(self, tmp_path: Path) -> None:
        profiles = tmp_path / "profiles"
        profiles.mkdir()
        staging = tmp_path / "staging"
        staging.mkdir()
        _setup_profile(profiles, "test")

        repo = ArchiveRepository(profiles, staging)
        archive = tmp_path / "export.zip"
        repo.export_profile("test", archive)

        issues = repo.validate_archive(archive)
        assert len(issues) == 0

    def test_validate_missing_manifest(self, tmp_path: Path) -> None:
        profiles = tmp_path / "profiles"
        profiles.mkdir()
        staging = tmp_path / "staging"
        staging.mkdir()

        bad_zip = tmp_path / "bad.zip"
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.writestr("profile.json", "{}")

        repo = ArchiveRepository(profiles, staging)
        issues = repo.validate_archive(bad_zip)
        assert any("manifest" in i.message.lower() for i in issues)

    def test_validate_path_traversal(self, tmp_path: Path) -> None:
        profiles = tmp_path / "profiles"
        profiles.mkdir()
        staging = tmp_path / "staging"
        staging.mkdir()

        bad_zip = tmp_path / "traversal.zip"
        with zipfile.ZipFile(bad_zip, "w") as zf:
            manifest = {
                "format_version": 1,
                "profile_id": "evil",
                "schema_version": 2,
                "files": [{"path": "../../etc/passwd", "sha256": "x"}],
            }
            zf.writestr("manifest.json", json.dumps(manifest))
            zf.writestr("../../etc/passwd", "evil")

        repo = ArchiveRepository(profiles, staging)
        issues = repo.validate_archive(bad_zip)
        assert any("traversal" in i.message.lower() for i in issues)

    def test_validate_nonexistent_archive(self, tmp_path: Path) -> None:
        profiles = tmp_path / "profiles"
        profiles.mkdir()
        staging = tmp_path / "staging"
        staging.mkdir()

        repo = ArchiveRepository(profiles, staging)
        issues = repo.validate_archive(tmp_path / "missing.zip")
        assert len(issues) == 1
        assert "not found" in issues[0].message.lower()
