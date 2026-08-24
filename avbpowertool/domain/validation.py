"""Domain validation for profiles, partitions, and key manifests.

Validators return lists of OperationIssue — never raise.
"""

from __future__ import annotations

from typing import Any

from .models import (
    AvbProfile,
    DescriptorType,
    OperationIssue,
    PartitionConfig,
    SigningAlgorithm,
)

# Algorithms valid for each descriptor type.
# NONE is valid: avbtool produces an unsigned footer/vbmeta (no --algorithm/--key).
_VALID_SIGNING_ALGORITHMS = frozenset(
    {
        SigningAlgorithm.NONE,
        SigningAlgorithm.SHA256_RSA2048,
        SigningAlgorithm.SHA256_RSA4096,
        SigningAlgorithm.SHA512_RSA2048,
        SigningAlgorithm.SHA512_RSA4096,
    }
)

#: avbtool requires the partition size to be a multiple of the image
#: block size (ImageHandler.block_size == 4096).
_IMAGE_BLOCK_SIZE = 4096

#: FEC roots accepted by the fec encoder (2..255).
_MIN_FEC_NUM_ROOTS = 2
_MAX_FEC_NUM_ROOTS = 255


def validate_profile(profile: AvbProfile) -> list[OperationIssue]:
    """Validate a complete profile. Returns issues found."""
    issues: list[OperationIssue] = []

    if profile.schema_version != 3:
        issues.append(
            OperationIssue(
                "config.invalid_schema_version",
                f"Expected schema_version 3, got {profile.schema_version}",
            )
        )

    if not profile.id:
        issues.append(OperationIssue("config.missing_profile_id", "Profile ID is empty"))

    if not profile.name:
        issues.append(OperationIssue("config.missing_profile_name", "Profile name is empty"))

    if not profile.partitions:
        issues.append(OperationIssue("config.no_partitions", "Profile has no partitions"))
        return issues

    for partition_name, partition_config in profile.partitions.items():
        issues.extend(validate_partition(partition_name, partition_config))

    return issues


