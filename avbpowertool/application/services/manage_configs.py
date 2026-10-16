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
from avbpowertool.domain.models import (
    AvbProfile,
    OperationIssue,
    PartitionConfig,
    SigningAlgorithm,
)
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
            profile_id = repo.resolve_profile_id(request.profile_id)
        except ConfigError as exc:
            issues.append(OperationIssue(exc.error_code, str(exc)))
            return ConfigShowResult(
                config_name=request.profile_id,
                partitions=(),
                issues=tuple(issues),
            )

        try:
            profile = repo.load(profile_id)
        except Exception as exc:
            issues.append(OperationIssue("config.not_found", f"Failed to load profile: {exc}"))
            return ConfigShowResult(
                config_name=profile_id,
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
            profile_id = repo.resolve_profile_id(request.profile_id)
        except ConfigError as exc:
            issues.append(OperationIssue(exc.error_code, str(exc)))
            return ConfigValidateResult(
                config_name=request.profile_id,
                partitions=(),
                issues=tuple(issues),
            )

        try:
            profile = repo.load(profile_id)
        except Exception as exc:
            issues.append(OperationIssue("config.not_found", f"Failed to load profile: {exc}"))
            return ConfigValidateResult(
                config_name=profile_id,
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

            # An unsigned (NONE) partition needs no key at all, so its
            # key_id is irrelevant -- even a stale one is not a problem.
            # This mirrors domain.validate_partition, which only requires
            # a key_id when the algorithm is not NONE.  Signed partitions
            # keep the full check below.
            if config.algorithm == SigningAlgorithm.NONE:
                continue

            # Check key exists
            key_dir = self._ws.resolve_key_dir(profile_id)
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


def sanitize_profile_id(value: str) -> str:
    """Make a filesystem-safe profile id from an arbitrary config name."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", value).strip("._")
    return cleaned or "legacy_config"


#: Historical private name, kept so existing references keep working.
_sanitize_profile_id = sanitize_profile_id


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
    """Create a new profile with partitions and optional key store.

    A request with ``allow_empty`` set may create a profile with zero
    partitions: ``config.no_partitions`` is filtered out of the validation
    issues (the domain validator stays strict) so the "create config,
    then add keys, then fill in partitions" flow works.  Every other
    issue is still reported.

    A request with ``overwrite`` set reuses an existing profile directory
    instead of reporting ``config.profile_exists``: the partition set is
    replaced and the ``keys/`` content is left alone (the manifest is only
    seeded when it does not exist yet).
    """

    def __init__(self, workspace: WorkspacePaths) -> None:
        self._ws = workspace

    def execute(self, request: ConfigCreateRequest) -> ConfigCreateResult:
        issues: list[OperationIssue] = []
        repo = ProfileRepository(self._ws)

        # The requested id must be usable as a directory name as-is;
        # silently rewriting it would create a profile under another id.
        profile_id = _sanitize_profile_id(request.profile_id)
        if profile_id != request.profile_id:
            issues.append(
                OperationIssue(
                    "config.invalid_profile_id",
                    f"Invalid profile id: {request.profile_id!r} "
                    "(use letters, digits, '_', '-', '.' only)",
                )
            )
            return ConfigCreateResult(profile_id=request.profile_id, issues=tuple(issues))

        # Check for conflicts
        existing = repo.list_profiles()
        if profile_id in existing and not request.overwrite:
            issues.append(
                OperationIssue(
                    "config.profile_exists",
                    f"Profile already exists: {profile_id}",
                )
            )
            return ConfigCreateResult(profile_id=profile_id, issues=tuple(issues))

        # Build profile
        partitions = {p.partition_name: p for p in request.partitions}
        profile = AvbProfile(
            id=profile_id,
            name=request.profile_name,
            key_store_path="keys",
            partitions=partitions,
        )

        # Validate
        from avbpowertool.domain.validation import validate_profile

        validation_issues = validate_profile(profile)
        if request.allow_empty:
            validation_issues = [
                issue for issue in validation_issues if issue.error_code != "config.no_partitions"
            ]
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
            return ConfigCreateResult(profile_id=profile_id, issues=tuple(issues))

        # Create profile directory and key store
        profile_dir = self._ws.resolve_profile_dir(profile_id)
        key_dir = self._ws.resolve_key_dir(profile_id)

        created = False
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
                repo.activate(profile_id)

            created = True
            logger.info("Created profile %r", profile_id)
        except Exception as exc:
            issues.append(
                OperationIssue("config.create_failed", f"Failed to create profile: {exc}")
            )

        return ConfigCreateResult(profile_id=profile_id, created=created, issues=tuple(issues))


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
        repo = ProfileRepository(self._ws)

        try:
            profile_id = repo.resolve_profile_id(request.profile_id)
        except ConfigError as exc:
            issues.append(OperationIssue(exc.error_code, str(exc)))
            return ConfigMigrateResult(profile_id=request.profile_id, issues=tuple(issues))

        profile_path = self._ws.resolve_profile_dir(profile_id) / "profile.json"
        if not profile_path.exists():
            issues.append(OperationIssue("config.not_found", f"Profile not found: {profile_id}"))
            return ConfigMigrateResult(profile_id=profile_id, issues=tuple(issues))

        try:
            with open(profile_path, encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            issues.append(
                OperationIssue(
                    "config.parse_error",
                    f"Failed to read profile {profile_id!r}: {exc}",
                )
            )
            return ConfigMigrateResult(profile_id=profile_id, issues=tuple(issues))

        schema_version = data.get("schema_version", 0)
        if schema_version == 3:
            return ConfigMigrateResult(profile_id=profile_id, migrated=False)

        if schema_version != 2:
            issues.append(
                OperationIssue(
                    "config.invalid_schema_version",
                    f"Unsupported schema_version {schema_version}; only v2 and v3 can be handled",
                )
            )
            return ConfigMigrateResult(profile_id=profile_id, issues=tuple(issues))

        try:
            profile, migration_issues = decode_profile_with_issues(data)
            issues.extend(migration_issues)
            # Rewrite the migrated dict back to the same file (in-place),
            # regardless of the profile id embedded in the JSON.
            v3_data = encode_profile(profile)
            profile_path.write_text(
                json.dumps(v3_data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            logger.info("Migrated profile %r to schema v3", profile_id)
        except Exception as exc:
            issues.append(OperationIssue("config.migrate_failed", f"Migration failed: {exc}"))
            return ConfigMigrateResult(profile_id=profile_id, issues=tuple(issues))

        return ConfigMigrateResult(
            profile_id=profile_id,
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
        "key_id",
    }
)
#: fields whose value is parsed through ``SigningAlgorithm.from_str``
_ALGORITHM_FIELDS = frozenset({"algorithm"})
#: fields whose value must name an image file (``*.img``)
_IMAGE_FIELDS = frozenset({"image"})
#: tuple fields whose items are ``KEY:VALUE`` pairs
_PAIR_FIELDS = frozenset({"props", "prop_from_file"})
_TUPLE_FIELDS = frozenset(
    {
        "kernel_cmdlines",
        "chain_partitions",
        "chain_partitions_do_not_use_ab",
        "included_partitions",
        "include_descriptors_from_image",
        "props",
        "prop_from_file",
    }
)
#: tuple fields whose items are ``PARTITION:SLOT:KEY_FILE`` triples
_CHAIN_FIELDS = frozenset({"chain_partitions", "chain_partitions_do_not_use_ab"})
#: chain slot numbers must be plain ASCII digits (``int()`` accepts more)
_CHAIN_SLOT_PATTERN = re.compile(r"[0-9]+")
#: every field accepted by ``config edit`` (``--set`` / ``--unset``)
_EDITABLE_FIELDS = (
    _INT_FIELDS | _BOOL_FIELDS | _STR_FIELDS | _ALGORITHM_FIELDS | _IMAGE_FIELDS | _TUPLE_FIELDS
)


class ConfigEditUseCase:
    """Update individual fields of one partition config.

    ``updates`` values are strings parsed according to the field's type.
    ``unset`` names fields to reset to their empty value (str -> ``""``,
    int -> ``0``, bool -> ``False``, tuple -> ``()``), while ``appends``
    and ``removes`` carry ``(field, item)`` pairs for tuple fields only;
    both are applied in the order they were given, removes before
    appends.  Unknown fields, invalid values, and ambiguous ``--set`` /
    ``--unset`` / ``--append`` / ``--remove`` combinations produce issues
    and the profile on disk is left untouched.
    """

    def __init__(self, workspace: WorkspacePaths) -> None:
        self._ws = workspace

    def execute(self, request: ConfigEditRequest) -> ConfigEditResult:
        issues: list[OperationIssue] = []
        repo = ProfileRepository(self._ws)

        try:
            profile_id = repo.resolve_profile_id(request.profile_id)
        except ConfigError as exc:
            issues.append(OperationIssue(exc.error_code, str(exc)))
            return ConfigEditResult(
                profile_id=request.profile_id,
                partition_name=request.partition_name,
                issues=tuple(issues),
            )

        try:
            profile = repo.load(profile_id)
        except Exception as exc:
            issues.append(OperationIssue("config.not_found", f"Failed to load profile: {exc}"))
            return ConfigEditResult(
                profile_id=profile_id,
                partition_name=request.partition_name,
                issues=tuple(issues),
            )

        if profile.id != profile_id:
            # ``ProfileRepository.save`` writes to ``profiles/<profile.id>/``
            # while the profile was loaded from ``profiles/<profile_id>/``:
            # saving now would silently create/overwrite another profile.
            issues.append(
                OperationIssue(
                    "config.profile_id_mismatch",
                    f"Profile directory {profile_id!r} contains profile id "
                    f"{profile.id!r}; saving would write to a different profile, "
                    "edit refused",
                )
            )
            return ConfigEditResult(
                profile_id=profile_id,
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
                profile_id=profile_id,
                partition_name=request.partition_name,
                issues=tuple(issues),
            )

        conflict = _conflict_message(request)
        if conflict is not None:
            issues.append(OperationIssue("config.invalid_option_combination", conflict))
            return ConfigEditResult(
                profile_id=profile_id,
                partition_name=request.partition_name,
                issues=tuple(issues),
            )

        parsed: dict[str, Any] = {}
        for field_name, raw_value in request.updates.items():
            value, error_code, message = self._parse_value(field_name, raw_value)
            if error_code:
                issues.append(OperationIssue(error_code, message))
            else:
                parsed[field_name] = value

        for field_name in request.unset:
            value, error_code, _message = self._parse_value(
                field_name, _empty_raw_value(field_name)
            )
            if error_code:
                issues.append(
                    OperationIssue(
                        error_code,
                        f"Field {field_name!r} cannot be unset (invalid empty value)",
                    )
                )
            else:
                parsed[field_name] = value

        for field_name, item in request.removes:
            self._apply_tuple_item(parsed, issues, config, field_name, item, append=False)
        for field_name, item in request.appends:
            self._apply_tuple_item(parsed, issues, config, field_name, item, append=True)

        if issues:
            return ConfigEditResult(
                profile_id=profile_id,
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
            profile_id=profile_id,
            partition_name=request.partition_name,
            issues=tuple(issues),
        )

    @staticmethod
    def _parse_field(field_name: str, raw_value: str) -> Any:
        """Parse a raw string value for a known field.

        Returns :data:`_UNSUPPORTED` for unknown fields or invalid values,
        and :data:`_INVALID_ALGORITHM` for an unparsable ``algorithm``.
        """
        if field_name in _INT_FIELDS:
            try:
                return int(raw_value)
            except ValueError:
                return _UNSUPPORTED
        if field_name in _BOOL_FIELDS:
            return raw_value.strip().lower() in {"1", "true", "yes", "on"}
        if field_name in _ALGORITHM_FIELDS:
            try:
                return SigningAlgorithm.from_str(raw_value)
            except ValueError:
                return _INVALID_ALGORITHM
        if field_name in _IMAGE_FIELDS:
            return raw_value if raw_value.endswith(".img") else _UNSUPPORTED
        if field_name in _STR_FIELDS:
            return raw_value
        if field_name in _PAIR_FIELDS:
            pairs = _parse_pairs(raw_value)
            return _UNSUPPORTED if pairs is None else pairs
        if field_name in _TUPLE_FIELDS:
            items = [item.strip() for item in raw_value.split(",") if item.strip()]
            return tuple(items)
        return _UNSUPPORTED

    @staticmethod
    def _parse_value(field_name: str, raw_value: str) -> tuple[Any, str, str]:
        """Parse *raw_value* into ``(value, error_code, message)``.

        ``error_code`` is empty on success; ``value`` is then the parsed
        value, otherwise it is meaningless.
        """
        parsed_value = ConfigEditUseCase._parse_field(field_name, raw_value)
        if parsed_value is _INVALID_ALGORITHM:
            return (
                None,
                "config.invalid_algorithm",
                f"Invalid signing algorithm: {raw_value!r}",
            )
        if parsed_value is _UNSUPPORTED:
            if field_name not in _EDITABLE_FIELDS:
                return (
                    None,
                    "config.invalid_field",
                    f"Field {field_name!r} is not editable via config edit",
                )
            return (
                None,
                "config.invalid_field",
                f"Invalid value for field {field_name!r}: {raw_value!r}",
            )
        return parsed_value, "", ""

    @staticmethod
    def _apply_tuple_item(
        parsed: dict[str, Any],
        issues: list[OperationIssue],
        config: PartitionConfig,
        field_name: str,
        item: str,
        *,
        append: bool,
    ) -> None:
        """Append or remove one *item* of a tuple field."""
        flag = "--append" if append else "--remove"
        if field_name not in _TUPLE_FIELDS:
            issues.append(
                OperationIssue(
                    "config.invalid_field",
                    f"{flag} only applies to tuple fields; {field_name!r} is not one",
                )
            )
            return

        current = _tuple_value(config, parsed, field_name)
        updated = (
            _append_item(field_name, current, item)
            if append
            else _remove_item(field_name, current, item)
        )
        if updated is None:
            message = f"Invalid {flag} item for field {field_name!r}: {item!r}"
            if append and field_name in _CHAIN_FIELDS:
                message += (
                    "; expected a full PART:SLOT:KEYFILE triple "
                    "(SLOT a number >= 1, KEYFILE non-empty)"
                )
            issues.append(OperationIssue("config.invalid_field", message))
            return
        parsed[field_name] = updated


#: sentinel returned when a field cannot be parsed / is not editable
_UNSUPPORTED = object()

#: sentinel returned when an ``algorithm`` value is not a known algorithm
_INVALID_ALGORITHM = object()


def _empty_raw_value(field_name: str) -> str:
    """Raw value that resets *field_name* to its empty/neutral state."""
    if field_name in _INT_FIELDS:
        return "0"
    if field_name in _BOOL_FIELDS:
        return "false"
    return ""


def _conflict_message(request: ConfigEditRequest) -> str | None:
    """Describe an ambiguous field combination, or ``None`` when clean.

    ``--set``/``--unset`` replace a whole field while ``--append``/
    ``--remove`` edit it item by item; combining both forms for the same
    field is rejected instead of silently picking one.
    """
    set_fields = set(request.updates)
    unset_fields = set(request.unset)
    append_fields = {field_name for field_name, _item in request.appends}
    remove_fields = {field_name for field_name, _item in request.removes}

    both_forms = sorted(set_fields & unset_fields)
    if both_forms:
        return (
            f"Field(s) {', '.join(both_forms)} given in both --set and --unset; "
            "use one form per field"
        )

    mixed = sorted((set_fields | unset_fields) & (append_fields | remove_fields))
    if mixed:
        return (
            f"Field(s) {', '.join(mixed)} given in both --set/--unset and --append/--remove; "
            "use one form per field"
        )
    return None


def _tuple_value(
    config: PartitionConfig, parsed: dict[str, Any], field_name: str
) -> tuple[Any, ...]:
    """Current tuple value of *field_name*, including earlier edits."""
    raw: object = parsed[field_name] if field_name in parsed else getattr(config, field_name, ())
    return cast("tuple[Any, ...]", raw) if isinstance(raw, tuple) else ()


def _chain_partition_of(item: str) -> str:
    """Partition name of a chain item (the segment before the first ``:``)."""
    return item.split(":", 1)[0].strip()


def _parse_pairs(raw_value: str) -> tuple[tuple[str, str], ...] | None:
    """Parse ``KEY:VALUE,KEY2:VALUE2`` into pairs.

    Values may contain ``:`` (only the first one separates key and value);
    an empty key or a missing separator makes the whole value invalid and
    ``None`` is returned.
    """
    pairs: list[tuple[str, str]] = []
    for entry in raw_value.split(","):
        entry = entry.strip()
        if not entry:
            continue
        key, separator, value = entry.partition(":")
        key = key.strip()
        if not separator or not key:
            return None
        pairs.append((key, value))
    return tuple(pairs)


def _parse_single_pair(item: str) -> tuple[str, str] | None:
    """Parse exactly one ``KEY:VALUE`` pair, or ``None`` when malformed."""
    pairs = _parse_pairs(item)
    if pairs is None or len(pairs) != 1:
        return None
    return pairs[0]


def _parse_chain_item(item: str) -> tuple[str, str, str] | None:
    """Split a chain item into ``(PART, SLOT, KEYFILE)``, or ``None``.

    Only the first two ``:`` separate the three parts, so the key file
    name may itself contain ``:`` (e.g. a Windows path).  A well-formed
    item has a non-empty partition, a numeric slot ``>= 1``, and a
    non-empty key file name.
    """
    parts = item.split(":", 2)
    if len(parts) != 3:
        return None
    partition, slot, key_file = (part.strip() for part in parts)
    if not partition or not key_file:
        return None
    if _CHAIN_SLOT_PATTERN.fullmatch(slot) is None or int(slot) < 1:
        return None
    return partition, slot, key_file


def _append_item(field_name: str, items: tuple[Any, ...], item: str) -> tuple[Any, ...] | None:
    """Append *item* to *items*, or ``None`` when the item is malformed.

    Chain fields require a full ``PARTITION:SLOT:KEY_FILE`` triple and
    merge by partition name: an item for a partition that is already
    chained replaces that entry in place (keeping its position) instead of
    adding a duplicate.
    """
    if field_name in _PAIR_FIELDS:
        pair = _parse_single_pair(item)
        return None if pair is None else (*items, pair)

    entry = item.strip()
    if not entry:
        return None

    if field_name in _CHAIN_FIELDS:
        triple = _parse_chain_item(entry)
        if triple is None:
            return None
        partition = triple[0]
        for index, existing in enumerate(items):
            if _chain_partition_of(str(existing)) == partition:
                replaced = list(items)
                replaced[index] = entry
                return tuple(replaced)
    return (*items, entry)


def _remove_item(field_name: str, items: tuple[Any, ...], item: str) -> tuple[Any, ...] | None:
    """Remove matching entries from *items*, or ``None`` when malformed.

    Chain fields match by partition name (a bare partition name or a full
    ``PARTITION:SLOT:KEY_FILE`` triple both work); every other tuple field
    matches the whole item.
    """
    if field_name in _PAIR_FIELDS:
        pair = _parse_single_pair(item)
        if pair is None:
            return None
        return tuple(existing for existing in items if existing != pair)

    entry = item.strip()
    if not entry:
        return None

    if field_name in _CHAIN_FIELDS:
        partition = _chain_partition_of(entry)
        if not partition:
            return None
        return tuple(
            existing for existing in items if _chain_partition_of(str(existing)) != partition
        )
    return tuple(existing for existing in items if existing != entry)
