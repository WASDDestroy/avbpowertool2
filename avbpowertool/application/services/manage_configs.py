"""Configuration management use cases."""

from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from avbpowertool.application.commands import (
    ConfigCreateRequest,
    ConfigCreateResult,
    ConfigEditRequest,
    ConfigEditResult,
    ConfigExportRequest,
    ConfigExportResult,
    ConfigImportRequest,
    ConfigImportResult,
    ConfigMigrateRequest,
    ConfigMigrateResult,
    ConfigShowRequest,
    ConfigShowResult,
    ConfigValidateRequest,
    ConfigValidateResult,
    LegacyImportRequest,
    LegacyImportResult,
)
from avbpowertool.domain.errors import ConfigError
from avbpowertool.domain.models import AvbProfile, OperationIssue
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.persistence.archive_repository import (
    ArchiveRepository,
)
from avbpowertool.infrastructure.persistence.key_repository import KeyRepository
from avbpowertool.infrastructure.persistence.profile_codec import (
    decode_profile_with_issues,
    encode_profile,
)
from avbpowertool.infrastructure.persistence.profile_repository import (
    ProfileRepository,
)
from avbpowertool.infrastructure.persistence.v1_profile_codec import (
    build_key_manifest,
    decode_v1_image_info,
    detect_v1_archive,
    extract_v1_archive,
    find_config_dir,
    find_keys_dir,
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

        for name, config in profile.partitions.items():
            # Check image exists in workspace Images/ directory
            image_path = self._ws.images / config.image
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


class LegacyConfigImportUseCase:
    """Import a legacy (v1) config archive, converting it to a v2 profile."""

    def __init__(self, workspace: WorkspacePaths) -> None:
        self._ws = workspace

    def execute(self, request: LegacyImportRequest) -> LegacyImportResult:
        issues: list[OperationIssue] = []
        archive_path = Path(request.archive_path)

        archive_type = detect_v1_archive(archive_path)
        if archive_type == "batch":
            return LegacyImportResult(
                profile_id="",
                issues=(
                    OperationIssue(
                        "import.legacy.batch_not_supported",
                        "Batch v1 archives are not supported",
                    ),
                ),
            )
        if archive_type != "single":
            return LegacyImportResult(
                profile_id="",
                issues=(
                    OperationIssue(
                        "config.invalid_archive",
                        f"Not a v1 config archive: {archive_path}",
                    ),
                ),
            )

        staging_dir = self._ws.staging / "legacy-import"
        shutil.rmtree(staging_dir, ignore_errors=True)
        try:
            staging_root = extract_v1_archive(archive_path, staging_dir)
            config_dir = find_config_dir(staging_root)
            keys_dir = find_keys_dir(staging_root)

            with open(config_dir / "imageInfo.json", encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raise ConfigError(
                    "imageInfo.json is not a dict",
                    error_code="config.parse_error",
                )
            raw_dict = cast(dict[str, Any], raw)

            profile_id = _sanitize_profile_id(
                request.new_profile_id or _derive_v1_config_name(config_dir, archive_path)
            )
            profile_name = _read_v1_config_name(config_dir) or profile_id

            profile, codec_issues = decode_v1_image_info(raw_dict, profile_id)
            issues.extend(codec_issues)
            profile = AvbProfile(
                id=profile_id,
                name=profile_name,
                schema_version=3,
                key_store_path="keys",
                partitions=profile.partitions,
            )

            repo = ProfileRepository(self._ws)
            if profile_id in repo.list_profiles():
                issues.append(
                    OperationIssue(
                        "config.profile_exists",
                        f"Profile already exists: {profile_id}",
                    )
                )
                return LegacyImportResult(profile_id=profile_id, issues=tuple(issues))

            repo.save(profile)

            key_count = 0
            if keys_dir is not None:
                manifest, key_issues = build_key_manifest(keys_dir, keys_dir / "keyCache.cache")
                issues.extend(key_issues)
                key_dir = self._ws.resolve_key_dir(profile_id)
                key_dir.mkdir(parents=True, exist_ok=True)
                for f in sorted(keys_dir.iterdir()):
                    if f.is_file() and (f.suffix == ".pem" or f.name.endswith("_pub.bin")):
                        shutil.copy2(f, key_dir / f.name)
                key_count = len(manifest)
                KeyRepository(key_dir).save_manifest(manifest)

            if request.activate:
                repo.activate(profile_id)

            logger.info(
                "Imported legacy config %r (%d partitions, %d keys)",
                profile_id,
                len(profile.partitions),
                key_count,
            )
            return LegacyImportResult(
                profile_id=profile_id,
                partition_count=len(profile.partitions),
                key_count=key_count,
                issues=tuple(issues),
            )
        except Exception as exc:
            issues.append(OperationIssue("import.legacy.failed", f"Legacy import failed: {exc}"))
            return LegacyImportResult(profile_id="", issues=tuple(issues))
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)


def _sanitize_profile_id(value: str) -> str:
    """Make a filesystem-safe profile id from an arbitrary config name."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", value).strip("._")
    return cleaned or "legacy_config"


def _read_v1_config_name(config_dir: Path) -> str | None:
    """Read the config name from v1 ``config_info.cfg`` (``name="..."``)."""
    cfg = config_dir / "config_info.cfg"
    if not cfg.is_file():
        return None
    try:
        for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() != "name":
                continue
            value = value.strip()
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            if value:
                return value
    except OSError:
        return None
    return None


def _derive_v1_config_name(config_dir: Path, archive_path: Path) -> str:
    """Derive the v1 config name: config_info.cfg > config folder > zip stem."""
    name = _read_v1_config_name(config_dir)
    if name:
        return name
    if config_dir.name not in ("Configs", "configs"):
        return config_dir.name
    return archive_path.stem


class ConfigCreateUseCase:
    """Create a new profile with partitions and optional key store."""

    def __init__(self, workspace: WorkspacePaths) -> None:
        self._ws = workspace

    def execute(self, request: ConfigCreateRequest) -> ConfigCreateResult:
        issues: list[OperationIssue] = []
        repo = ProfileRepository(self._ws)

        # Check for conflicts
        existing = repo.list_profiles()
        if request.profile_id in existing:
            issues.append(
                OperationIssue(
                    "config.profile_exists",
                    f"Profile already exists: {request.profile_id}",
                )
            )
            return ConfigCreateResult(profile_id=request.profile_id, issues=tuple(issues))

        # Build profile
        partitions = {p.partition_name: p for p in request.partitions}
        profile = AvbProfile(
            id=request.profile_id,
            name=request.profile_name,
            key_store_path="keys",
            partitions=partitions,
        )

        # Validate
        from avbpowertool.domain.validation import validate_profile

        validation_issues = validate_profile(profile)
        issues.extend(validation_issues)
        if any(
            i.error_code
            in {
                "config.invalid_schema_version",
                "config.no_partitions",
                "config.missing_profile_id",
            }
            for i in validation_issues
        ):
            return ConfigCreateResult(profile_id=request.profile_id, issues=tuple(issues))

        # Create profile directory and key store
        profile_dir = self._ws.resolve_profile_dir(request.profile_id)
        key_dir = self._ws.resolve_key_dir(request.profile_id)

        try:
            profile_dir.mkdir(parents=True, exist_ok=True)
            key_dir.mkdir(parents=True, exist_ok=True)

            # Write profile.json
            import json

            data = encode_profile(profile)
            (profile_dir / "profile.json").write_bytes(
                json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
            )

            # Write an empty manifest only when none exists yet — the
            # creation wizard may have already discovered keys into the
            # key store before this use case ran.
            if not (key_dir / "manifest.json").exists():
                (key_dir / "manifest.json").write_bytes(b"{}")

            # Activate if requested
            if request.activate:
                repo.activate(request.profile_id)

            logger.info("Created profile %r", request.profile_id)
        except Exception as exc:
            issues.append(
                OperationIssue("config.create_failed", f"Failed to create profile: {exc}")
            )

        return ConfigCreateResult(profile_id=request.profile_id, issues=tuple(issues))


# ---------------------------------------------------------------------------
# Config migration (v2 -> v3)
# ---------------------------------------------------------------------------


class ConfigMigrateUseCase:
    """Upgrade a profile on disk to the current schema version.

    v2 profiles are migrated in memory (``decode_profile_with_issues``)
    and re-saved as v3.  v3 profiles are left untouched.
    """

    def __init__(self, workspace: WorkspacePaths) -> None:
        self._ws = workspace

    def execute(self, request: ConfigMigrateRequest) -> ConfigMigrateResult:
        issues: list[OperationIssue] = []
        profile_path = self._ws.resolve_profile_dir(request.profile_id) / "profile.json"
        if not profile_path.exists():
            issues.append(
                OperationIssue("config.not_found", f"Profile not found: {request.profile_id}")
            )
            return ConfigMigrateResult(profile_id=request.profile_id, issues=tuple(issues))

        try:
            with open(profile_path, encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            issues.append(
                OperationIssue(
                    "config.parse_error",
                    f"Failed to read profile {request.profile_id!r}: {exc}",
                )
            )
            return ConfigMigrateResult(profile_id=request.profile_id, issues=tuple(issues))

        schema_version = data.get("schema_version", 0)
        if schema_version == 3:
            return ConfigMigrateResult(profile_id=request.profile_id, migrated=False)

        if schema_version != 2:
            issues.append(
                OperationIssue(
                    "config.invalid_schema_version",
                    f"Unsupported schema_version {schema_version}; only v2 and v3 can be handled",
                )
            )
            return ConfigMigrateResult(profile_id=request.profile_id, issues=tuple(issues))

        try:
            profile, migration_issues = decode_profile_with_issues(data)
            issues.extend(migration_issues)
            # Rewrite the migrated dict back to the same file (in-place),
            # regardless of the profile id embedded in the JSON.
            v3_data = encode_profile(profile)
            profile_path.write_text(
                json.dumps(v3_data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            logger.info("Migrated profile %r to schema v3", request.profile_id)
        except Exception as exc:
            issues.append(OperationIssue("config.migrate_failed", f"Migration failed: {exc}"))
            return ConfigMigrateResult(profile_id=request.profile_id, issues=tuple(issues))

        return ConfigMigrateResult(
            profile_id=request.profile_id,
            migrated=True,
            issues=tuple(issues),
        )


# ---------------------------------------------------------------------------
# Config field editing
# ---------------------------------------------------------------------------

#: PartitionConfig fields editable via ``config edit --set``.
_INT_FIELDS = frozenset(
    {
        "partition_size",
        "rollback_index",
        "rollback_index_location",
        "flags",
        "block_size",
        "fec_num_roots",
        "padding_size",
    }
)
_BOOL_FIELDS = frozenset(
    {
        "dynamic_partition_size",
        "do_not_generate_fec",
        "calc_max_image_size",
        "do_not_append_vbmeta_image",
        "no_hashtree",
        "check_at_most_once",
        "setup_as_rootfs_from_kernel",
        "use_persistent_digest",
        "do_not_use_ab",
        "set_hashtree_disabled_flag",
        "set_verification_disabled_flag",
        "print_required_libavb_version",
    }
)
_STR_FIELDS = frozenset(
    {
        "salt",
        "hash_algorithm",
        "output_vbmeta_image",
        "setup_rootfs_from_kernel",
        "signing_helper",
        "signing_helper_with_files",
        "public_key_metadata",
        "append_to_release_string",
    }
)
_TUPLE_FIELDS = frozenset(
    {
        "kernel_cmdlines",
        "chain_partitions",
        "chain_partitions_do_not_use_ab",
        "included_partitions",
        "include_descriptors_from_image",
    }
)


class ConfigEditUseCase:
    """Update individual fields of one partition config.

    ``updates`` values are strings; they are parsed according to the
    field's type.  Unknown or unsupported fields produce issues.
    """

    def __init__(self, workspace: WorkspacePaths) -> None:
        self._ws = workspace

    def execute(self, request: ConfigEditRequest) -> ConfigEditResult:
        issues: list[OperationIssue] = []
        repo = ProfileRepository(self._ws)

        try:
            profile = repo.load(request.profile_id)
        except Exception as exc:
            issues.append(OperationIssue("config.not_found", f"Failed to load profile: {exc}"))
            return ConfigEditResult(
                profile_id=request.profile_id,
                partition_name=request.partition_name,
                issues=tuple(issues),
            )

        config = profile.partitions.get(request.partition_name)
        if config is None:
            issues.append(
                OperationIssue(
                    "config.partition_missing",
                    f"Partition not in profile: {request.partition_name}",
                )
            )
            return ConfigEditResult(
                profile_id=request.profile_id,
                partition_name=request.partition_name,
                issues=tuple(issues),
            )

        parsed: dict[str, Any] = {}
        for field_name, raw_value in request.updates.items():
            parsed_value = self._parse_field(field_name, raw_value)
            if parsed_value is _UNSUPPORTED:
                issues.append(
                    OperationIssue(
                        "config.invalid_field",
                        f"Field {field_name!r} is not editable via config edit",
                    )
                )
            else:
                parsed[field_name] = parsed_value

        if issues:
            return ConfigEditResult(
                profile_id=request.profile_id,
                partition_name=request.partition_name,
                issues=tuple(issues),
            )

        new_config = replace(config, **parsed)
        new_partitions = dict(profile.partitions)
        new_partitions[request.partition_name] = new_config
        new_profile = replace(profile, partitions=new_partitions)

        try:
            repo.save(new_profile)
        except Exception as exc:
            issues.append(OperationIssue("config.save_failed", f"Failed to save profile: {exc}"))

        return ConfigEditResult(
            profile_id=request.profile_id,
            partition_name=request.partition_name,
            issues=tuple(issues),
        )

    @staticmethod
    def _parse_field(field_name: str, raw_value: str) -> Any:
        """Parse a raw string value for a known field."""
        if field_name in _INT_FIELDS:
            try:
                return int(raw_value)
            except ValueError:
                return _UNSUPPORTED
        if field_name in _BOOL_FIELDS:
            return raw_value.strip().lower() in {"1", "true", "yes", "on"}
        if field_name in _STR_FIELDS:
            return raw_value
        if field_name in _TUPLE_FIELDS:
            items = [item.strip() for item in raw_value.split(",") if item.strip()]
            return tuple(items)
        return _UNSUPPORTED


#: sentinel returned when a field cannot be parsed / is not editable
_UNSUPPORTED = object()
