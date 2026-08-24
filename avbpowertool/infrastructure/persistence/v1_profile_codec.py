"""Legacy (v1) profile codec — decode AVBPowerTool 1.x configs to v2 models.

Reads the config format produced by AVBPowerTool 1.x (see ``references/AVBPowerTool``):
a ``Configs/<name>/imageInfo.json`` partition map plus a ``Keys/<name>/`` key store.

Conversion preserves every signing-relevant field. Informational fields with no v2
equivalent (``Image size``, ``Root Digest``, ``Version of dm-verity``) are dropped.
Partitions with ``Algorithm: NONE`` map to ``SigningAlgorithm.NONE`` (v2 supports
unsigned footers/vbmeta).
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path
from typing import Any

from avbpowertool.domain.errors import ConfigError
from avbpowertool.domain.models import (
    AvbProfile,
    DescriptorType,
    OperationIssue,
    PartitionConfig,
    SigningAlgorithm,
)

V1_ARCHIVE_FLAG = "this_is_a_config_file_of_avbpowertool"
V1_BATCH_FLAG = "BATCH_CONFIG_AVBPOWERTOOL"
V1_RENAME_FLAG = "RENAME_REQUIRED"

# v1 descriptor labels -> v2 DescriptorType
_V1_DESCRIPTOR_TO_TYPE = {
    "hash": DescriptorType.HASH,
    "hashtree": DescriptorType.HASHTREE,
}


# ---------------------------------------------------------------------------
# Archive detection / extraction
# ---------------------------------------------------------------------------


def detect_v1_archive(archive_path: Path) -> str:
    """Return ``"single"`` | ``"batch"`` | ``"none"`` for a candidate ZIP."""
    if not archive_path.is_file():
        return "none"
    try:
        with zipfile.ZipFile(archive_path) as zf:
            names = set(zf.namelist())
    except (OSError, zipfile.BadZipFile):
        return "none"
    if V1_BATCH_FLAG in names:
        return "batch"
    if V1_ARCHIVE_FLAG in names or _has_v1_layout(names):
        return "single"
    return "none"


def extract_v1_archive(archive_path: Path, staging_dir: Path) -> Path:
    """Extract a single v1 config archive into ``staging_dir``.

    Returns the staging root. Raises ConfigError for missing, batch, or
    unsafe archives.
    """
    if not archive_path.is_file():
        raise ConfigError(
            f"Archive not found: {archive_path}",
            error_code="config.not_found",
        )
    archive_type = detect_v1_archive(archive_path)
    if archive_type == "batch":
        raise ConfigError(
            "Batch v1 archives are not supported",
            error_code="import.legacy.batch_not_supported",
        )
    if archive_type != "single":
        raise ConfigError(
            f"Not a v1 config archive: {archive_path}",
            error_code="config.invalid_archive",
        )

    staging_root = staging_dir / archive_path.stem
    staging_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as zf:
        for info in zf.infolist():
            name = info.filename
            _validate_v1_member(name)
            if info.is_dir():
                continue
            target = staging_root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    return staging_root


def find_config_dir(staging_root: Path) -> Path:
    """Locate the directory holding ``imageInfo.json`` under ``Configs/``."""
    base = staging_root / "Configs"
    if base.is_dir():
        if (base / "imageInfo.json").is_file():
            return base
        for child in sorted(base.iterdir()):
            if child.is_dir() and (child / "imageInfo.json").is_file():
                return child
    raise ConfigError(
        "v1 archive missing imageInfo.json",
        error_code="config.invalid_archive",
    )


def find_keys_dir(staging_root: Path) -> Path | None:
    """Locate the v1 ``Keys/<name>/`` directory, or None if absent."""
    base = staging_root / "Keys"
    if not base.is_dir():
        return None
    if _looks_like_keys_dir(base):
        return base
    for child in sorted(base.iterdir()):
        if child.is_dir() and _looks_like_keys_dir(child):
            return child
    return None


def _looks_like_keys_dir(directory: Path) -> bool:
    return any(
        p.is_file() and (p.suffix == ".pem" or p.name == "keyCache.cache")
        for p in directory.iterdir()
    )


def _has_v1_layout(names: set[str]) -> bool:
    has_config = any(n.startswith("Configs/") and n.endswith("imageInfo.json") for n in names)
    has_keys = any(n.startswith("Keys/") for n in names)
    return has_config and has_keys


def _validate_v1_member(name: str) -> None:
    if any(part == ".." for part in Path(name).parts):
        raise ConfigError(
            f"Archive contains path traversal: {name!r}",
            error_code="config.invalid_archive",
        )
    if Path(name).is_absolute():
        raise ConfigError(
            f"Archive contains absolute path: {name!r}",
            error_code="config.invalid_archive",
        )


# ---------------------------------------------------------------------------
# imageInfo.json -> AvbProfile
# ---------------------------------------------------------------------------


def decode_v1_image_info(
    raw: dict[str, Any],
    config_id: str,
) -> tuple[AvbProfile, list[OperationIssue]]:
    """Convert a v1 ``imageInfo.json`` dict to a v3 AvbProfile.

    ``config_id`` becomes the profile id and name. Returns conversion
    warnings/issues alongside the profile.
    """
    issues: list[OperationIssue] = []
    partitions: dict[str, PartitionConfig] = {}

    for name, entry in raw.items():
        if not isinstance(entry, dict):
            issues.append(
                OperationIssue(
                    "import.legacy.invalid_entry",
                    f"Partition {name!r}: entry is not a dict; skipped",
                )
            )
            continue
        partition, partition_issues = _decode_partition(name, entry)
        issues.extend(partition_issues)
        partitions[name] = partition

    profile = AvbProfile(
        id=config_id,
        name=config_id,
        schema_version=3,
        key_store_path="keys",
        partitions=partitions,
    )
    return profile, issues


def _decode_partition(
    name: str,
    entry: dict[str, Any],
) -> tuple[PartitionConfig, list[OperationIssue]]:
    issues: list[OperationIssue] = []
    descriptor = _detect_descriptor(name, entry)
    algorithm = _parse_algorithm(entry.get("Algorithm", "NONE"), issues)
    key_id = _parse_key_id(entry, issues)
    partition_name = str(entry.get("Partition Name") or name)
    image = str(entry.get("Image File") or f"{name}.img")
    rollback_index = _parse_int(entry.get("Rollback Index"))
    flags = _parse_int(entry.get("Flags"))
    salt = str(entry.get("Salt") or "")
    hash_algorithm = str(entry.get("Hash Algorithm") or "sha256")
    props = _parse_props(entry.get("Props"))
    # v1 kept separate data/hash block sizes; v3 uses one --block_size.
    data_block_size = _parse_block_size(entry.get("Data Block Size"))
    hash_block_size = _parse_block_size(entry.get("Hash Block Size"))
    block_size = data_block_size or hash_block_size
    if data_block_size and hash_block_size and data_block_size != hash_block_size:
        issues.append(
            OperationIssue(
                "import.legacy.block_size_conflict",
                f"Partition {name!r}: data/hash block sizes differ "
                f"({data_block_size} vs {hash_block_size}); using {data_block_size}",
            )
        )

    included_partitions: tuple[str, ...] = ()
    chain_partitions: tuple[str, ...] = ()
    if descriptor == DescriptorType.VBMETA:
        included_partitions = tuple(
            _as_str_list(entry.get("Hash")) + _as_str_list(entry.get("Hashtree"))
        )
        chain_partitions = _decode_chains(entry, issues)

    return (
        PartitionConfig(
            image=image,
            descriptor=descriptor,
            algorithm=algorithm,
            key_id=key_id,
            partition_name=partition_name,
            rollback_index=rollback_index,
            salt=salt,
            flags=flags,
            props=props,
            hash_algorithm=hash_algorithm,
            included_partitions=included_partitions,
            chain_partitions=chain_partitions,
            block_size=block_size,
        ),
        issues,
    )


def _detect_descriptor(name: str, entry: dict[str, Any]) -> DescriptorType:
    if "vbmeta" in name.lower() or "Chain" in entry:
        return DescriptorType.VBMETA
    label = str(entry.get("Descriptor Type", "")).lower()
    return _V1_DESCRIPTOR_TO_TYPE.get(label, DescriptorType.HASH)


def _parse_algorithm(value: Any, issues: list[OperationIssue]) -> SigningAlgorithm:
    try:
        return SigningAlgorithm.from_str(str(value))
    except ValueError:
        issues.append(
            OperationIssue(
                "import.legacy.unsupported_algorithm",
                f"Unknown algorithm {value!r}; treating as NONE",
            )
        )
        return SigningAlgorithm.NONE


def _parse_key_id(entry: dict[str, Any], issues: list[OperationIssue]) -> str:
    key_file = str(entry.get("Public key file") or "")
    if not key_file:
        return ""  # unsigned (NONE) partition
    if key_file.upper() == "NOT_FOUND":
        issues.append(
            OperationIssue(
                "import.legacy.key_not_found",
                f"Partition {entry.get('Partition Name', '')!r}: "
                "v1 recorded 'NOT_FOUND' for the public key",
            )
        )
        return ""
    return key_file.removesuffix(".pem")


def _decode_chains(
    entry: dict[str, Any],
    issues: list[OperationIssue],
) -> tuple[str, ...]:
    chains = _as_str_list(entry.get("Chain"))
    keys = _as_str_list(entry.get("Chain partition key"))
    result: list[str] = []
    for index, chain in enumerate(chains):
        parts = chain.split(":")
        chain_name = parts[0] if parts else chain
        location = parts[1] if len(parts) > 1 else "0"
        key_file = keys[index] if index < len(keys) else ""
        if not key_file:
            issues.append(
                OperationIssue(
                    "import.legacy.partial_chain",
                    f"Chain entry {chain!r} has no matching public key",
                )
            )
        result.append(f"{chain_name}:{location}:{key_file}")
    return tuple(result)


# ---------------------------------------------------------------------------
# keyCache.cache -> key manifest
# ---------------------------------------------------------------------------


def build_key_manifest(
    keys_dir: Path,
    key_cache: Path | None = None,
) -> tuple[dict[str, dict[str, str]], list[OperationIssue]]:
    """Build a v2 ``keys/manifest.json`` from a v1 key store.

    ``key_id`` = PEM filename minus ``.pem`` (matches v2 auto-discovery).
    ``public_key`` points at the sibling ``_pub.bin`` when present;
    ``public_key_sha1`` comes from ``keyCache.cache`` when available.
    """
    issues: list[OperationIssue] = []
    sha_map: dict[str, str] = {}
    if key_cache is not None and key_cache.is_file():
        sha_map = _parse_key_cache(key_cache)

    manifest: dict[str, dict[str, str]] = {}
    if keys_dir.is_dir():
        for f in sorted(keys_dir.iterdir()):
            if not (f.is_file() and f.suffix == ".pem"):
                continue
            entry: dict[str, str] = {"private_key": f.name}
            pub_bin = keys_dir / (f.stem + "_pub.bin")
            if pub_bin.is_file():
                entry["public_key"] = pub_bin.name
            digest = sha_map.get(f.name)
            if digest:
                entry["public_key_sha1"] = digest
            manifest[f.stem] = entry
    return manifest, issues


def _parse_key_cache(path: Path) -> dict[str, str]:
    """Parse ``keyCache.cache`` lines of the form ``pem_name, sha1_digest``."""
    result: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return result
    for line in lines:
        line = line.strip()
        if not line or ", " not in line:
            continue
        filename, _, digest = line.partition(", ")
        if filename and digest:
            result[filename.strip()] = digest.strip()
    return result


# ---------------------------------------------------------------------------
# Shared v1 value helpers
# ---------------------------------------------------------------------------


def _parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _parse_block_size(value: Any, default: int = 4096) -> int:
    if value is None:
        return default
    text = str(value).strip().lower()
    for suffix in ("bytes", "byte"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    try:
        return int(text)
    except ValueError:
        return default


def _parse_props(value: Any) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, dict):
        return ()
    return tuple((str(k), str(v)) for k, v in value.items())


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [value] if value else []
    return []
