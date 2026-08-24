"""Tests for v2 -> v3 profile migration."""

from __future__ import annotations

from avbpowertool.infrastructure.persistence.v2_to_v3 import (
    V3_SCHEMA_VERSION,
    migrate_v2_to_v3,
)


def _v2_profile(**overrides: object) -> dict:
    data: dict = {
        "schema_version": 2,
        "profile": {"id": "test", "name": "Test"},
        "key_store_path": "keys",
        "partitions": {
            "boot": {
                "image": "boot.img",
                "descriptor": "hash",
                "algorithm": "SHA256_RSA4096",
                "key_id": "k",
                "partition_name": "boot",
                "kernel_cmdline": "androidboot.avb.test=1",
            },
            "system": {
                "image": "system.img",
                "descriptor": "hashtree",
                "algorithm": "SHA256_RSA4096",
                "key_id": "k",
                "partition_name": "system",
                "data_block_size": 4096,
                "hash_block_size": 4096,
            },
        },
    }
    data.update(overrides)  # type: ignore[arg-type]
    return data


class TestMigrateV2ToV3:
    def test_schema_version_bumped(self) -> None:
        migrated, issues = migrate_v2_to_v3(_v2_profile())
        assert migrated["schema_version"] == V3_SCHEMA_VERSION == 3
        assert issues == []

    def test_does_not_mutate_input(self) -> None:
        data = _v2_profile()
        before = {k: (list(v) if isinstance(v, list) else v) for k, v in data.items()}
        migrate_v2_to_v3(data)
        assert data["schema_version"] == 2
        assert "block_size" not in data["partitions"]["system"]
        assert before["partitions"] == data["partitions"]

    def test_block_sizes_collapse(self) -> None:
        migrated, issues = migrate_v2_to_v3(_v2_profile())
        system = migrated["partitions"]["system"]
        assert system["block_size"] == 4096
        assert "data_block_size" not in system
        assert "hash_block_size" not in system
        assert issues == []

    def test_block_size_conflict_warns(self) -> None:
        data = _v2_profile()
        data["partitions"]["system"]["data_block_size"] = 512
        data["partitions"]["system"]["hash_block_size"] = 4096
        migrated, issues = migrate_v2_to_v3(data)
        assert migrated["partitions"]["system"]["block_size"] == 512
        assert len(issues) == 1
        assert issues[0].error_code == "migrate.v2_to_v3.block_size_conflict"

    def test_kernel_cmdline_becomes_list(self) -> None:
        migrated, _ = migrate_v2_to_v3(_v2_profile())
        boot = migrated["partitions"]["boot"]
        assert boot["kernel_cmdlines"] == ["androidboot.avb.test=1"]
        assert "kernel_cmdline" not in boot

    def test_only_data_block_size_migrates(self) -> None:
        data = _v2_profile()
        data["partitions"]["system"].pop("hash_block_size")
        migrated, issues = migrate_v2_to_v3(data)
        assert migrated["partitions"]["system"]["block_size"] == 4096
        assert issues == []

    def test_absent_partitions_ok(self) -> None:
        data = _v2_profile()
        del data["partitions"]
        migrated, issues = migrate_v2_to_v3(data)
        assert migrated["schema_version"] == 3
        assert issues == []
