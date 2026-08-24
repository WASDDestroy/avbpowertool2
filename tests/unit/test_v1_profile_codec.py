"""Tests for the legacy (v1) profile codec."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from avbpowertool.domain.errors import ConfigError
from avbpowertool.domain.models import DescriptorType, SigningAlgorithm
from avbpowertool.infrastructure.persistence.v1_profile_codec import (
    V1_ARCHIVE_FLAG,
    V1_BATCH_FLAG,
    build_key_manifest,
    decode_v1_image_info,
    detect_v1_archive,
    extract_v1_archive,
    find_config_dir,
    find_keys_dir,
)

LEGACY_FIXTURES = Path(__file__).parent.parent / "fixtures" / "legacy"


def _load_sample() -> dict:
    with open(LEGACY_FIXTURES / "imageInfo.json", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# decode_v1_image_info
# ---------------------------------------------------------------------------


class TestDecodeV1ImageInfo:
    def test_hash_partition_mapping(self) -> None:
        profile, issues = decode_v1_image_info(_load_sample(), "zuxos")
        assert issues == []

        boot = profile.partitions["boot"]
        assert boot.image == "boot.img"
        assert boot.descriptor == DescriptorType.HASH
        assert boot.algorithm == SigningAlgorithm.SHA256_RSA4096
        assert boot.key_id == "testkey_rsa4096"
        assert boot.partition_name == "boot"
        assert boot.rollback_index == 1736035200
        assert boot.flags == 0
        assert boot.hash_algorithm == "sha256"
        assert boot.salt.startswith("c15f")
        props = dict(boot.props)
        assert props["com.android.build.boot.os_version"] == "14"

    def test_none_hash_partition_has_no_key(self) -> None:
        profile, issues = decode_v1_image_info(_load_sample(), "zuxos")
        assert issues == []

        dtbo = profile.partitions["dtbo"]
        assert dtbo.algorithm == SigningAlgorithm.NONE
        assert dtbo.key_id == ""
        assert dtbo.descriptor == DescriptorType.HASH

    def test_hashtree_partition_block_sizes(self) -> None:
        profile, _ = decode_v1_image_info(_load_sample(), "zuxos")
        system = profile.partitions["system"]
        assert system.descriptor == DescriptorType.HASHTREE
        assert system.block_size == 4096
        assert system.algorithm == SigningAlgorithm.NONE

    def test_vbmeta_partition_mapping(self) -> None:
        profile, issues = decode_v1_image_info(_load_sample(), "zuxos")
        assert issues == []

        vbmeta = profile.partitions["vbmeta"]
        assert vbmeta.descriptor == DescriptorType.VBMETA
        assert vbmeta.algorithm == SigningAlgorithm.SHA256_RSA4096
        assert vbmeta.key_id == "testkey_rsa4096"
        # Hash + Hashtree concatenated
        assert vbmeta.included_partitions == (
            "dtbo",
            "init_boot",
            "vendor_boot",
            "odm",
            "system_dlkm",
            "vendor",
            "vendor_dlkm",
        )
        # v1 partial triples completed with matching public keys
        assert vbmeta.chain_partitions == (
            "boot:3:testkey_rsa4096_pub.bin",
            "recovery:1:testkey_rsa4096_pub.bin",
            "vbmeta_system:2:testkey_rsa2048_pub.bin",
        )

    def test_vbmeta_system_partition(self) -> None:
        profile, issues = decode_v1_image_info(_load_sample(), "zuxos")
        assert issues == []

        vbmeta_system = profile.partitions["vbmeta_system"]
        assert vbmeta_system.descriptor == DescriptorType.VBMETA
        assert vbmeta_system.algorithm == SigningAlgorithm.SHA256_RSA2048
        assert vbmeta_system.included_partitions == (
            "pvmfw",
            "product",
            "system",
            "system_ext",
        )
        assert vbmeta_system.chain_partitions == ()

    def test_profile_metadata(self) -> None:
        profile, _ = decode_v1_image_info(_load_sample(), "zuxos")
        assert profile.id == "zuxos"
        assert profile.name == "zuxos"
        assert profile.schema_version == 3
        assert profile.key_store_path == "keys"
        assert len(profile.partitions) == 15

    def test_key_not_found_reports_issue(self) -> None:
        raw = {
            "boot": {
                "Algorithm": "SHA256_RSA4096",
                "Descriptor Type": "Hash",
                "Image File": "boot.img",
                "Partition Name": "boot",
                "Public key file": "NOT_FOUND",
                "Rollback Index": "0",
            }
        }
        profile, issues = decode_v1_image_info(raw, "x")
        assert profile.partitions["boot"].key_id == ""
        assert any(i.error_code == "import.legacy.key_not_found" for i in issues)

    def test_unknown_algorithm_falls_back_to_none(self) -> None:
        raw = {
            "boot": {
                "Algorithm": "SHA999_RSA999",
                "Descriptor Type": "Hash",
                "Image File": "boot.img",
                "Partition Name": "boot",
                "Rollback Index": "0",
            }
        }
        profile, issues = decode_v1_image_info(raw, "x")
        assert profile.partitions["boot"].algorithm == SigningAlgorithm.NONE
        assert any(i.error_code == "import.legacy.unsupported_algorithm" for i in issues)

    def test_partial_chain_reports_issue(self) -> None:
        raw = {
            "vbmeta": {
                "Algorithm": "SHA256_RSA4096",
                "Chain": ["boot:3:"],
                "Chain partition key": [],
                "Hash": [],
                "Hashtree": [],
                "Image File": "vbmeta.img",
                "Rollback Index": "0",
            }
        }
        profile, issues = decode_v1_image_info(raw, "x")
        assert profile.partitions["vbmeta"].chain_partitions == ("boot:3:",)
        assert any(i.error_code == "import.legacy.partial_chain" for i in issues)

    def test_invalid_entry_reports_issue(self) -> None:
        profile, issues = decode_v1_image_info({"bad": "not-a-dict"}, "x")  # type: ignore[dict-item]
        assert profile.partitions == {}
        assert any(i.error_code == "import.legacy.invalid_entry" for i in issues)

    def test_descriptor_detection_heuristic(self) -> None:
        raw = {
            "myvbmeta_img": {
                "Algorithm": "NONE",
                "Image File": "myvbmeta.img",
                "Hash": ["boot"],
                "Rollback Index": "0",
            }
        }
        profile, _ = decode_v1_image_info(raw, "x")
        assert profile.partitions["myvbmeta_img"].descriptor == DescriptorType.VBMETA


# ---------------------------------------------------------------------------
# build_key_manifest
# ---------------------------------------------------------------------------


class TestBuildKeyManifest:
    def test_from_fixture_keys(self) -> None:
        keys_dir = LEGACY_FIXTURES / "keys"
        manifest, issues = build_key_manifest(keys_dir, keys_dir / "keyCache.cache")
        assert issues == []
        assert set(manifest.keys()) == {"testkey_rsa2048", "testkey_rsa4096"}
        assert manifest["testkey_rsa4096"]["private_key"] == "testkey_rsa4096.pem"
        assert manifest["testkey_rsa4096"]["public_key"] == "testkey_rsa4096_pub.bin"
        assert (
            manifest["testkey_rsa4096"]["public_key_sha1"]
            == "2597c218aae470a130f61162feaae70afd97f011"
        )
        assert (
            manifest["testkey_rsa2048"]["public_key_sha1"]
            == "cdbb77177f731920bbe0a0f94f84d9038ae0617d"
        )

    def test_missing_key_cache(self, tmp_path: Path) -> None:
        keys_dir = tmp_path / "keys"
        keys_dir.mkdir()
        (keys_dir / "a.pem").write_text("k", encoding="utf-8")
        manifest, issues = build_key_manifest(keys_dir)
        assert issues == []
        assert manifest == {"a": {"private_key": "a.pem"}}


# ---------------------------------------------------------------------------
# Archive detection / extraction
# ---------------------------------------------------------------------------


def _make_v1_zip(path: Path, *, batch: bool = False) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Configs/demo/imageInfo.json", json.dumps({"boot": {"Image File": "boot.img"}}))
        zf.writestr("Keys/demo/keyCache.cache", "test.pem, abc123\n")
        zf.writestr("Keys/demo/test.pem", "dummy")
        flag = V1_BATCH_FLAG if batch else V1_ARCHIVE_FLAG
        zf.writestr(flag, "x")


class TestDetectV1Archive:
    def test_single_by_flag(self, tmp_path: Path) -> None:
        p = tmp_path / "c.zip"
        _make_v1_zip(p)
        assert detect_v1_archive(p) == "single"

    def test_batch_by_flag(self, tmp_path: Path) -> None:
        p = tmp_path / "c.zip"
        _make_v1_zip(p, batch=True)
        assert detect_v1_archive(p) == "batch"

    def test_none_for_plain_zip(self, tmp_path: Path) -> None:
        p = tmp_path / "plain.zip"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("foo.txt", "x")
        assert detect_v1_archive(p) == "none"

    def test_none_for_missing_file(self, tmp_path: Path) -> None:
        assert detect_v1_archive(tmp_path / "missing.zip") == "none"


class TestExtractV1Archive:
    def test_extract_and_locate(self, tmp_path: Path) -> None:
        archive = tmp_path / "demo.zip"
        _make_v1_zip(archive)
        staging = tmp_path / "staging"
        root = extract_v1_archive(archive, staging)
        config_dir = find_config_dir(root)
        assert config_dir.name == "demo"
        assert (config_dir / "imageInfo.json").is_file()
        keys_dir = find_keys_dir(root)
        assert keys_dir is not None
        assert keys_dir.name == "demo"

    def test_rejects_batch(self, tmp_path: Path) -> None:
        archive = tmp_path / "batch.zip"
        _make_v1_zip(archive, batch=True)
        with pytest.raises(ConfigError) as exc:
            extract_v1_archive(archive, tmp_path / "staging")
        assert exc.value.error_code == "import.legacy.batch_not_supported"

    def test_rejects_path_traversal(self, tmp_path: Path) -> None:
        archive = tmp_path / "evil.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../../evil.txt", "x")
            zf.writestr(V1_ARCHIVE_FLAG, "x")
        with pytest.raises(ConfigError) as exc:
            extract_v1_archive(archive, tmp_path / "staging")
        assert exc.value.error_code == "config.invalid_archive"