def validate_partition(name: str, config: PartitionConfig) -> list[OperationIssue]:
    """Validate a single partition configuration."""
    issues: list[OperationIssue] = []

    if not config.image:
        issues.append(OperationIssue("config.missing_image", f"Partition {name!r}: image is empty"))

    # key_id is not required for unsigned (NONE) partitions
    if config.algorithm != SigningAlgorithm.NONE and not config.key_id:
        issues.append(OperationIssue("config.key_missing", f"Partition {name!r}: key_id is empty"))

    if not config.partition_name:
        issues.append(
            OperationIssue(
                "config.missing_partition_name",
                f"Partition {name!r}: partition_name is empty",
            )
        )

    # Algorithm validity per descriptor type
    if (
        config.descriptor
        in {
            DescriptorType.HASH,
            DescriptorType.HASHTREE,
            DescriptorType.VBMETA,
        }
        and config.algorithm not in _VALID_SIGNING_ALGORITHMS
    ):
        issues.append(
            OperationIssue(
                "config.invalid_algorithm",
                f"Partition {name!r}: algorithm {config.algorithm.value!r} "
                f"not valid for {config.descriptor.value} descriptor",
            )
        )

    # ------------------------------------------------------------------
    # Partition size (hash requires partition_size or dynamic_partition_size)
    # ------------------------------------------------------------------
    if (
        config.descriptor == DescriptorType.HASH
        and config.partition_size <= 0
        and not config.dynamic_partition_size
    ):
        issues.append(
            OperationIssue(
                "config.missing_partition_size",
                f"Partition {name!r}: hash footer requires partition_size > 0 "
                "or dynamic_partition_size",
            )
        )

    if config.dynamic_partition_size and config.calc_max_image_size:
        issues.append(
            OperationIssue(
                "config.invalid_option_combination",
                f"Partition {name!r}: dynamic_partition_size cannot be combined "
                "with calc_max_image_size (avbtool rejects this)",
            )
        )

    if config.partition_size > 0 and config.partition_size % _IMAGE_BLOCK_SIZE != 0:
        issues.append(
            OperationIssue(
                "config.invalid_partition_size",
                f"Partition {name!r}: partition_size {config.partition_size} "
                f"must be a multiple of {_IMAGE_BLOCK_SIZE}",
            )
        )

    # ------------------------------------------------------------------
    # vbmeta must have at least one included partition or chain
    # ------------------------------------------------------------------
    if (
        config.descriptor == DescriptorType.VBMETA
        and not config.included_partitions
        and not config.chain_partitions
    ):
        issues.append(
            OperationIssue(
                "config.vbmeta_no_contents",
                f"Partition {name!r}: vbmeta has no included_partitions or chain_partitions",
            )
        )

    # ------------------------------------------------------------------
    # hashtree-specific
    # ------------------------------------------------------------------
    if config.descriptor == DescriptorType.HASHTREE:
        if config.block_size <= 0 or (config.block_size & (config.block_size - 1)) != 0:
            issues.append(
                OperationIssue(
                    "config.invalid_block_size",
                    f"Partition {name!r}: block_size must be a positive power of 2",
                )
            )
        if not (_MIN_FEC_NUM_ROOTS <= config.fec_num_roots <= _MAX_FEC_NUM_ROOTS):
            issues.append(
                OperationIssue(
                    "config.invalid_fec_num_roots",
                    f"Partition {name!r}: fec_num_roots must be between "
                    f"{_MIN_FEC_NUM_ROOTS} and {_MAX_FEC_NUM_ROOTS}",
                )
            )

    # ------------------------------------------------------------------
    # Option combinations
    # ------------------------------------------------------------------
    if config.use_persistent_digest and not config.do_not_use_ab:
        issues.append(
            OperationIssue(
                "config.invalid_option_combination",
                f"Partition {name!r}: use_persistent_digest requires do_not_use_ab",
            )
        )

    # ------------------------------------------------------------------
    # Props / prop_from_file must have non-empty keys (avbtool CLI format
    # is KEY:VALUE / KEY:PATH; the model stores the pair pre-split).
    # ------------------------------------------------------------------
    for key, _value in config.props:
        if not key:
            issues.append(
                OperationIssue(
                    "config.invalid_prop",
                    f"Partition {name!r}: prop key must not be empty (KEY:VALUE)",
                )
            )
    for key, _path in config.prop_from_file:
        if not key:
            issues.append(
                OperationIssue(
                    "config.invalid_prop",
                    f"Partition {name!r}: prop_from_file key must not be empty (KEY:PATH)",
                )
            )

    # ------------------------------------------------------------------
    # Chain partitions: PART_NAME:ROLLBACK_SLOT:KEY_PATH, slot >= 1, unique
    # ------------------------------------------------------------------
    all_chains = list(config.chain_partitions) + list(config.chain_partitions_do_not_use_ab)
    used_slots: dict[int, str] = {}
    for chain in all_chains:
        parts = chain.split(":")
        if len(parts) < 3 or not parts[0] or not parts[2]:
            issues.append(
                OperationIssue(
                    "config.invalid_chain_partition",
                    f"Partition {name!r}: malformed chain partition {chain!r} "
                    "(expected PART_NAME:ROLLBACK_SLOT:KEY_PATH)",
                )
            )
            continue
        try:
            slot = int(parts[1])
        except ValueError:
            issues.append(
                OperationIssue(
                    "config.invalid_chain_partition",
                    f"Partition {name!r}: chain {chain!r} has non-integer rollback slot",
                )
            )
            continue
        if slot < 1:
            issues.append(
                OperationIssue(
                    "config.invalid_chain_partition",
                    f"Partition {name!r}: chain {chain!r} rollback slot must be >= 1",
                )
            )
        if slot in used_slots:
            issues.append(
                OperationIssue(
                    "config.duplicate_rollback_slot",
                    f"Partition {name!r}: rollback slot {slot} already used by "
                    f"chain {used_slots[slot]!r}",
                )
            )
        else:
            used_slots[slot] = chain

    return issues


def validate_key_manifest(manifest: dict[str, Any]) -> list[OperationIssue]:
    """Validate a key manifest (keys/manifest.json).

    Each key_id must have at least a 'private_key' entry.
    """
    issues: list[OperationIssue] = []

    if not manifest:
        issues.append(OperationIssue("keys.empty_manifest", "Key manifest is empty"))
        return issues

    for key_id, entry in manifest.items():
        if not isinstance(entry, dict):
            issues.append(
                OperationIssue(
                    "keys.invalid_entry",
                    f"Key {key_id!r}: manifest entry must be a dict",
                )
            )
            continue
        if "private_key" not in entry:
            issues.append(
                OperationIssue(
                    "keys.missing_private_key",
                    f"Key {key_id!r}: missing 'private_key' in manifest",
                )
            )
        elif not entry["private_key"]:
            issues.append(
                OperationIssue(
                    "keys.empty_private_key",
                    f"Key {key_id!r}: 'private_key' is empty",
                )
            )

    return issues
