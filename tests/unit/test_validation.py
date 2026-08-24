"""Tests for domain validation."""

from __future__ import annotations

from avbpowertool.domain.models import (
    AvbProfile,
    DescriptorType,
    PartitionConfig,
    SigningAlgorithm,
)
from avbpowertool.domain.validation import (
    validate_key_manifest,
    validate_partition,
    validate_profile,
)

# ---------------------------------------------------------------------------
# Profile validation
# ---------------------------------------------------------------------------


class TestValidateProfile:
    def test_valid_profile(self) -> None:
        profile = AvbProfile(
            id="test",
            name="Test",
            partitions={
                "boot": PartitionConfig(
                    image="boot.img",
                    descriptor=DescriptorType.HASH,
                    algorithm=SigningAlgorithm.SHA256_RSA4096,
                    key_id="testkey",
                    partition_name="boot",
                    partition_size=67108864,
                ),
            },
        )
        issues = validate_profile(profile)
        assert len(issues) == 0

    def test_wrong_schema_version(self) -> None:
        profile = AvbProfile(id="test", name="Test", schema_version=1)
        issues = validate_profile(profile)
        assert any(i.error_code == "config.invalid_schema_version" for i in issues)

    def test_empty_id(self) -> None:
        profile = AvbProfile(id="", name="Test")
        issues = validate_profile(profile)
        assert any(i.error_code == "config.missing_profile_id" for i in issues)

    def test_empty_name(self) -> None:
        profile = AvbProfile(id="test", name="")
        issues = validate_profile(profile)
        assert any(i.error_code == "config.missing_profile_name" for i in issues)

    def test_no_partitions(self) -> None:
        profile = AvbProfile(id="test", name="Test")
        issues = validate_profile(profile)
        assert any(i.error_code == "config.no_partitions" for i in issues)

    def test_collects_partition_issues(self) -> None:
        profile = AvbProfile(
            id="test",
            name="Test",
            partitions={
                "bad": PartitionConfig(
                    image="",
                    descriptor=DescriptorType.HASH,
                    algorithm=SigningAlgorithm.SHA256_RSA4096,
                    key_id="",
                    partition_name="",
                ),
            },
        )
        issues = validate_profile(profile)
        codes = {i.error_code for i in issues}
        assert "config.missing_image" in codes
        assert "config.key_missing" in codes
        assert "config.missing_partition_name" in codes


# ---------------------------------------------------------------------------
# Partition validation
# ---------------------------------------------------------------------------


