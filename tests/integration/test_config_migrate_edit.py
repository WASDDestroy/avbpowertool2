"""Integration tests for config migrate and config edit use cases."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from avbpowertool.application.commands import (
    ConfigEditRequest,
    ConfigMigrateRequest,
)
from avbpowertool.application.services.manage_configs import (
    ConfigEditUseCase,
    ConfigMigrateUseCase,
)
from avbpowertool.domain.models import AvbProfile, DescriptorType, PartitionConfig, SigningAlgorithm
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.persistence.profile_codec import encode_profile
from avbpowertool.infrastructure.persistence.profile_repository import ProfileRepository
from tests.conftest import sample_profile_v2  # noqa: F401


def _setup_workspace(tmp_path: Path) -> WorkspacePaths:
    ws = WorkspacePaths.discover(tmp_path)
    ws.ensure_dirs()
    return ws


def _write_profile_json(ws: WorkspacePaths, profile_id: str, data: dict) -> None:
    profile_dir = ws.resolve_profile_dir(profile_id)
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "keys").mkdir(exist_ok=True)
    (profile_dir / "profile.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


class TestConfigMigrateUseCase:
    def test_migrates_v2_profile_on_disk(self, tmp_path: Path, sample_profile_v2: dict) -> None:
        ws = _setup_workspace(tmp_path)
        _write_profile_json(ws, "legacy", sample_profile_v2)

        uc = ConfigMigrateUseCase(ws)
        result = uc.execute(ConfigMigrateRequest(profile_id="legacy"))

        assert result.migrated is True
        assert result.issues == ()

        on_disk = json.loads(
            (ws.resolve_profile_dir("legacy") / "profile.json").read_text(encoding="utf-8")
        )
        assert on_disk["schema_version"] == 3
        # v2 block-size fields are gone (block_size==4096 default is omitted)
        assert "data_block_size" not in on_disk["partitions"]["system"]
        assert "hash_block_size" not in on_disk["partitions"]["system"]

        # Repository can load the migrated file
        profile = ProfileRepository(ws).load("legacy")
        assert profile.schema_version == 3
        assert profile.partitions["system"].block_size == 4096

    def test_migrated_with_block_size_conflict_issue(
        self, tmp_path: Path, sample_profile_v2: dict
    ) -> None:
        ws = _setup_workspace(tmp_path)
        sample_profile_v2["partitions"]["system"]["data_block_size"] = 512
        _write_profile_json(ws, "legacy", sample_profile_v2)

        uc = ConfigMigrateUseCase(ws)
        result = uc.execute(ConfigMigrateRequest(profile_id="legacy"))

        assert result.migrated is True
        assert any(
            i.error_code == "migrate.v2_to_v3.block_size_conflict" for i in result.issues
        )

    def test_v3_profile_is_not_rewritten(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        profile = AvbProfile(id="modern", name="Modern")
        _write_profile_json(ws, "modern", encode_profile(profile))

        uc = ConfigMigrateUseCase(ws)
        result = uc.execute(ConfigMigrateRequest(profile_id="modern"))

        assert result.migrated is False
        assert result.issues == ()

    def test_nonexistent_profile(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        uc = ConfigMigrateUseCase(ws)
        result = uc.execute(ConfigMigrateRequest(profile_id="ghost"))
        assert any(i.error_code == "config.not_found" for i in result.issues)

    def test_unsupported_schema_version(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        _write_profile_json(ws, "weird", {"schema_version": 99, "profile": {}})
        uc = ConfigMigrateUseCase(ws)
        result = uc.execute(ConfigMigrateRequest(profile_id="weird"))
        assert any(i.error_code == "config.invalid_schema_version" for i in result.issues)


class TestConfigEditUseCase:
    def _profile_with_partitions(self) -> AvbProfile:
        return AvbProfile(
            id="current",
            name="Current",
            partitions={
                "boot": PartitionConfig(
                    image="boot.img",
                    descriptor=DescriptorType.HASH,
                    algorithm=SigningAlgorithm.SHA256_RSA4096,
                    key_id="testkey_rsa4096",
                    partition_name="boot",
                    partition_size=67108864,
                ),
                "system": PartitionConfig(
                    image="system.img",
                    descriptor=DescriptorType.HASHTREE,
                    algorithm=SigningAlgorithm.SHA256_RSA4096,
                    key_id="testkey_rsa4096",
                    partition_name="system",
                    block_size=4096,
                ),
            },
        )

    def _save(self, ws: WorkspacePaths, profile: AvbProfile) -> None:
        repo = ProfileRepository(ws)
        profile_dir = ws.resolve_profile_dir(profile.id)
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / "keys").mkdir(exist_ok=True)
        repo.save(profile)

    def test_edit_int_field(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        self._save(ws, self._profile_with_partitions())

        uc = ConfigEditUseCase(ws)
        result = uc.execute(
            ConfigEditRequest(
                partition_name="boot",
                updates={"partition_size": "1048576"},
            )
        )
        assert result.issues == ()

        profile = ProfileRepository(ws).load("current")
        assert profile.partitions["boot"].partition_size == 1048576

    def test_edit_bool_and_tuple_fields(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        self._save(ws, self._profile_with_partitions())

        uc = ConfigEditUseCase(ws)
        result = uc.execute(
            ConfigEditRequest(
                partition_name="boot",
                updates={
                    "use_persistent_digest": "true",
                    "do_not_use_ab": "yes",
                    "kernel_cmdlines": "a=1,b=2",
                },
            )
        )
        assert result.issues == ()

        boot = ProfileRepository(ws).load("current").partitions["boot"]
        assert boot.use_persistent_digest is True
        assert boot.do_not_use_ab is True
        assert boot.kernel_cmdlines == ("a=1", "b=2")

    def test_unknown_field_rejected(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        self._save(ws, self._profile_with_partitions())

        uc = ConfigEditUseCase(ws)
        result = uc.execute(
            ConfigEditRequest(partition_name="boot", updates={"nonexistent": "1"})
        )
        assert any(i.error_code == "config.invalid_field" for i in result.issues)

    def test_missing_partition(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        self._save(ws, self._profile_with_partitions())

        uc = ConfigEditUseCase(ws)
        result = uc.execute(
            ConfigEditRequest(partition_name="vendor", updates={"flags": "0"})
        )
        assert any(i.error_code == "config.partition_missing" for i in result.issues)

    def test_bad_int_value_rejected(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        self._save(ws, self._profile_with_partitions())

        uc = ConfigEditUseCase(ws)
        result = uc.execute(
            ConfigEditRequest(partition_name="boot", updates={"flags": "not-an-int"})
        )
        assert any(i.error_code == "config.invalid_field" for i in result.issues)
