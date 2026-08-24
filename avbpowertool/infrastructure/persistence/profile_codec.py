"""v3 profile JSON codec — encode/decode between domain models and JSON.

Round-trip safe: decode(encode(profile)) == profile (modulo dict ordering).
Deterministic key ordering on encode (sorted).

Decoding accepts both v3 (native) and v2 (auto-migrated via
``v2_to_v3.migrate_v2_to_v3``); migration issues are surfaced through
:func:`decode_profile_with_issues`.
"""

from __future__ import annotations

from typing import Any

from avbpowertool.domain.errors import ConfigError
from avbpowertool.domain.models import (
    AvbProfile,
    DescriptorType,
    OperationIssue,
    PartitionConfig,
    SigningAlgorithm,
)
from avbpowertool.infrastructure.persistence.v2_to_v3 import migrate_v2_to_v3

# Schema version constant
SCHEMA_VERSION = 3


def encode_profile(profile: AvbProfile) -> dict[str, Any]:
    """Encode a domain AvbProfile to a v3 JSON-serializable dict."""
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
        # partition size
        if pc.partition_size > 0:
            entry["partition_size"] = pc.partition_size
        if pc.dynamic_partition_size:
            entry["dynamic_partition_size"] = True
        # rollback / digest
        if pc.rollback_index != 0:
            entry["rollback_index"] = pc.rollback_index
        if pc.rollback_index_location != 0:
            entry["rollback_index_location"] = pc.rollback_index_location
        if pc.salt:
            entry["salt"] = pc.salt
        if pc.hash_algorithm != "sha256":
            entry["hash_algorithm"] = pc.hash_algorithm
        # descriptor properties
        if pc.flags:
            entry["flags"] = pc.flags
        if pc.props:
            entry["props"] = [[k, v] for k, v in pc.props]
        if pc.prop_from_file:
            entry["prop_from_file"] = [[k, v] for k, v in pc.prop_from_file]
        if pc.set_hashtree_disabled_flag:
            entry["set_hashtree_disabled_flag"] = True
        if pc.set_verification_disabled_flag:
            entry["set_verification_disabled_flag"] = True
        # hashtree-specific
        if pc.descriptor == DescriptorType.HASHTREE:
            if pc.block_size != 4096:
                entry["block_size"] = pc.block_size
            if pc.do_not_generate_fec:
                entry["do_not_generate_fec"] = True
            if pc.fec_num_roots != 2:
                entry["fec_num_roots"] = pc.fec_num_roots
            if pc.no_hashtree:
                entry["no_hashtree"] = True
            if pc.check_at_most_once:
                entry["check_at_most_once"] = True
            if pc.setup_as_rootfs_from_kernel:
                entry["setup_as_rootfs_from_kernel"] = True
        # vbmeta / footer common
        if pc.included_partitions:
            entry["included_partitions"] = list(pc.included_partitions)
        if pc.include_descriptors_from_image:
            entry["include_descriptors_from_image"] = list(pc.include_descriptors_from_image)
        if pc.chain_partitions:
            entry["chain_partitions"] = list(pc.chain_partitions)
        if pc.chain_partitions_do_not_use_ab:
            entry["chain_partitions_do_not_use_ab"] = list(pc.chain_partitions_do_not_use_ab)
        if pc.kernel_cmdlines:
            entry["kernel_cmdlines"] = list(pc.kernel_cmdlines)
        if pc.setup_rootfs_from_kernel:
            entry["setup_rootfs_from_kernel"] = pc.setup_rootfs_from_kernel
        if pc.padding_size:
            entry["padding_size"] = pc.padding_size
        if pc.output_vbmeta_image:
            entry["output_vbmeta_image"] = pc.output_vbmeta_image
        # behavior switches
        if pc.calc_max_image_size:
            entry["calc_max_image_size"] = True
        if pc.do_not_append_vbmeta_image:
            entry["do_not_append_vbmeta_image"] = True
        if pc.print_required_libavb_version:
            entry["print_required_libavb_version"] = True
        if pc.use_persistent_digest:
            entry["use_persistent_digest"] = True
        if pc.do_not_use_ab:
            entry["do_not_use_ab"] = True
        # signing helper
        if pc.signing_helper:
            entry["signing_helper"] = pc.signing_helper
        if pc.signing_helper_with_files:
            entry["signing_helper_with_files"] = pc.signing_helper_with_files
        if pc.public_key_metadata:
            entry["public_key_metadata"] = pc.public_key_metadata
        if pc.append_to_release_string:
            entry["append_to_release_string"] = pc.append_to_release_string

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
    """Decode a JSON dict to a domain AvbProfile (v3, or auto-migrated v2)."""
    profile, _ = decode_profile_with_issues(data)
    return profile


