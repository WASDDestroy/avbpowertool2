"""Tests for SigningPlanBuilder (pure planner, zero writes)."""

from __future__ import annotations

import json
from pathlib import Path

from avbpowertool.domain.models import (
    AvbProfile,
    DescriptorType,
    OperationIssue,
    PartitionConfig,
    SigningAlgorithm,
)
from avbpowertool.domain.signing_plan import SigningPlanBuilder


def _make_profile() -> AvbProfile:
    return AvbProfile(
        id="test",
        name="Test Profile",
        partitions={
            "boot": PartitionConfig(
                image="boot.img",
                descriptor=DescriptorType.HASH,
                algorithm=SigningAlgorithm.SHA256_RSA4096,
                key_id="testkey_rsa4096",
                partition_name="boot",
                rollback_index=0,
                salt="a1b2c3d4e5f6",
            ),
            "system": PartitionConfig(
                image="system.img",
                descriptor=DescriptorType.HASHTREE,
                algorithm=SigningAlgorithm.SHA256_RSA4096,
                key_id="testkey_rsa4096",
                partition_name="system",
                rollback_index=0,
                data_block_size=4096,
                hash_block_size=4096,
            ),
            "vbmeta": PartitionConfig(
                image="vbmeta.img",
                descriptor=DescriptorType.VBMETA,
                algorithm=SigningAlgorithm.SHA256_RSA4096,
                key_id="testkey_rsa4096",
                partition_name="vbmeta",
                rollback_index=0,
                included_partitions=("boot",),
            ),
        },
    )


