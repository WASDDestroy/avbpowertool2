"""Configuration management use cases."""

from __future__ import annotations

import logging
from pathlib import Path

from avbpowertool.application.commands import (
    ConfigExportRequest,
    ConfigExportResult,
    ConfigImportRequest,
    ConfigImportResult,
    ConfigShowRequest,
    ConfigShowResult,
    ConfigValidateRequest,
    ConfigValidateResult,
)
from avbpowertool.domain.models import OperationIssue
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.persistence.archive_repository import (
    ArchiveRepository,
)
from avbpowertool.infrastructure.persistence.profile_repository import (
    ProfileRepository,
)

logger = logging.getLogger(__name__)


class ConfigShowUseCase:
    """Show the currently active configuration."""

    def __init__(self, workspace: WorkspacePaths) -> None:
        self._ws = workspace

    def execute(self, request: ConfigShowRequest) -> ConfigShowResult:
        issues: list[OperationIssue] = []
        repo = ProfileRepository(self._ws)

        try:
            profile = repo.load(request.profile_id)
        except Exception as exc:
            issues.append(OperationIssue("config.not_found", f"Failed to load profile: {exc}"))
            return ConfigShowResult(
                config_name=request.profile_id,
                partitions=(),
                issues=tuple(issues),
            )

        partitions = tuple(profile.partitions.values())
        return ConfigShowResult(
            config_name=profile.id,
            partitions=partitions,
            issues=tuple(issues),
        )


class ConfigValidateUseCase:
    """Validate the current config against workspace images."""

    def __init__(self, workspace: WorkspacePaths) -> None:
        self._ws = workspace

    def execute(self, request: ConfigValidateRequest) -> ConfigValidateResult:
        issues: list[OperationIssue] = []
        repo = ProfileRepository(self._ws)

        try:
            profile = repo.load(request.profile_id)
        except Exception as exc:
            issues.append(OperationIssue("config.not_found", f"Failed to load profile: {exc}"))
            return ConfigValidateResult(
                config_name=request.profile_id,
                partitions=(),
                issues=tuple(issues),
            )

        partitions = tuple(profile.partitions.values())
        missing_images: list[str] = []
        missing_keys: list[str] = []

        profile_dir = self._ws.resolve_profile_dir(request.profile_id)

        for name, config in profile.partitions.items():
            # Check image exists
            image_path = profile_dir / config.image
            if not image_path.exists():
                missing_images.append(name)

            # Check key exists
            key_dir = self._ws.resolve_key_dir(request.profile_id)
            manifest_path = key_dir / "manifest.json"
            if manifest_path.exists():
                import json

                try:
                    with open(manifest_path, encoding="utf-8") as f:
                        manifest = json.load(f)
                    entry = manifest.get(config.key_id)
                    if entry is None or not (key_dir / entry.get("private_key", "")).exists():
                        missing_keys.append(config.key_id)
                except (OSError, ValueError):
                    missing_keys.append(config.key_id)
            else:
                missing_keys.append(config.key_id)

        return ConfigValidateResult(
            config_name=profile.id,
            partitions=partitions,
            missing_images=tuple(missing_images),
            missing_keys=tuple(dict.fromkeys(missing_keys)),  # deduplicate, preserve order
            issues=tuple(issues),
        )


class ConfigImportUseCase:
    """Import a config from a ZIP archive."""

    def __init__(self, workspace: WorkspacePaths) -> None:
        self._ws = workspace

    def execute(self, request: ConfigImportRequest) -> ConfigImportResult:
        issues: list[OperationIssue] = []
        archive_path = Path(request.archive_path)

        repo = ArchiveRepository(self._ws.profiles, self._ws.staging)

        # Validate first
        validation_issues = repo.validate_archive(archive_path)
        issues.extend(validation_issues)
        if any(i.error_code == "config.invalid_archive" for i in validation_issues):
            return ConfigImportResult(profile_id="", issues=tuple(issues))

        try:
            profile_id = repo.import_profile(archive_path, new_profile_id=request.new_profile_id)
        except Exception as exc:
            issues.append(OperationIssue("config.import_failed", f"Import failed: {exc}"))
            return ConfigImportResult(profile_id="", issues=tuple(issues))

        return ConfigImportResult(profile_id=profile_id, issues=tuple(issues))


class ConfigExportUseCase:
    """Export a config as a ZIP archive."""

    def __init__(self, workspace: WorkspacePaths) -> None:
        self._ws = workspace

    def execute(self, request: ConfigExportRequest) -> ConfigExportResult:
        issues: list[OperationIssue] = []

        output_path = Path(request.output_path or str(self._ws.root / f"{request.profile_id}.zip"))

        repo = ArchiveRepository(self._ws.profiles, self._ws.staging)

        try:
            repo.export_profile(request.profile_id, output_path)
        except Exception as exc:
            issues.append(OperationIssue("config.export_failed", f"Export failed: {exc}"))
            return ConfigExportResult(output_path=str(output_path), issues=tuple(issues))

        return ConfigExportResult(output_path=str(output_path), issues=tuple(issues))