class TestValidatePartition:
    def test_valid_hash(self) -> None:
        config = PartitionConfig(
            image="boot.img",
            descriptor=DescriptorType.HASH,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="testkey",
            partition_name="boot",
            partition_size=67108864,
        )
        issues = validate_partition("boot", config)
        assert len(issues) == 0

    def test_valid_hash_dynamic_size(self) -> None:
        config = PartitionConfig(
            image="boot.img",
            descriptor=DescriptorType.HASH,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="testkey",
            partition_name="boot",
            dynamic_partition_size=True,
        )
        issues = validate_partition("boot", config)
        assert len(issues) == 0

    def test_hash_missing_partition_size(self) -> None:
        config = PartitionConfig(
            image="boot.img",
            descriptor=DescriptorType.HASH,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="testkey",
            partition_name="boot",
        )
        issues = validate_partition("boot", config)
        assert any(i.error_code == "config.missing_partition_size" for i in issues)

    def test_hash_partition_size_not_multiple_of_4096(self) -> None:
        config = PartitionConfig(
            image="boot.img",
            descriptor=DescriptorType.HASH,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="testkey",
            partition_name="boot",
            partition_size=4097,
        )
        issues = validate_partition("boot", config)
        assert any(i.error_code == "config.invalid_partition_size" for i in issues)

    def test_dynamic_with_calc_max_conflict(self) -> None:
        config = PartitionConfig(
            image="boot.img",
            descriptor=DescriptorType.HASH,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="testkey",
            partition_name="boot",
            dynamic_partition_size=True,
            calc_max_image_size=True,
        )
        issues = validate_partition("boot", config)
        assert any(i.error_code == "config.invalid_option_combination" for i in issues)

    def test_valid_hashtree(self) -> None:
        config = PartitionConfig(
            image="system.img",
            descriptor=DescriptorType.HASHTREE,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="testkey",
            partition_name="system",
        )
        issues = validate_partition("system", config)
        assert len(issues) == 0

    def test_valid_vbmeta_with_includes(self) -> None:
        config = PartitionConfig(
            image="vbmeta.img",
            descriptor=DescriptorType.VBMETA,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="testkey",
            partition_name="vbmeta",
            included_partitions=("boot",),
        )
        issues = validate_partition("vbmeta", config)
        assert len(issues) == 0

    def test_valid_vbmeta_with_chain(self) -> None:
        config = PartitionConfig(
            image="vbmeta.img",
            descriptor=DescriptorType.VBMETA,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="testkey",
            partition_name="vbmeta",
            chain_partitions=("vbmeta_system:1:system_key.pem",),
        )
        issues = validate_partition("vbmeta", config)
        assert len(issues) == 0

    def test_invalid_chain_partition_format(self) -> None:
        config = PartitionConfig(
            image="vbmeta.img",
            descriptor=DescriptorType.VBMETA,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="testkey",
            partition_name="vbmeta",
            chain_partitions=("malformed",),
        )
        issues = validate_partition("vbmeta", config)
        assert any(i.error_code == "config.invalid_chain_partition" for i in issues)

    def test_chain_partition_zero_slot(self) -> None:
        config = PartitionConfig(
            image="vbmeta.img",
            descriptor=DescriptorType.VBMETA,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="testkey",
            partition_name="vbmeta",
            chain_partitions=("vbmeta_system:0:system_key.pem",),
        )
        issues = validate_partition("vbmeta", config)
        assert any(i.error_code == "config.invalid_chain_partition" for i in issues)

    def test_duplicate_chain_slots(self) -> None:
        config = PartitionConfig(
            image="vbmeta.img",
            descriptor=DescriptorType.VBMETA,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="testkey",
            partition_name="vbmeta",
            chain_partitions=(
                "vbmeta_system:1:sys_pub.bin",
                "vbmeta_vendor:1:vendor_pub.bin",
            ),
        )
        issues = validate_partition("vbmeta", config)
        assert any(i.error_code == "config.duplicate_rollback_slot" for i in issues)

    def test_empty_image(self) -> None:
        config = PartitionConfig(
            image="",
            descriptor=DescriptorType.HASH,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="testkey",
            partition_name="boot",
        )
        issues = validate_partition("boot", config)
        assert any(i.error_code == "config.missing_image" for i in issues)

    def test_empty_key_id(self) -> None:
        config = PartitionConfig(
            image="boot.img",
            descriptor=DescriptorType.HASH,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="",
            partition_name="boot",
        )
        issues = validate_partition("boot", config)
        assert any(i.error_code == "config.key_missing" for i in issues)

    def test_empty_partition_name(self) -> None:
        config = PartitionConfig(
            image="boot.img",
            descriptor=DescriptorType.HASH,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="testkey",
            partition_name="",
        )
        issues = validate_partition("boot", config)
        assert any(i.error_code == "config.missing_partition_name" for i in issues)

    def test_vbmeta_no_contents(self) -> None:
        config = PartitionConfig(
            image="vbmeta.img",
            descriptor=DescriptorType.VBMETA,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="testkey",
            partition_name="vbmeta",
        )
        issues = validate_partition("vbmeta", config)
        assert any(i.error_code == "config.vbmeta_no_contents" for i in issues)

    def test_hashtree_invalid_block_size(self) -> None:
        config = PartitionConfig(
            image="system.img",
            descriptor=DescriptorType.HASHTREE,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="testkey",
            partition_name="system",
            block_size=0,
        )
        issues = validate_partition("system", config)
        assert any(i.error_code == "config.invalid_block_size" for i in issues)

    def test_hashtree_non_power_of_two(self) -> None:
        config = PartitionConfig(
            image="system.img",
            descriptor=DescriptorType.HASHTREE,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="testkey",
            partition_name="system",
            block_size=3000,
        )
        issues = validate_partition("system", config)
        assert any(i.error_code == "config.invalid_block_size" for i in issues)

    def test_hashtree_valid_block_sizes(self) -> None:
        config = PartitionConfig(
            image="system.img",
            descriptor=DescriptorType.HASHTREE,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="testkey",
            partition_name="system",
            block_size=4096,
        )
        issues = validate_partition("system", config)
        assert len(issues) == 0

    def test_hashtree_invalid_fec_num_roots(self) -> None:
        config = PartitionConfig(
            image="system.img",
            descriptor=DescriptorType.HASHTREE,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="testkey",
            partition_name="system",
            fec_num_roots=1,
        )
        issues = validate_partition("system", config)
        assert any(i.error_code == "config.invalid_fec_num_roots" for i in issues)

    def test_hashtree_valid_fec_num_roots(self) -> None:
        config = PartitionConfig(
            image="system.img",
            descriptor=DescriptorType.HASHTREE,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="testkey",
            partition_name="system",
            fec_num_roots=10,
        )
        issues = validate_partition("system", config)
        assert len(issues) == 0

    def test_persistent_digest_requires_no_ab(self) -> None:
        config = PartitionConfig(
            image="boot.img",
            descriptor=DescriptorType.HASH,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="testkey",
            partition_name="boot",
            partition_size=4096,
            use_persistent_digest=True,
        )
        issues = validate_partition("boot", config)
        assert any(i.error_code == "config.invalid_option_combination" for i in issues)

    def test_persistent_digest_with_no_ab_ok(self) -> None:
        config = PartitionConfig(
            image="boot.img",
            descriptor=DescriptorType.HASH,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="testkey",
            partition_name="boot",
            partition_size=4096,
            use_persistent_digest=True,
            do_not_use_ab=True,
        )
        issues = validate_partition("boot", config)
        assert len(issues) == 0

    def test_valid_none_hash_without_key(self) -> None:
        config = PartitionConfig(
            image="dtbo.img",
            descriptor=DescriptorType.HASH,
            algorithm=SigningAlgorithm.NONE,
            key_id="",
            partition_name="dtbo",
            partition_size=4194304,
        )
        issues = validate_partition("dtbo", config)
        assert len(issues) == 0

    def test_valid_none_hashtree_without_key(self) -> None:
        config = PartitionConfig(
            image="system.img",
            descriptor=DescriptorType.HASHTREE,
            algorithm=SigningAlgorithm.NONE,
            key_id="",
            partition_name="system",
        )
        issues = validate_partition("system", config)
        assert len(issues) == 0

    def test_valid_none_vbmeta_with_contents(self) -> None:
        config = PartitionConfig(
            image="vbmeta.img",
            descriptor=DescriptorType.VBMETA,
            algorithm=SigningAlgorithm.NONE,
            key_id="",
            partition_name="vbmeta",
            included_partitions=("boot",),
        )
        issues = validate_partition("vbmeta", config)
        assert len(issues) == 0

    def test_none_vbmeta_still_requires_contents(self) -> None:
        config = PartitionConfig(
            image="vbmeta.img",
            descriptor=DescriptorType.VBMETA,
            algorithm=SigningAlgorithm.NONE,
            key_id="",
            partition_name="vbmeta",
        )
        issues = validate_partition("vbmeta", config)
        assert any(i.error_code == "config.vbmeta_no_contents" for i in issues)


