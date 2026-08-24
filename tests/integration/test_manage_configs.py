"""Integration tests for config management use cases."""

from __future__ import annotations

import json
from pathlib import Path

from avbpowertool.application.commands import (
    ConfigExportRequest,
    ConfigImportRequest,
    ConfigShowRequest,
    ConfigValidateRequest,
)
from avbpowertool.application.services.manage_configs import (
    ConfigExportUseCase,
    ConfigImportUseCase,
    ConfigShowUseCase,
    ConfigValidateUseCase,
)
from avbpowertool.domain.models import AvbProfile
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.persistence.profile_codec import encode_profile
from avbpowertool.infrastructure.persistence.profile_repository import ProfileRepository


def _setup_profile(tmp_path: Path) -> WorkspacePaths:
    ws = WorkspacePaths.discover(tmp_path)
    ws.ensure_dirs()
    profile_dir = ws.resolve_profile_dir("test")
    profile_dir.mkdir(parents=True, exist_ok=True)
    key_dir = profile_dir / "keys"
    key_dir.mkdir()
    (profile_dir / "profile.json").write_text(
        json.dumps(
            encode_profile(AvbProfile(id="test", name="Test Profile"))
        ),
        encoding="utf-8",
    )
    return ws


class TestConfigShowUseCase:
    def test_show_existing_profile(self, tmp_path: Path) -> None:
        ws = _setup_profile(tmp_path)
        uc = ConfigShowUseCase(ws)
        result = uc.execute(ConfigShowRequest(profile_id="test"))
        assert result.config_name == "test"
        assert len(result.issues) == 0

    def test_show_nonexistent_profile(self, tmp_path: Path) -> None:
        ws = _setup_profile(tmp_path)
        uc = ConfigShowUseCase(ws)
        result = uc.execute(ConfigShowRequest(profile_id="nonexistent"))
        assert any(i.error_code == "config.not_found" for i in result.issues)


class TestConfigValidateUseCase:
    def test_validate_missing_images(self, tmp_path: Path) -> None:
        ws = _setup_profile(tmp_path)
        uc = ConfigValidateUseCase(ws)
        result = uc.execute(ConfigValidateRequest(profile_id="test"))
        # No images exist, no partitions defined, so no missing images
        assert result.config_name == "test"


class TestConfigImportExportUseCase:
    def test_export_then_import_round_trip(self, tmp_path: Path) -> None:
        ws = _setup_profile(tmp_path)
        export_uc = ConfigExportUseCase(ws)
        archive_path = tmp_path / "export.zip"
        export_result = export_uc.execute(
            ConfigExportRequest(profile_id="test", output_path=str(archive_path))
        )
        assert archive_path.exists()
        assert len(export_result.issues) == 0

        # Delete original
        repo = ProfileRepository(ws)
        repo.delete("test")
        assert "test" not in repo.list_profiles()

        # Import
        import_uc = ConfigImportUseCase(ws)
        import_result = import_uc.execute(
            ConfigImportRequest(archive_path=str(archive_path))
        )
        assert import_result.profile_id == "test"
        assert len(import_result.issues) == 0
        assert "test" in repo.list_profiles()

    def test_import_with_new_id(self, tmp_path: Path) -> None:
        ws = _setup_profile(tmp_path)
        export_uc = ConfigExportUseCase(ws)
        archive_path = tmp_path / "export.zip"
        export_uc.execute(
            ConfigExportRequest(profile_id="test", output_path=str(archive_path))
        )

        import_uc = ConfigImportUseCase(ws)
        result = import_uc.execute(
            ConfigImportRequest(
                archive_path=str(archive_path), new_profile_id="renamed"
            )
        )
        assert result.profile_id == "renamed"

    def test_import_conflict(self, tmp_path: Path) -> None:
        ws = _setup_profile(tmp_path)
        export_uc = ConfigExportUseCase(ws)
        archive_path = tmp_path / "export.zip"
        export_uc.execute(
            ConfigExportRequest(profile_id="test", output_path=str(archive_path))
        )

        import_uc = ConfigImportUseCase(ws)
        result = import_uc.execute(
            ConfigImportRequest(archive_path=str(archive_path))
        )
        # Conflict is caught as import_failed wrapping the profile_exists error
        assert any(
            "import_failed" in i.error_code or "already exists" in i.message
            for i in result.issues
        )

    def test_export_nonexistent(self, tmp_path: Path) -> None:
        ws = _setup_profile(tmp_path)
        uc = ConfigExportUseCase(ws)
        result = uc.execute(
            ConfigExportRequest(profile_id="nonexistent", output_path=str(tmp_path / "out.zip"))
        )
        assert any(i.error_code == "config.export_failed" for i in result.issues)
