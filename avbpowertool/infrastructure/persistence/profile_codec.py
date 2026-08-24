"""v2 profile JSON codec — encode/decode between domain models and JSON.

Round-trip safe: decode(encode(profile)) == profile (modulo dict ordering).
Deterministic key ordering on encode (sorted).
"""

from __future__ import annotations

from typing import Any

from avbpowertool.domain.errors import ConfigError
from avbpowertool.domain.models import (
    AvbProfile,
    DescriptorType,
    PartitionConfig,
    SigningAlgorithm,
)

# Schema version constant
SCHEMA_VERSION = 2


def encode_profile(profile: AvbProfile) -> dict[str, Any]:
    """Encode a domain AvbProfile to a v2 JSON-serializable dict."""
    partitions: dict[str, Any] = {}
    for name in sorted(profile.partitions):
        pc = profile.partitions[name]
        entry: dict[str, Any] = {
            "image": pc.image,
            "descriptor": pc.descriptor.value,
            "algorithm": pc.algorithm.value,
            "key_id": pc.key_id,
            "partition_name": pc.partition_name,
        }
        if pc.rollback_index != 0:
            entry["rollback_index"] = pc.rollback_index
        if pc.salt:
            entry["salt"] = pc.salt
        if pc.flags:
            entry["flags"] = pc.flags
        if pc.rollback_index_location != 0:
            entry["rollback_index_location"] = pc.rollback_index_location
        if pc.hash_algorithm != "sha256":
            entry["hash_algorithm"] = pc.hash_algorithm
        if pc.props:
            entry["props"] = [[k, v] for k, v in pc.props]
        if pc.included_partitions:
            entry["included_partitions"] = list(pc.included_partitions)
        if pc.chain_partitions:
            entry["chain_partitions"] = list(pc.chain_partitions)
        if pc.kernel_cmdline:
            entry["kernel_cmdline"] = pc.kernel_cmdline
        if pc.descriptor == DescriptorType.HASHTREE:
            if pc.data_block_size != 4096:
                entry["data_block_size"] = pc.data_block_size
            if pc.hash_block_size != 4096:
                entry["hash_block_size"] = pc.hash_block_size
        partitions[name] = entry

    return {
        "schema_version": profile.schema_version,
        "profile": {
            "id": profile.id,
            "name": profile.name,
        },
        "key_store_path": profile.key_store_path,
        "partitions": partitions,
    }


def decode_profile(data: dict[str, Any]) -> AvbProfile:
    """Decode a v2 JSON dict to a domain AvbProfile.

    Raises ConfigError on invalid schema.
    """
    schema_version: int = data.get("schema_version", 0)
    if schema_version != SCHEMA_VERSION:
        raise ConfigError(
            f"Expected schema_version {SCHEMA_VERSION}, got {schema_version}",
            error_code="config.invalid_schema_version",
        )

    profile_meta: Any = data.get("profile", {})
    if not isinstance(profile_meta, dict) or not profile_meta:
        raise ConfigError(
            "Missing or invalid 'profile' section",
            error_code="config.parse_error",
        )

    profile_id: str = profile_meta.get("id", "")
    profile_name: str = profile_meta.get("name", "")
    key_store_path: str = data.get("key_store_path", "keys")

    raw_partitions: Any = data.get("partitions")
    if not isinstance(raw_partitions, dict):
        raise ConfigError(
            "Missing or invalid 'partitions' section",
            error_code="config.parse_error",
        )

    partitions: dict[str, PartitionConfig] = {}
    for name, entry in raw_partitions.items():
        partitions[name] = _decode_partition(name, entry)

    return AvbProfile(
        id=profile_id,
        name=profile_name,
        schema_version=schema_version,
        key_store_path=key_store_path,
        partitions=partitions,
    )


def _decode_partition(name: str, entry: dict[str, Any]) -> PartitionConfig:
    """Decode a single partition entry from JSON."""
    # Required fields
    image: str = entry.get("image", "")
    descriptor_str: str = entry.get("descriptor", "")
    algorithm_str: str = entry.get("algorithm", "")
    key_id: str = entry.get("key_id", "")
    partition_name: str = entry.get("partition_name", "")

    # Parse descriptor type
    descriptor_str_lower = descriptor_str.lower()
    if descriptor_str_lower == "hash":
        descriptor = DescriptorType.HASH
    elif descriptor_str_lower == "hashtree":
        descriptor = DescriptorType.HASHTREE
    elif descriptor_str_lower == "vbmeta":
        descriptor = DescriptorType.VBMETA
    else:
        raise ConfigError(
            f"Partition {name!r}: unknown descriptor {descriptor_str!r}",
            error_code="config.parse_error",
        )

    # Parse algorithm
    try:
        algorithm = SigningAlgorithm.from_str(algorithm_str)
    except ValueError as exc:
        raise ConfigError(
            f"Partition {name!r}: unknown algorithm {algorithm_str!r}",
            error_code="config.parse_error",
        ) from exc

    # Optional fields
    rollback_index = entry.get("rollback_index", 0)
    if isinstance(rollback_index, str):
        rollback_index = int(rollback_index)
    rollback_index_location = entry.get("rollback_index_location", 0)
    if isinstance(rollback_index_location, str):
        rollback_index_location = int(rollback_index_location)
    salt = entry.get("salt", "")
    flags = entry.get("flags", 0)
    if isinstance(flags, str):
        flags = int(flags)
    hash_algorithm = entry.get("hash_algorithm", "sha256")

    # Props: stored as [[key, value], ...] or {key: value, ...}
    raw_props: Any = entry.get("props", ())
    props: tuple[tuple[str, str], ...]
    if isinstance(raw_props, dict):
        props = tuple(sorted((str(k), str(v)) for k, v in raw_props.items()))
    elif isinstance(raw_props, list):
        props = tuple((str(p[0]), str(p[1])) for p in raw_props)
    else:
        props = ()

    # vbmeta-specific
    included_partitions: tuple[str, ...] = tuple(entry.get("included_partitions", ()))
    chain_partitions: tuple[str, ...] = tuple(entry.get("chain_partitions", ()))
    kernel_cmdline = entry.get("kernel_cmdline", "")

    # hashtree-specific
    data_block_size = entry.get("data_block_size", 4096)
    hash_block_size = entry.get("hash_block_size", 4096)

    # flag shortcuts
    set_hashtree_disabled_flag = bool(entry.get("set_hashtree_disabled_flag", False))
    set_verification_disabled_flag = bool(entry.get("set_verification_disabled_flag", False))

    return PartitionConfig(
        image=image,
        descriptor=descriptor,
        algorithm=algorithm,
        key_id=key_id,
        partition_name=partition_name,
        rollback_index=rollback_index,
        rollback_index_location=rollback_index_location,
        hash_algorithm=hash_algorithm,
        salt=salt,
        flags=flags,
        props=props,
        included_partitions=included_partitions,
        chain_partitions=chain_partitions,
        kernel_cmdline=kernel_cmdline,
        data_block_size=data_block_size,
        hash_block_size=hash_block_size,
        set_hashtree_disabled_flag=set_hashtree_disabled_flag,
        set_verification_disabled_flag=set_verification_disabled_flag,
    )