def decode_profile_with_issues(
    data: dict[str, Any],
) -> tuple[AvbProfile, list[OperationIssue]]:
    """Decode a JSON dict to an AvbProfile plus migration issues.

    v2 inputs are auto-migrated to v3 in memory (the file on disk is
    untouched); any migration warnings are returned as issues.
    """
    schema_version: int = data.get("schema_version", 0)
    if schema_version == 2:
        data, issues = migrate_v2_to_v3(data)
    elif schema_version == SCHEMA_VERSION:
        issues = []
    else:
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

    return (
        AvbProfile(
            id=profile_id,
            name=profile_name,
            schema_version=SCHEMA_VERSION,
            key_store_path=key_store_path,
            partitions=partitions,
        ),
        issues,
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
    partition_size = _parse_int(entry.get("partition_size"), 0)
    dynamic_partition_size = bool(entry.get("dynamic_partition_size", False))
    rollback_index = _parse_int(entry.get("rollback_index"), 0)
    rollback_index_location = _parse_int(entry.get("rollback_index_location"), 0)
    salt = entry.get("salt", "")
    hash_algorithm = entry.get("hash_algorithm", "sha256")
    flags = _parse_int(entry.get("flags"), 0)

    # Props / prop_from_file: stored as [[key, value], ...] or {key: value}
    props = _parse_pairs(entry.get("props"))
    prop_from_file = _parse_pairs(entry.get("prop_from_file"))

    # flag shortcuts
    set_hashtree_disabled_flag = bool(entry.get("set_hashtree_disabled_flag", False))
    set_verification_disabled_flag = bool(entry.get("set_verification_disabled_flag", False))

    # hashtree-specific
    block_size = _parse_int(entry.get("block_size"), 4096)
    do_not_generate_fec = bool(entry.get("do_not_generate_fec", False))
    fec_num_roots = _parse_int(entry.get("fec_num_roots"), 2)
    no_hashtree = bool(entry.get("no_hashtree", False))
    check_at_most_once = bool(entry.get("check_at_most_once", False))
    setup_as_rootfs_from_kernel = bool(entry.get("setup_as_rootfs_from_kernel", False))

    # vbmeta / footer common
    included_partitions = tuple(entry.get("included_partitions", ()))
    include_descriptors_from_image = tuple(entry.get("include_descriptors_from_image", ()))
    chain_partitions = tuple(entry.get("chain_partitions", ()))
    chain_partitions_do_not_use_ab = tuple(entry.get("chain_partitions_do_not_use_ab", ()))
    kernel_cmdlines = _parse_str_tuple(entry.get("kernel_cmdlines"))
    setup_rootfs_from_kernel = entry.get("setup_rootfs_from_kernel", "")
    padding_size = _parse_int(entry.get("padding_size"), 0)
    output_vbmeta_image = entry.get("output_vbmeta_image", "")

    # behavior switches
    calc_max_image_size = bool(entry.get("calc_max_image_size", False))
    do_not_append_vbmeta_image = bool(entry.get("do_not_append_vbmeta_image", False))
    print_required_libavb_version = bool(entry.get("print_required_libavb_version", False))
    use_persistent_digest = bool(entry.get("use_persistent_digest", False))
    do_not_use_ab = bool(entry.get("do_not_use_ab", False))

    # signing helper
    signing_helper = entry.get("signing_helper", "")
    signing_helper_with_files = entry.get("signing_helper_with_files", "")
    public_key_metadata = entry.get("public_key_metadata", "")
    append_to_release_string = entry.get("append_to_release_string", "")

    return PartitionConfig(
        image=image,
        descriptor=descriptor,
        algorithm=algorithm,
        key_id=key_id,
        partition_name=partition_name,
        partition_size=partition_size,
        dynamic_partition_size=dynamic_partition_size,
        rollback_index=rollback_index,
        rollback_index_location=rollback_index_location,
        hash_algorithm=hash_algorithm,
        salt=salt,
        flags=flags,
        props=props,
        prop_from_file=prop_from_file,
        set_hashtree_disabled_flag=set_hashtree_disabled_flag,
        set_verification_disabled_flag=set_verification_disabled_flag,
        block_size=block_size,
        do_not_generate_fec=do_not_generate_fec,
        fec_num_roots=fec_num_roots,
        no_hashtree=no_hashtree,
        check_at_most_once=check_at_most_once,
        setup_as_rootfs_from_kernel=setup_as_rootfs_from_kernel,
        included_partitions=included_partitions,
        include_descriptors_from_image=include_descriptors_from_image,
        chain_partitions=chain_partitions,
        chain_partitions_do_not_use_ab=chain_partitions_do_not_use_ab,
        kernel_cmdlines=kernel_cmdlines,
        setup_rootfs_from_kernel=setup_rootfs_from_kernel,
        padding_size=padding_size,
        output_vbmeta_image=output_vbmeta_image,
        calc_max_image_size=calc_max_image_size,
        do_not_append_vbmeta_image=do_not_append_vbmeta_image,
        print_required_libavb_version=print_required_libavb_version,
        use_persistent_digest=use_persistent_digest,
        do_not_use_ab=do_not_use_ab,
        signing_helper=signing_helper,
        signing_helper_with_files=signing_helper_with_files,
        public_key_metadata=public_key_metadata,
        append_to_release_string=append_to_release_string,
    )


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------


def _parse_int(value: Any, default: int) -> int:
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    if isinstance(value, int):
        return value
    return default


def _parse_pairs(value: Any) -> tuple[tuple[str, str], ...]:
    """Parse props/prop_from_file stored as [[k, v], ...] or {k: v}."""
    if isinstance(value, dict):
        return tuple(sorted((str(k), str(v)) for k, v in value.items()))
    if isinstance(value, list):
        return tuple((str(p[0]), str(p[1])) for p in value)
    return ()


def _parse_str_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(v) for v in value)
    if isinstance(value, str):
        return (value,) if value else ()
    return ()
