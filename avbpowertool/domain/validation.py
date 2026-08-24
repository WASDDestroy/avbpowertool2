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

# Algorithms valid for each descriptor type
_VALID_SIGNING_ALGORITHMS = frozenset(
    {
        SigningAlgorithm.SHA256_RSA2048,
        SigningAlgorithm.SHA256_RSA4096,
        SigningAlgorithm.SHA512_RSA2048,
        SigningAlgorithm.SHA512_RSA4096,
    }
)


def validate_profile(profile: AvbProfile) -> list[OperationIssue]:
    """Validate a complete profile. Returns issues found."""
    issues: list[OperationIssue] = []

    if profile.schema_version != 2:
        issues.append(
            OperationIssue(
                "config.invalid_schema_version",
                f"Expected schema_version 2, got {profile.schema_version}",
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

    if not config.key_id:
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

    # vbmeta must have at least one included partition or chain
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

    # hashtree block sizes must be positive powers of 2
    if config.descriptor == DescriptorType.HASHTREE:
        if (
            config.data_block_size <= 0
            or (config.data_block_size & (config.data_block_size - 1)) != 0
        ):
            issues.append(
                OperationIssue(
                    "config.invalid_block_size",
                    f"Partition {name!r}: data_block_size must be a positive power of 2",
                )
            )
        if (
            config.hash_block_size <= 0
            or (config.hash_block_size & (config.hash_block_size - 1)) != 0
        ):
            issues.append(
                OperationIssue(
                    "config.invalid_block_size",
                    f"Partition {name!r}: hash_block_size must be a positive power of 2",
                )
            )

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