def _setup_workspace(ws: Path) -> None:
    """Create image and key files in the workspace."""
    profile_dir = ws / "profiles" / "current"
    key_dir = profile_dir / "keys"
    image_dir = ws / "Images"
    staging_dir = ws / ".avbpowertool-staging"

    image_dir.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)
    key_dir.mkdir(parents=True, exist_ok=True)

    # Create image files
    (image_dir / "boot.img").write_bytes(b"fake boot image")
    (image_dir / "system.img").write_bytes(b"fake system image")

    # Create key files
    (key_dir / "testkey_rsa4096.pem").write_text("fake key", encoding="utf-8")

    # Create manifest
    manifest = {
        "testkey_rsa4096": {
            "private_key": "testkey_rsa4096.pem",
            "public_key": "testkey_rsa4096_pub.bin",
        }
    }
    (key_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    # Create profile.json
    profile = _make_profile()
    profile_dict = {
        "schema_version": profile.schema_version,
        "profile": {"id": profile.id, "name": profile.name},
        "key_store_path": profile.key_store_path,
        "partitions": {},
    }
    (profile_dir / "profile.json").write_text(
        json.dumps(profile_dict), encoding="utf-8"
    )


class TestSigningPlanBuilder:
    def test_builds_hash_step(self, tmp_path: Path) -> None:
        _setup_workspace(tmp_path)
        profile = _make_profile()
        image_dir = tmp_path / "Images"
        key_dir = tmp_path / "profiles" / "current" / "keys"
        staging_dir = tmp_path / ".avbpowertool-staging"

        builder = SigningPlanBuilder(profile, image_dir, key_dir, staging_dir)
        plan = builder.build(("boot",))

        assert len(plan.steps) == 1
        step = plan.steps[0]
        assert step.partition_name == "boot"
        assert step.operation == "add_hash_footer"
        assert "--partition_name" in step.command
        assert "--salt" in step.command
        assert step.order == 0

    def test_builds_hashtree_step(self, tmp_path: Path) -> None:
        _setup_workspace(tmp_path)
        profile = _make_profile()
        image_dir = tmp_path / "Images"
        key_dir = tmp_path / "profiles" / "current" / "keys"
        staging_dir = tmp_path / ".avbpowertool-staging"

        builder = SigningPlanBuilder(profile, image_dir, key_dir, staging_dir)
        plan = builder.build(("system",))

        assert len(plan.steps) == 1
        step = plan.steps[0]
        assert step.partition_name == "system"
        assert step.operation == "add_hashtree_footer"
        assert "--data_block_size" in step.command
        assert "--hash_block_size" in step.command

    def test_builds_vbmeta_step(self, tmp_path: Path) -> None:
        _setup_workspace(tmp_path)
        profile = _make_profile()
        image_dir = tmp_path / "Images"
        key_dir = tmp_path / "profiles" / "current" / "keys"
        staging_dir = tmp_path / ".avbpowertool-staging"

        builder = SigningPlanBuilder(profile, image_dir, key_dir, staging_dir)
        plan = builder.build(("vbmeta",))

        assert len(plan.steps) == 1
        step = plan.steps[0]
        assert step.partition_name == "vbmeta"
        assert step.operation == "make_vbmeta_image"
        assert any("--include_descriptors_from_image" in c for c in step.command)

    def test_vbmeta_ordering(self, tmp_path: Path) -> None:
        _setup_workspace(tmp_path)
        profile = _make_profile()
        image_dir = tmp_path / "Images"
        key_dir = tmp_path / "profiles" / "current" / "keys"
        staging_dir = tmp_path / ".avbpowertool-staging"

        builder = SigningPlanBuilder(profile, image_dir, key_dir, staging_dir)
        plan = builder.build(("boot", "system", "vbmeta"))

        # Non-vbmeta come first, then vbmeta
        assert len(plan.steps) == 3
        operations = [s.operation for s in plan.steps]
        assert operations == ["add_hash_footer", "add_hashtree_footer", "make_vbmeta_image"]
        assert plan.vbmeta_order == ("vbmeta",)

    def test_missing_partition_reports_issue(self, tmp_path: Path) -> None:
        _setup_workspace(tmp_path)
        profile = _make_profile()
        image_dir = tmp_path / "Images"
        key_dir = tmp_path / "profiles" / "current" / "keys"
        staging_dir = tmp_path / ".avbpowertool-staging"

        builder = SigningPlanBuilder(profile, image_dir, key_dir, staging_dir)
        plan = builder.build(("nonexistent",))

        assert len(plan.steps) == 0
        assert any(i.error_code == "config.partition_missing" for i in plan.issues)

    def test_missing_image_reports_issue(self, tmp_path: Path) -> None:
        _setup_workspace(tmp_path)
        profile = _make_profile()
        # Delete the image file
        (tmp_path / "Images" / "boot.img").unlink()

        image_dir = tmp_path / "Images"
        key_dir = tmp_path / "profiles" / "current" / "keys"
        staging_dir = tmp_path / ".avbpowertool-staging"

        builder = SigningPlanBuilder(profile, image_dir, key_dir, staging_dir)
        plan = builder.build(("boot",))

        assert len(plan.steps) == 0
        assert any(i.error_code == "image.not_found" for i in plan.issues)

    def test_missing_key_manifest_reports_issue(self, tmp_path: Path) -> None:
        _setup_workspace(tmp_path)
        profile = _make_profile()
        # Delete manifest
        (tmp_path / "profiles" / "current" / "keys" / "manifest.json").unlink()

        image_dir = tmp_path / "Images"
        key_dir = tmp_path / "profiles" / "current" / "keys"
        staging_dir = tmp_path / ".avbpowertool-staging"

        builder = SigningPlanBuilder(profile, image_dir, key_dir, staging_dir)
        plan = builder.build(("boot",))

        assert len(plan.steps) == 0
        assert any(i.error_code == "keys.manifest_not_found" for i in plan.issues)

    def test_missing_key_in_manifest_reports_issue(self, tmp_path: Path) -> None:
        _setup_workspace(tmp_path)
        profile = _make_profile()
        # Overwrite manifest with a key that doesn't match
        manifest = {"other_key": {"private_key": "other.pem"}}
        (tmp_path / "profiles" / "current" / "keys" / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

        image_dir = tmp_path / "Images"
        key_dir = tmp_path / "profiles" / "current" / "keys"
        staging_dir = tmp_path / ".avbpowertool-staging"

        builder = SigningPlanBuilder(profile, image_dir, key_dir, staging_dir)
        plan = builder.build(("boot",))

        assert len(plan.steps) == 0
        assert any(i.error_code == "config.key_missing" for i in plan.issues)

    def test_missing_key_file_reports_issue(self, tmp_path: Path) -> None:
        _setup_workspace(tmp_path)
        profile = _make_profile()
        # Delete the key file but keep manifest
        (tmp_path / "profiles" / "current" / "keys" / "testkey_rsa4096.pem").unlink()

        image_dir = tmp_path / "Images"
        key_dir = tmp_path / "profiles" / "current" / "keys"
        staging_dir = tmp_path / ".avbpowertool-staging"

        builder = SigningPlanBuilder(profile, image_dir, key_dir, staging_dir)
        plan = builder.build(("boot",))

        assert len(plan.steps) == 0
        assert any(i.error_code == "config.key_missing" for i in plan.issues)

    def test_issues_are_operation_issue_instances(self, tmp_path: Path) -> None:
        _setup_workspace(tmp_path)
        profile = _make_profile()
        image_dir = tmp_path / "Images"
        key_dir = tmp_path / "profiles" / "current" / "keys"
        staging_dir = tmp_path / ".avbpowertool-staging"

        builder = SigningPlanBuilder(profile, image_dir, key_dir, staging_dir)
        plan = builder.build(("nonexistent",))

        for iss in plan.issues:
            assert isinstance(iss, OperationIssue)

    def test_deterministic_ordering(self, tmp_path: Path) -> None:
        """Non-vbmeta steps should be alphabetical."""
        _setup_workspace(tmp_path)
        profile = AvbProfile(
            id="test",
            name="Test",
            partitions={
                "init_boot": PartitionConfig(
                    image="init_boot.img",
                    descriptor=DescriptorType.HASH,
                    algorithm=SigningAlgorithm.SHA256_RSA4096,
                    key_id="testkey_rsa4096",
                    partition_name="init_boot",
                ),
                "boot": PartitionConfig(
                    image="boot.img",
                    descriptor=DescriptorType.HASH,
                    algorithm=SigningAlgorithm.SHA256_RSA4096,
                    key_id="testkey_rsa4096",
                    partition_name="boot",
                ),
            },
        )
        (tmp_path / "Images" / "init_boot.img").write_bytes(b"fake init_boot image")

        image_dir = tmp_path / "Images"
        key_dir = tmp_path / "profiles" / "current" / "keys"
        staging_dir = tmp_path / ".avbpowertool-staging"

        builder = SigningPlanBuilder(profile, image_dir, key_dir, staging_dir)
        plan = builder.build(("boot", "init_boot"))

        # Alphabetical: boot before init_boot
        assert plan.steps[0].partition_name == "boot"
        assert plan.steps[1].partition_name == "init_boot"

    def test_props_in_command(self, tmp_path: Path) -> None:
        _setup_workspace(tmp_path)
        profile = AvbProfile(
            id="test",
            name="Test",
            partitions={
                "boot": PartitionConfig(
                    image="boot.img",
                    descriptor=DescriptorType.HASH,
                    algorithm=SigningAlgorithm.SHA256_RSA4096,
                    key_id="testkey_rsa4096",
                    partition_name="boot",
                    props=(("android.boot.vbmeta.digest", "sha256_of_vbmeta"),),
                ),
            },
        )

        image_dir = tmp_path / "Images"
        key_dir = tmp_path / "profiles" / "current" / "keys"
        staging_dir = tmp_path / ".avbpowertool-staging"

        builder = SigningPlanBuilder(profile, image_dir, key_dir, staging_dir)
        plan = builder.build(("boot",))

        assert len(plan.steps) == 1
        cmd = plan.steps[0].command
        assert "--prop" in cmd
        prop_idx = cmd.index("--prop")
        assert cmd[prop_idx + 1] == "android.boot.vbmeta.digest:sha256_of_vbmeta"
