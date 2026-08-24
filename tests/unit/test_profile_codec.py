"""Tests for profile codec — encode/decode round-trip."""

from __future__ import annotations

import pytest

from avbpowertool.domain.errors import ConfigError
from avbpowertool.domain.models import (
    AvbProfile,
    DescriptorType,
    PartitionConfig,
    SigningAlgorithm,
)
from avbpowertool.infrastructure.persistence.profile_codec import (
    decode_profile,
    encode_profile,
)


class TestEncodeProfile:
    def test_minimal_profile(self) -> None:
        profile = AvbProfile(id="test", name="Test")
        data = encode_profile(profile)
        assert data["schema_version"] == 2
        assert data["profile"]["id"] == "test"
        assert data["profile"]["name"] == "Test"
        assert data["key_store_path"] == "keys"
        assert data["partitions"] == {}

    def test_with_hash_partition(self) -> None:
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
                    rollback_index=3,
                    salt="abcdef",
                ),
            },
        )
        data = encode_profile(profile)
        boot = data["partitions"]["boot"]
        assert boot["image"] == "boot.img"
        assert boot["descriptor"] == "hash"
        assert boot["algorithm"] == "SHA256_RSA4096"
        assert boot["rollback_index"] == 3
        assert boot["salt"] == "abcdef"

    def test_with_props(self) -> None:
        profile = AvbProfile(
            id="test",
            name="Test",
            partitions={
                "boot": PartitionConfig(
                    image="boot.img",
                    descriptor=DescriptorType.HASH,
                    algorithm=SigningAlgorithm.SHA256_RSA4096,
                    key_id="k",
                    partition_name="boot",
                    props=(("key1", "val1"),),
                ),
            },
        )
        data = encode_profile(profile)
        assert data["partitions"]["boot"]["props"] == [["key1", "val1"]]

    def test_with_vbmeta(self) -> None:
        profile = AvbProfile(
            id="test",
            name="Test",
            partitions={
                "vbmeta": PartitionConfig(
                    image="vbmeta.img",
                    descriptor=DescriptorType.VBMETA,
                    algorithm=SigningAlgorithm.SHA256_RSA4096,
                    key_id="k",
                    partition_name="vbmeta",
                    included_partitions=("boot", "system"),
                ),
            },
        )
        data = encode_profile(profile)
        vb = data["partitions"]["vbmeta"]
        assert vb["included_partitions"] == ["boot", "system"]

    def test_deterministic_ordering(self) -> None:
        """Partitions should be sorted alphabetically."""
        profile = AvbProfile(
            id="test",
            name="Test",
            partitions={
                "vbmeta": PartitionConfig(
                    image="vbmeta.img",
                    descriptor=DescriptorType.VBMETA,
                    algorithm=SigningAlgorithm.SHA256_RSA4096,
                    key_id="k",
                    partition_name="vbmeta",
                    included_partitions=("boot",),
                ),
                "boot": PartitionConfig(
                    image="boot.img",
                    descriptor=DescriptorType.HASH,
                    algorithm=SigningAlgorithm.SHA256_RSA4096,
                    key_id="k",
                    partition_name="boot",
                ),
            },
        )
        data = encode_profile(profile)
        keys = list(data["partitions"].keys())
        assert keys == ["boot", "vbmeta"]


class TestDecodeProfile:
    def test_round_trip(self) -> None:
        original = AvbProfile(
            id="rt",
            name="Round Trip",
            partitions={
                "boot": PartitionConfig(
                    image="boot.img",
                    descriptor=DescriptorType.HASH,
                    algorithm=SigningAlgorithm.SHA256_RSA4096,
                    key_id="testkey",
                    partition_name="boot",
                    salt="abcdef",
                    props=(("k1", "v1"),),
                ),
                "system": PartitionConfig(
                    image="system.img",
                    descriptor=DescriptorType.HASHTREE,
                    algorithm=SigningAlgorithm.SHA512_RSA4096,
                    key_id="testkey",
                    partition_name="system",
                    data_block_size=512,
                    hash_block_size=512,
                ),
            },
        )
        encoded = encode_profile(original)
        decoded = decode_profile(encoded)
        assert decoded.id == original.id
        assert decoded.name == original.name
        assert decoded.schema_version == 2
        assert len(decoded.partitions) == 2
        boot = decoded.partitions["boot"]
        assert boot.descriptor == DescriptorType.HASH
        assert boot.salt == "abcdef"
        assert boot.props == (("k1", "v1"),)
        system = decoded.partitions["system"]
        assert system.descriptor == DescriptorType.HASHTREE
        assert system.data_block_size == 512

    def test_invalid_schema_version_raises(self) -> None:
        with pytest.raises(ConfigError, match="schema_version"):
            decode_profile({"schema_version": 1})

    def test_missing_profile_section_raises(self) -> None:
        with pytest.raises(ConfigError, match="profile"):
            decode_profile({"schema_version": 2})

    def test_missing_partitions_raises(self) -> None:
        with pytest.raises(ConfigError, match="partitions"):
            decode_profile({"schema_version": 2, "profile": {"id": "x", "name": "X"}})

    def test_unknown_descriptor_raises(self) -> None:
        data = {
            "schema_version": 2,
            "profile": {"id": "x", "name": "X"},
            "partitions": {
                "boot": {
                    "image": "boot.img",
                    "descriptor": "unknown",
                    "algorithm": "SHA256_RSA4096",
                    "key_id": "k",
                    "partition_name": "boot",
                }
            },
        }
        with pytest.raises(ConfigError, match="unknown descriptor"):
            decode_profile(data)

    def test_unknown_algorithm_raises(self) -> None:
        data = {
            "schema_version": 2,
            "profile": {"id": "x", "name": "X"},
            "partitions": {
                "boot": {
                    "image": "boot.img",
                    "descriptor": "hash",
                    "algorithm": "UNKNOWN",
                    "key_id": "k",
                    "partition_name": "boot",
                }
            },
        }
        with pytest.raises(ConfigError, match="unknown algorithm"):
            decode_profile(data)

    def test_props_as_dict(self) -> None:
        """Props stored as dict should be decoded to sorted tuple."""
        data = {
            "schema_version": 2,
            "profile": {"id": "x", "name": "X"},
            "partitions": {
                "boot": {
                    "image": "boot.img",
                    "descriptor": "hash",
                    "algorithm": "SHA256_RSA4096",
                    "key_id": "k",
                    "partition_name": "boot",
                    "props": {"b_key": "b_val", "a_key": "a_val"},
                }
            },
        }
        profile = decode_profile(data)
        assert profile.partitions["boot"].props == (("a_key", "a_val"), ("b_key", "b_val"))

    def test_sample_fixture_round_trip(self, sample_profile_v2: dict) -> None:
        """The sample profile fixture should round-trip."""
        profile = decode_profile(sample_profile_v2)
        re_encoded = encode_profile(profile)
        re_decoded = decode_profile(re_encoded)
        assert re_decoded.id == profile.id
        assert len(re_decoded.partitions) == len(profile.partitions)