# ---------------------------------------------------------------------------
# Key manifest validation
# ---------------------------------------------------------------------------


class TestValidateKeyManifest:
    def test_valid_manifest(self) -> None:
        manifest = {
            "testkey": {
                "private_key": "testkey.pem",
                "public_key": "testkey_pub.bin",
            }
        }
        issues = validate_key_manifest(manifest)
        assert len(issues) == 0

    def test_empty_manifest(self) -> None:
        issues = validate_key_manifest({})
        assert any(i.error_code == "keys.empty_manifest" for i in issues)

    def test_missing_private_key(self) -> None:
        manifest = {
            "testkey": {
                "public_key": "testkey_pub.bin",
            }
        }
        issues = validate_key_manifest(manifest)
        assert any(i.error_code == "keys.missing_private_key" for i in issues)

    def test_empty_private_key(self) -> None:
        manifest = {
            "testkey": {
                "private_key": "",
            }
        }
        issues = validate_key_manifest(manifest)
        assert any(i.error_code == "keys.empty_private_key" for i in issues)

    def test_non_dict_entry(self) -> None:
        manifest = {
            "testkey": "invalid"  # type: ignore[dict-item]
        }
        issues = validate_key_manifest(manifest)
        assert any(i.error_code == "keys.invalid_entry" for i in issues)

    def test_multiple_keys(self) -> None:
        manifest = {
            "key1": {"private_key": "key1.pem"},
            "key2": {"private_key": "key2.pem", "public_key": "key2_pub.bin"},
        }
        issues = validate_key_manifest(manifest)
        assert len(issues) == 0
