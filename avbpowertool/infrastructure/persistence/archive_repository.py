"""Archive repository — ZIP import/export of profiles with manifest."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import zipfile
from pathlib import Path
from typing import Any

from avbpowertool.domain.errors import ConfigError
from avbpowertool.domain.models import OperationIssue

logger = logging.getLogger(__name__)

_ARCHIVE_MANIFEST_FORMAT = 1


class ArchiveRepository:
    """Export and import profiles as ZIP archives with integrity manifest."""

    def __init__(self, profiles_base: Path, staging_base: Path) -> None:
        self._profiles_base = profiles_base
        self._staging_base = staging_base

    def export_profile(
        self,
        profile_id: str,
        output_path: Path,
    ) -> None:
        """Export a profile directory as a ZIP archive with manifest."""
        profile_dir = self._profiles_base / profile_id
        if not profile_dir.exists():
            raise ConfigError(
                f"Profile not found: {profile_id}",
                error_code="config.not_found",
            )

        files_to_pack: list[tuple[str, Path]] = []
        for path in sorted(profile_dir.rglob("*")):
            if path.is_file():
                rel = path.relative_to(profile_dir)
                files_to_pack.append((rel.as_posix(), path))

        # Build manifest
        manifest_entries: list[dict[str, str]] = []
        for rel_str, abs_path in files_to_pack:
            sha = _sha256_file(abs_path)
            manifest_entries.append({"path": rel_str, "sha256": sha})

        archive_manifest = {
            "format_version": _ARCHIVE_MANIFEST_FORMAT,
            "profile_id": profile_id,
            "schema_version": 2,
            "files": manifest_entries,
        }

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Write manifest first
            zf.writestr(
                "manifest.json",
                json.dumps(archive_manifest, indent=2, ensure_ascii=False),
            )
            # Write all profile files
            for rel_str, abs_path in files_to_pack:
                zf.write(abs_path, rel_str)

        logger.info(
            "Exported profile %r to %s (%d files)",
            profile_id,
            output_path,
            len(files_to_pack),
        )

    def import_profile(
        self,
        archive_path: Path,
        new_profile_id: str | None = None,
    ) -> str:
        """Import a profile from a ZIP archive. Returns the profile_id used.

        Raises ConfigError on invalid archive.
        """
        if not archive_path.exists():
            raise ConfigError(
                f"Archive not found: {archive_path}",
                error_code="config.not_found",
            )

        with zipfile.ZipFile(archive_path, "r") as zf:
            # Read and validate manifest
            if "manifest.json" not in zf.namelist():
                raise ConfigError(
                    "Archive missing manifest.json",
                    error_code="config.invalid_archive",
                )
            manifest_data = json.loads(zf.read("manifest.json"))
            profile_id = new_profile_id or manifest_data.get("profile_id", "")
            if not profile_id:
                raise ConfigError(
                    "No profile_id in archive manifest",
                    error_code="config.invalid_archive",
                )

            # Check for path traversal
            for name in zf.namelist():
                if name == "manifest.json":
                    continue
                _validate_archive_path(name)

            # Check for conflicts
            target_dir = self._profiles_base / profile_id
            if target_dir.exists():
                raise ConfigError(
                    f"Profile already exists: {profile_id}",
                    error_code="config.profile_exists",
                )

            # Extract to staging, then move
            staging_dir = self._staging_base / f"import-{profile_id}"
            staging_dir.mkdir(parents=True, exist_ok=True)
            try:
                zf.extractall(staging_dir)
                # Remove manifest.json from extracted files
                manifest_file = staging_dir / "manifest.json"
                manifest_file.unlink(missing_ok=True)
                # Move to target
                shutil.move(str(staging_dir), str(target_dir))
            except Exception:
                shutil.rmtree(staging_dir, ignore_errors=True)
                raise

        logger.info("Imported profile %r from %s", profile_id, archive_path)
        return profile_id

    def validate_archive(self, archive_path: Path) -> list[OperationIssue]:
        """Validate a ZIP archive without importing. Returns issues found."""
        issues: list[OperationIssue] = []

        if not archive_path.exists():
            issues.append(OperationIssue("config.not_found", f"Archive not found: {archive_path}"))
            return issues

        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                if "manifest.json" not in zf.namelist():
                    issues.append(
                        OperationIssue(
                            "config.invalid_archive",
                            "Archive missing manifest.json",
                        )
                    )
                    return issues

                manifest_data = json.loads(zf.read("manifest.json"))
                if not isinstance(manifest_data, dict):
                    issues.append(
                        OperationIssue(
                            "config.invalid_archive",
                            "manifest.json is not a dict",
                        )
                    )
                    return issues

                # Check for path traversal
                for name in zf.namelist():
                    if name == "manifest.json":
                        continue
                    try:
                        _validate_archive_path(name)
                    except ConfigError as exc:
                        issues.append(OperationIssue(exc.error_code, str(exc)))

                # Verify file checksums if manifest has entries
                raw_entries: list[Any] = manifest_data.get("files", [])
                expected_files: dict[str, str | None] = {
                    e["path"]: e.get("sha256") for e in raw_entries
                }
                for file_path, expected_sha in expected_files.items():
                    if file_path not in zf.namelist():
                        issues.append(
                            OperationIssue(
                                "config.invalid_archive",
                                f"File in manifest missing from archive: {file_path}",
                            )
                        )
                    elif expected_sha:
                        actual_sha = hashlib.sha256(zf.read(file_path)).hexdigest()
                        if actual_sha != expected_sha:
                            issues.append(
                                OperationIssue(
                                    "config.invalid_archive",
                                    f"Checksum mismatch for {file_path}",
                                )
                            )

                # Check profile.json exists
                if "profile.json" not in zf.namelist():
                    issues.append(
                        OperationIssue(
                            "config.invalid_archive",
                            "Archive missing profile.json",
                        )
                    )

        except zipfile.BadZipFile:
            issues.append(OperationIssue("config.invalid_archive", "Invalid ZIP file"))
        except (json.JSONDecodeError, KeyError) as exc:
            issues.append(
                OperationIssue("config.invalid_archive", f"Invalid archive format: {exc}")
            )

        return issues


def _validate_archive_path(name: str) -> None:
    """Validate an archive member path. Raises ConfigError on traversal."""
    parts = Path(name).parts
    if any(part == ".." for part in parts):
        raise ConfigError(
            f"Archive contains path traversal: {name!r}",
            error_code="config.invalid_archive",
        )
    if Path(name).is_absolute():
        raise ConfigError(
            f"Archive contains absolute path: {name!r}",
            error_code="config.invalid_archive",
        )


def _sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
