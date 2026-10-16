"""Integration tests for config migrate and config edit use cases."""

from __future__ import annotations

import json
from pathlib import Path

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


def _setup_workspace(tmp_path: Path) -> WorkspacePaths:
    ws = WorkspacePaths.discover(tmp_path)
    ws.ensure_dirs()
    return ws


def _write_profile_json(ws: WorkspacePaths, profile_id: str, data: dict) -> None:
    profile_dir = ws.resolve_profile_dir(profile_id)
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "keys").mkdir(exist_ok=True)
    (profile_dir / "profile.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


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
        assert any(i.error_code == "migrate.v2_to_v3.block_size_conflict" for i in result.issues)

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
        result = uc.execute(ConfigEditRequest(partition_name="boot", updates={"nonexistent": "1"}))
        assert any(i.error_code == "config.invalid_field" for i in result.issues)

    def test_missing_partition(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        self._save(ws, self._profile_with_partitions())

        uc = ConfigEditUseCase(ws)
        result = uc.execute(ConfigEditRequest(partition_name="vendor", updates={"flags": "0"}))
        assert any(i.error_code == "config.partition_missing" for i in result.issues)

    def test_bad_int_value_rejected(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        self._save(ws, self._profile_with_partitions())

        uc = ConfigEditUseCase(ws)
        result = uc.execute(
            ConfigEditRequest(partition_name="boot", updates={"flags": "not-an-int"})
        )
        assert any(i.error_code == "config.invalid_field" for i in result.issues)

    # ------------------------------------------------------------------
    # P0-2: key_id / algorithm / image / props
    # ------------------------------------------------------------------

    def _profile_with_tuple_fields(self) -> AvbProfile:
        return AvbProfile(
            id="current",
            name="Current",
            partitions={
                "vbmeta": PartitionConfig(
                    image="vbmeta.img",
                    descriptor=DescriptorType.VBMETA,
                    algorithm=SigningAlgorithm.SHA256_RSA4096,
                    key_id="testkey_rsa4096",
                    partition_name="vbmeta",
                    flags=1,
                    salt="a1b2c3d4",
                    use_persistent_digest=True,
                    chain_partitions=("boot:3:old_boot.pem.bin", "recovery:1:rec.pem.bin"),
                    included_partitions=("boot", "odm"),
                ),
            },
        )

    def _profile_json_path(self, ws: WorkspacePaths) -> Path:
        return ws.resolve_profile_dir("current") / "profile.json"

    def test_set_key_id_and_algorithm(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        self._save(ws, self._profile_with_partitions())

        uc = ConfigEditUseCase(ws)
        result = uc.execute(
            ConfigEditRequest(
                partition_name="boot",
                updates={"key_id": "testkey_rsa2048", "algorithm": "SHA256_RSA2048"},
            )
        )
        assert result.issues == ()

        boot = ProfileRepository(ws).load("current").partitions["boot"]
        assert boot.key_id == "testkey_rsa2048"
        assert boot.algorithm is SigningAlgorithm.SHA256_RSA2048

    def test_set_key_id_to_empty_string(self, tmp_path: Path) -> None:
        """``NONE`` partitions need no key, so an empty key_id is legal."""
        ws = _setup_workspace(tmp_path)
        self._save(ws, self._profile_with_partitions())

        uc = ConfigEditUseCase(ws)
        result = uc.execute(
            ConfigEditRequest(partition_name="boot", updates={"key_id": "", "algorithm": "NONE"})
        )
        assert result.issues == ()

        boot = ProfileRepository(ws).load("current").partitions["boot"]
        assert boot.key_id == ""
        assert boot.algorithm is SigningAlgorithm.NONE

    def test_invalid_algorithm_rejected_without_writing(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        self._save(ws, self._profile_with_partitions())
        profile_path = self._profile_json_path(ws)
        before = profile_path.read_bytes()

        uc = ConfigEditUseCase(ws)
        result = uc.execute(
            ConfigEditRequest(partition_name="boot", updates={"algorithm": "SHA256_MD5"})
        )
        assert any(i.error_code == "config.invalid_algorithm" for i in result.issues)
        assert profile_path.read_bytes() == before

    def test_image_must_end_with_img(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        self._save(ws, self._profile_with_partitions())
        profile_path = self._profile_json_path(ws)
        before = profile_path.read_bytes()

        uc = ConfigEditUseCase(ws)
        rejected = uc.execute(
            ConfigEditRequest(partition_name="boot", updates={"image": "boot.bin"})
        )
        assert any(i.error_code == "config.invalid_field" for i in rejected.issues)
        assert profile_path.read_bytes() == before

        accepted = uc.execute(
            ConfigEditRequest(partition_name="boot", updates={"image": "boot_new.img"})
        )
        assert accepted.issues == ()
        assert ProfileRepository(ws).load("current").partitions["boot"].image == "boot_new.img"

    def test_set_props_splits_on_first_colon(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        self._save(ws, self._profile_with_partitions())

        uc = ConfigEditUseCase(ws)
        result = uc.execute(
            ConfigEditRequest(
                partition_name="boot",
                updates={"props": "KEY:VALUE,KEY2:VALUE:WITH:COLON"},
            )
        )
        assert result.issues == ()

        boot = ProfileRepository(ws).load("current").partitions["boot"]
        assert boot.props == (("KEY", "VALUE"), ("KEY2", "VALUE:WITH:COLON"))

    def test_set_props_with_empty_key_rejected(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        self._save(ws, self._profile_with_partitions())
        profile_path = self._profile_json_path(ws)
        before = profile_path.read_bytes()

        uc = ConfigEditUseCase(ws)
        result = uc.execute(
            ConfigEditRequest(partition_name="boot", updates={"props": ":VALUE"})
        )
        assert any(i.error_code == "config.invalid_field" for i in result.issues)
        assert profile_path.read_bytes() == before

    # ------------------------------------------------------------------
    # P0-2: --unset
    # ------------------------------------------------------------------

    def test_unset_resets_each_field_type(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        self._save(ws, self._profile_with_tuple_fields())

        uc = ConfigEditUseCase(ws)
        result = uc.execute(
            ConfigEditRequest(
                partition_name="vbmeta",
                unset=("salt", "flags", "use_persistent_digest", "included_partitions"),
            )
        )
        assert result.issues == ()

        vbmeta = ProfileRepository(ws).load("current").partitions["vbmeta"]
        assert vbmeta.salt == ""  # str -> ""
        assert vbmeta.flags == 0  # int -> 0
        assert vbmeta.use_persistent_digest is False  # bool -> False
        assert vbmeta.included_partitions == ()  # tuple -> ()

    def test_unset_unknown_field_rejected(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        self._save(ws, self._profile_with_partitions())
        profile_path = self._profile_json_path(ws)
        before = profile_path.read_bytes()

        uc = ConfigEditUseCase(ws)
        result = uc.execute(ConfigEditRequest(partition_name="boot", unset=("nonexistent",)))
        assert any(i.error_code == "config.invalid_field" for i in result.issues)
        assert profile_path.read_bytes() == before

    # ------------------------------------------------------------------
    # P0-2: --append / --remove
    # ------------------------------------------------------------------

    def test_append_included_partitions_accumulates_in_order(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        self._save(ws, self._profile_with_tuple_fields())

        uc = ConfigEditUseCase(ws)
        result = uc.execute(
            ConfigEditRequest(
                partition_name="vbmeta",
                appends=(("included_partitions", "dtbo"), ("included_partitions", "vendor_boot")),
            )
        )
        assert result.issues == ()

        vbmeta = ProfileRepository(ws).load("current").partitions["vbmeta"]
        assert vbmeta.included_partitions == ("boot", "odm", "dtbo", "vendor_boot")

    def test_append_chain_partition_replaces_same_name_in_place(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        self._save(ws, self._profile_with_tuple_fields())

        uc = ConfigEditUseCase(ws)
        result = uc.execute(
            ConfigEditRequest(
                partition_name="vbmeta",
                appends=(("chain_partitions", "boot:4:new_boot.pem.bin"),),
            )
        )
        assert result.issues == ()

        chains = ProfileRepository(ws).load("current").partitions["vbmeta"].chain_partitions
        assert len(chains) == 2  # replaced, not duplicated
        assert chains[0] == "boot:4:new_boot.pem.bin"  # position preserved
        assert chains[1] == "recovery:1:rec.pem.bin"

    def test_append_chain_partition_appends_new_name(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        self._save(ws, self._profile_with_tuple_fields())

        uc = ConfigEditUseCase(ws)
        result = uc.execute(
            ConfigEditRequest(
                partition_name="vbmeta",
                appends=(("chain_partitions", "vbmeta_system:2:sys.pem.bin"),),
            )
        )
        assert result.issues == ()

        chains = ProfileRepository(ws).load("current").partitions["vbmeta"].chain_partitions
        assert chains == (
            "boot:3:old_boot.pem.bin",
            "recovery:1:rec.pem.bin",
            "vbmeta_system:2:sys.pem.bin",
        )

    def test_append_props_single_pair(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        self._save(ws, self._profile_with_partitions())

        uc = ConfigEditUseCase(ws)
        result = uc.execute(
            ConfigEditRequest(
                partition_name="boot",
                appends=(("props", "android.boot.vbmeta.digest:abc:def"),),
            )
        )
        assert result.issues == ()

        boot = ProfileRepository(ws).load("current").partitions["boot"]
        assert boot.props == (("android.boot.vbmeta.digest", "abc:def"),)

    def test_remove_chain_partition_by_bare_name(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        self._save(ws, self._profile_with_tuple_fields())

        uc = ConfigEditUseCase(ws)
        result = uc.execute(
            ConfigEditRequest(partition_name="vbmeta", removes=(("chain_partitions", "boot"),))
        )
        assert result.issues == ()

        vbmeta = ProfileRepository(ws).load("current").partitions["vbmeta"]
        assert vbmeta.chain_partitions == ("recovery:1:rec.pem.bin",)

    def test_remove_chain_partition_by_full_triple(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        self._save(ws, self._profile_with_tuple_fields())

        uc = ConfigEditUseCase(ws)
        result = uc.execute(
            ConfigEditRequest(
                partition_name="vbmeta",
                removes=(("chain_partitions", "recovery:1:rec.pem.bin"),),
            )
        )
        assert result.issues == ()

        vbmeta = ProfileRepository(ws).load("current").partitions["vbmeta"]
        assert vbmeta.chain_partitions == ("boot:3:old_boot.pem.bin",)

    def test_remove_included_partition_by_full_value(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        self._save(ws, self._profile_with_tuple_fields())

        uc = ConfigEditUseCase(ws)
        result = uc.execute(
            ConfigEditRequest(partition_name="vbmeta", removes=(("included_partitions", "odm"),))
        )
        assert result.issues == ()

        vbmeta = ProfileRepository(ws).load("current").partitions["vbmeta"]
        assert vbmeta.included_partitions == ("boot",)

    def test_remove_then_append_same_field(self, tmp_path: Path) -> None:
        """Removes are applied before appends within one request."""
        ws = _setup_workspace(tmp_path)
        self._save(ws, self._profile_with_tuple_fields())

        uc = ConfigEditUseCase(ws)
        result = uc.execute(
            ConfigEditRequest(
                partition_name="vbmeta",
                removes=(("chain_partitions", "recovery"),),
                appends=(("chain_partitions", "vbmeta_system:2:sys.pem.bin"),),
            )
        )
        assert result.issues == ()

        chains = ProfileRepository(ws).load("current").partitions["vbmeta"].chain_partitions
        assert chains == ("boot:3:old_boot.pem.bin", "vbmeta_system:2:sys.pem.bin")

    def test_set_and_append_same_field_conflict(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        self._save(ws, self._profile_with_tuple_fields())
        profile_path = self._profile_json_path(ws)
        before = profile_path.read_bytes()

        uc = ConfigEditUseCase(ws)
        result = uc.execute(
            ConfigEditRequest(
                partition_name="vbmeta",
                updates={"included_partitions": "boot"},
                appends=(("included_partitions", "dtbo"),),
            )
        )
        assert any(i.error_code == "config.invalid_option_combination" for i in result.issues)
        assert profile_path.read_bytes() == before

    def test_unset_and_remove_same_field_conflict(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        self._save(ws, self._profile_with_tuple_fields())
        profile_path = self._profile_json_path(ws)
        before = profile_path.read_bytes()

        uc = ConfigEditUseCase(ws)
        result = uc.execute(
            ConfigEditRequest(
                partition_name="vbmeta",
                unset=("chain_partitions",),
                removes=(("chain_partitions", "boot"),),
            )
        )
        assert any(i.error_code == "config.invalid_option_combination" for i in result.issues)
        assert profile_path.read_bytes() == before

    def test_append_on_scalar_field_rejected(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        self._save(ws, self._profile_with_tuple_fields())
        profile_path = self._profile_json_path(ws)
        before = profile_path.read_bytes()

        uc = ConfigEditUseCase(ws)
        result = uc.execute(
            ConfigEditRequest(partition_name="vbmeta", appends=(("flags", "1"),))
        )
        assert any(i.error_code == "config.invalid_field" for i in result.issues)
        assert profile_path.read_bytes() == before

    def test_remove_on_scalar_field_rejected(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        self._save(ws, self._profile_with_tuple_fields())

        uc = ConfigEditUseCase(ws)
        result = uc.execute(
            ConfigEditRequest(partition_name="vbmeta", removes=(("key_id", "testkey_rsa4096"),))
        )
        assert any(i.error_code == "config.invalid_field" for i in result.issues)

    def test_append_invalid_chain_item_rejected(self, tmp_path: Path) -> None:
        ws = _setup_workspace(tmp_path)
        self._save(ws, self._profile_with_tuple_fields())
        profile_path = self._profile_json_path(ws)
        before = profile_path.read_bytes()

        uc = ConfigEditUseCase(ws)
        result = uc.execute(
            ConfigEditRequest(partition_name="vbmeta", appends=(("chain_partitions", "   "),))
        )
        assert any(i.error_code == "config.invalid_field" for i in result.issues)
        assert profile_path.read_bytes() == before
