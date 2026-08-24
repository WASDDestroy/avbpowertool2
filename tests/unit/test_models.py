"""Tests for domain models."""

from __future__ import annotations

import pytest

from avbpowertool.domain.models import (
    AvbProfile,
    DescriptorType,
    ImageInspection,
    KeyRef,
    OperationIssue,
    PartitionConfig,
    SigningAlgorithm,
    SigningPlan,
    SigningStep,
)


class TestDescriptorType:
    def test_from_avbtool_label_hash(self) -> None:
        assert DescriptorType.from_avbtool_label("Hash descriptor") == DescriptorType.HASH

    def test_from_avbtool_label_hashtree(self) -> None:
        assert DescriptorType.from_avbtool_label("Hashtree descriptor") == DescriptorType.HASHTREE

    def test_from_avbtool_label_chain_partition(self) -> None:
        assert DescriptorType.from_avbtool_label("Chain Partition descriptor") == DescriptorType.VBMETA

    def test_from_avbtool_label_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown descriptor label"):
            DescriptorType.from_avbtool_label("Kernel Cmdline descriptor")

    def test_values(self) -> None:
        assert DescriptorType.HASH.value == "hash"
        assert DescriptorType.HASHTREE.value == "hashtree"
        assert DescriptorType.VBMETA.value == "vbmeta"


class TestSigningAlgorithm:
    def test_from_str_valid(self) -> None:
        assert SigningAlgorithm.from_str("SHA256_RSA4096") == SigningAlgorithm.SHA256_RSA4096
        assert SigningAlgorithm.from_str("none") == SigningAlgorithm.NONE

    def test_from_str_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown signing algorithm"):
            SigningAlgorithm.from_str("UNKNOWN_ALG")

    def test_all_values(self) -> None:
        for member in SigningAlgorithm:
            assert SigningAlgorithm.from_str(member.value) == member


class TestPartitionConfig:
    def test_frozen(self) -> None:
        p = PartitionConfig(
            image="boot.img",
            descriptor=DescriptorType.HASH,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="testkey",
            partition_name="boot",
        )
        with pytest.raises(AttributeError):
            p.image = "other.img"  # type: ignore[misc]

    def test_defaults(self) -> None:
        p = PartitionConfig(
            image="boot.img",
            descriptor=DescriptorType.HASH,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="testkey",
            partition_name="boot",
        )
        assert p.rollback_index == 0
        assert p.salt == ""
        assert p.flags == 0
        assert p.props == ()
        assert p.included_partitions == ()
        assert p.chain_partitions == ()
        assert p.block_size == 4096
        assert p.partition_size == 0
        assert p.dynamic_partition_size is False

    def test_with_props(self) -> None:
        p = PartitionConfig(
            image="boot.img",
            descriptor=DescriptorType.HASH,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="testkey",
            partition_name="boot",
            props=(("key1", "val1"), ("key2", "val2")),
        )
        assert p.props == (("key1", "val1"), ("key2", "val2"))


class TestAvbProfile:
    def test_frozen(self) -> None:
        profile = AvbProfile(id="test", name="Test")
        with pytest.raises(AttributeError):
            profile.id = "other"  # type: ignore[misc]

    def test_defaults(self) -> None:
        profile = AvbProfile(id="test", name="Test")
        assert profile.schema_version == 3
        assert profile.key_store_path == "keys"
        assert profile.partitions == {}

    def test_with_partitions(self) -> None:
        p = PartitionConfig(
            image="boot.img",
            descriptor=DescriptorType.HASH,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="testkey",
            partition_name="boot",
        )
        profile = AvbProfile(id="test", name="Test", partitions={"boot": p})
        assert "boot" in profile.partitions
        assert profile.partitions["boot"].image == "boot.img"


class TestOperationIssue:
    def test_creation(self) -> None:
        issue = OperationIssue(error_code="test.error", message="Something went wrong")
        assert issue.error_code == "test.error"
        assert issue.message == "Something went wrong"

    def test_frozen(self) -> None:
        issue = OperationIssue(error_code="test.error", message="msg")
        with pytest.raises(AttributeError):
            issue.error_code = "other"  # type: ignore[misc]


class TestSigningStep:
    def test_creation(self) -> None:
        step = SigningStep(
            partition_name="boot",
            operation="add_hash_footer",
            command=("add_hash_footer", "--image", "boot.img"),
            input_path="/images/boot.img",
            output_path="/staging/boot.img",
            order=0,
        )
        assert step.partition_name == "boot"
        assert step.order == 0
        assert "add_hash_footer" in step.command

    def test_frozen(self) -> None:
        step = SigningStep(
            partition_name="boot",
            operation="add_hash_footer",
            command=(),
            input_path="",
            output_path="",
            order=0,
        )
        with pytest.raises(AttributeError):
            step.order = 1  # type: ignore[misc]


class TestSigningPlan:
    def test_empty_plan(self) -> None:
        plan = SigningPlan(profile_id="test", steps=(), vbmeta_order=())
        assert plan.steps == ()
        assert plan.issues == ()

    def test_with_issues(self) -> None:
        issue = OperationIssue("test.error", "msg")
        plan = SigningPlan(
            profile_id="test",
            steps=(),
            vbmeta_order=(),
            issues=(issue,),
        )
        assert len(plan.issues) == 1


class TestKeyRef:
    def test_creation(self) -> None:
        ref = KeyRef(key_id="test", private_key_filename="test.pem")
        assert ref.key_id == "test"
        assert ref.public_key_filename is None
        assert ref.public_key_sha1 is None


class TestImageInspection:
    def test_minimal(self) -> None:
        insp = ImageInspection(image_name="boot", image_path="/images/boot.img")
        assert insp.image_name == "boot"
        assert insp.descriptor is None
        assert insp.props == ()

    def test_with_extensions(self) -> None:
        insp = ImageInspection(
            image_name="boot",
            image_path="/images/boot.img",
            raw_extensions=(("Custom Field", "value"),),
        )
        assert insp.raw_extensions == (("Custom Field", "value"),)
