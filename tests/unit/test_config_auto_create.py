"""Tests for the auto-mode config generation use case and its builders."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from avbpowertool.application.commands import (
    ChainKeyResolution,
    ConfigAutoCreateRequest,
    ConfigCreateFromImagesRequest,
    ConfigCreateFromImagesResult,
    ConfigValidateRequest,
)
from avbpowertool.application.ports import AvbToolResult
from avbpowertool.application.services.config_auto_create import (
    ConfigAutoCreateUseCase,
    ConfigCreateFromImagesUseCase,
    apply_chain_resolutions,
    build_auto_partition,
    finalize_vbmeta_includes,
    select_key_for_algorithm,
)
from avbpowertool.application.services.manage_configs import ConfigValidateUseCase
from avbpowertool.domain.models import (
    ChainDescriptor,
    DescriptorType,
    ImageInspection,
    PartitionConfig,
    SigningAlgorithm,
)
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.persistence.profile_repository import (
    ProfileRepository,
)
from tests.conftest import AVBTOOL_OUTPUT_DIR, FakeAvbTool

SAMPLE_HASH = (AVBTOOL_OUTPUT_DIR / "hash_descriptor.txt").read_text(encoding="utf-8")
SAMPLE_HASHTREE = (AVBTOOL_OUTPUT_DIR / "hashtree_descriptor.txt").read_text(encoding="utf-8")
SAMPLE_VBMETA_WITH_DESCS = (AVBTOOL_OUTPUT_DIR / "vbmeta_with_descriptors.txt").read_text(
    encoding="utf-8"
)
SAMPLE_VBMETA_WITH_CHAIN = (AVBTOOL_OUTPUT_DIR / "vbmeta_with_chain.txt").read_text(
    encoding="utf-8"
)
SAMPLE_NO_FOOTER = (
    "usage: avbtool info_image ...\n"
    "avbtool.py: error: Given image does not look like a vbmeta image.\n"
)


def _inspection(**overrides: object) -> ImageInspection:
    data: dict = dict(
        image_name="boot",
        image_path="/img/boot.img",
        descriptor=DescriptorType.HASH,
        algorithm="NONE",
        partition_name="boot",
        rollback_index="3",
        rollback_index_location="2",
        salt="a1b2c3d4e5f6",
        hash_algorithm="sha256",
        digest="d1e2f3",
        flags="2",
        props=(("android.boot.test", "1"),),
        raw_extensions=(),
    )
    data.update(overrides)  # type: ignore[arg-type]
    return ImageInspection(**data)  # type: ignore[arg-type]


class TestBuildAutoPartition:
    def test_reads_full_metadata(self, tmp_path: Path) -> None:
        (tmp_path / "boot.img").write_bytes(b"x" * 5000)
        config = build_auto_partition(_inspection(), tmp_path)

        assert config is not None
        assert config.image == "boot.img"
        assert config.partition_name == "boot"
        # rollback index / location
        assert config.rollback_index == 3
        assert config.rollback_index_location == 2
        # salt / hash algorithm / props
        assert config.salt == "a1b2c3d4e5f6"
        assert config.hash_algorithm == "sha256"
        assert config.props == (("android.boot.test", "1"),)
        # signing algorithm from the header (NONE -> unsigned)
        assert config.algorithm == SigningAlgorithm.NONE
        # flags integer + flag-bit shortcuts (flags=2 -> VERIFICATION_DISABLED)
        assert config.flags == 2
        assert config.set_hashtree_disabled_flag is False
        assert config.set_verification_disabled_flag is True
        # partition size = image size rounded up to 4096
        assert config.partition_size == 8192

    def test_signed_algorithm_mapped(self, tmp_path: Path) -> None:
        config = build_auto_partition(_inspection(algorithm="SHA256_RSA4096"), tmp_path)
        assert config is not None
        assert config.algorithm == SigningAlgorithm.SHA256_RSA4096

    def test_key_id_defaults_and_param(self, tmp_path: Path) -> None:
        default = build_auto_partition(_inspection(), tmp_path)
        assert default is not None
        assert default.key_id == "default"

        chosen = build_auto_partition(_inspection(), tmp_path, key_id="release")
        assert chosen is not None
        assert chosen.key_id == "release"

    def test_flag_bits(self, tmp_path: Path) -> None:
        config = build_auto_partition(_inspection(flags="3"), tmp_path)
        assert config is not None
        assert config.flags == 3
        assert config.set_hashtree_disabled_flag is True
        assert config.set_verification_disabled_flag is True

    def test_hash_algorithm_clamped(self, tmp_path: Path) -> None:
        config = build_auto_partition(_inspection(hash_algorithm="foobar"), tmp_path)
        assert config is not None
        assert config.hash_algorithm == "sha256"

    def test_hash_algorithm_missing_defaults(self, tmp_path: Path) -> None:
        config = build_auto_partition(_inspection(hash_algorithm=None), tmp_path)
        assert config is not None
        assert config.hash_algorithm == "sha256"

    def test_hashtree_hash_algorithm_read(self, tmp_path: Path) -> None:
        config = build_auto_partition(
            _inspection(
                descriptor=DescriptorType.HASHTREE,
                hash_algorithm="sha512",
                partition_name="system",
                image_name="system",
            ),
            tmp_path,
        )
        assert config is not None
        assert config.hash_algorithm == "sha512"

    def test_vbmeta_keeps_defaults_and_hashtree_flag(self, tmp_path: Path) -> None:
        config = build_auto_partition(
            _inspection(
                descriptor=DescriptorType.VBMETA,
                image_name="vbmeta",
                partition_name="vbmeta",
                flags="1",
            ),
            tmp_path,
        )
        assert config is not None
        # vbmeta has no hash algorithm concept; default kept
        assert config.hash_algorithm == "sha256"
        assert config.set_hashtree_disabled_flag is True
        assert config.set_verification_disabled_flag is False

    def test_none_descriptor_returns_none(self, tmp_path: Path) -> None:
        inspection = ImageInspection(
            image_name="raw",
            image_path="/img/raw.img",
            descriptor=None,
        )
        assert build_auto_partition(inspection, tmp_path) is None

    def test_empty_values_fall_back(self, tmp_path: Path) -> None:
        config = build_auto_partition(
            _inspection(
                rollback_index=None,
                rollback_index_location=None,
                salt=None,
                flags=None,
                props=(),
            ),
            tmp_path,
        )
        assert config is not None
        assert config.rollback_index == 0
        assert config.rollback_index_location == 0
        assert config.salt == ""
        assert config.flags == 0
        assert config.props == ()


def _config(image: str, partition: str, descriptor: DescriptorType) -> PartitionConfig:
    return PartitionConfig(
        image=image,
        descriptor=descriptor,
        algorithm=SigningAlgorithm.SHA256_RSA4096,
        key_id="default",
        partition_name=partition,
    )


class TestFinalizeVbmetaIncludes:
    def test_uses_real_includes_limited_to_scan(self) -> None:
        by_image = {
            "boot.img": _config("boot.img", "boot", DescriptorType.HASH),
            "dtbo.img": _config("dtbo.img", "dtbo", DescriptorType.HASH),
            "vbmeta.img": _config("vbmeta.img", "vbmeta", DescriptorType.VBMETA),
        }
        included = {"vbmeta.img": ("dtbo", "odm", "init_boot")}
        partitions = finalize_vbmeta_includes(by_image, included)
        vbmeta = next(p for p in partitions if p.partition_name == "vbmeta")
        # "odm"/"init_boot" are not in the scan -> dropped
        assert vbmeta.included_partitions == ("dtbo",)

    def test_falls_back_to_other_scanned_partitions(self) -> None:
        by_image = {
            "boot.img": _config("boot.img", "boot", DescriptorType.HASH),
            "system.img": _config("system.img", "system", DescriptorType.HASHTREE),
            "vbmeta.img": _config("vbmeta.img", "vbmeta", DescriptorType.VBMETA),
        }
        partitions = finalize_vbmeta_includes(by_image, {})
        vbmeta = next(p for p in partitions if p.partition_name == "vbmeta")
        assert vbmeta.included_partitions == ("boot", "system")

    def test_fallback_excludes_other_vbmeta(self) -> None:
        by_image = {
            "boot.img": _config("boot.img", "boot", DescriptorType.HASH),
            "vbmeta.img": _config("vbmeta.img", "vbmeta", DescriptorType.VBMETA),
            "vbmeta_system.img": _config(
                "vbmeta_system.img", "vbmeta_system", DescriptorType.VBMETA
            ),
        }
        partitions = finalize_vbmeta_includes(by_image, {})
        vbmeta = next(p for p in partitions if p.partition_name == "vbmeta")
        assert vbmeta.included_partitions == ("boot",)
        vbmeta_system = next(p for p in partitions if p.partition_name == "vbmeta_system")
        assert vbmeta_system.included_partitions == ("boot",)

    def test_no_image_entries_are_lost(self) -> None:
        """Every scanned image keeps its own entry (regression for the
        vbmeta.img overwriting the real dtbo.img entry bug)."""
        by_image = {
            "boot.img": _config("boot.img", "boot", DescriptorType.HASH),
            "dtbo.img": _config("dtbo.img", "dtbo", DescriptorType.HASH),
            "vbmeta.img": _config("vbmeta.img", "vbmeta", DescriptorType.VBMETA),
            "vbmeta_system.img": _config(
                "vbmeta_system.img", "vbmeta_system", DescriptorType.VBMETA
            ),
        }
        partitions = finalize_vbmeta_includes(by_image, {"vbmeta.img": ("dtbo",)})
        names = {p.partition_name for p in partitions}
        assert names == {"boot", "dtbo", "vbmeta", "vbmeta_system"}
        # the real dtbo.img config keeps its own image file
        dtbo = next(p for p in partitions if p.partition_name == "dtbo")
        assert dtbo.image == "dtbo.img"

    def test_no_fallback_keeps_pruned_empty_includes(self) -> None:
        """allow_fallback=False keeps the filtered (empty) tuple instead of
        filling the vbmeta with every other scanned partition."""
        by_image = {
            "boot.img": _config("boot.img", "boot", DescriptorType.HASH),
            "vbmeta.img": _config("vbmeta.img", "vbmeta", DescriptorType.VBMETA),
        }
        # Every embedded descriptor names a partition outside the scan.
        included = {"vbmeta.img": ("odm", "init_boot")}

        fallback = finalize_vbmeta_includes(dict(by_image), included)
        vbmeta_fallback = next(p for p in fallback if p.partition_name == "vbmeta")
        assert vbmeta_fallback.included_partitions == ("boot",)

        strict = finalize_vbmeta_includes(dict(by_image), included, allow_fallback=False)
        vbmeta_strict = next(p for p in strict if p.partition_name == "vbmeta")
        assert vbmeta_strict.included_partitions == ()


class TestApplyChainResolutions:
    def test_writes_resolved_entries_into_vbmeta_config(self) -> None:
        by_image = {
            "vbmeta.img": _config("vbmeta.img", "vbmeta", DescriptorType.VBMETA),
            "boot.img": _config("boot.img", "boot", DescriptorType.HASH),
        }
        chains = {
            "vbmeta.img": (
                ChainDescriptor("vbmeta_system", "1", "a" * 40),
                ChainDescriptor("vbmeta_vendor", "2", "b" * 40),
            )
        }
        resolutions = (
            ChainKeyResolution(entry="vbmeta_system:1:key.pem", key_id="k1"),
            ChainKeyResolution(entry="vbmeta_vendor:2:other.pem", key_id="k2"),
        )
        result = apply_chain_resolutions(by_image, chains, resolutions)
        vbmeta = result["vbmeta.img"]
        assert vbmeta.chain_partitions == (
            "vbmeta_system:1:key.pem",
            "vbmeta_vendor:2:other.pem",
        )

    def test_unresolved_entries_are_skipped(self) -> None:
        by_image = {
            "vbmeta.img": _config("vbmeta.img", "vbmeta", DescriptorType.VBMETA),
        }
        chains = {"vbmeta.img": (ChainDescriptor("vbmeta_system", "1", "a" * 40),)}
        resolutions = (ChainKeyResolution(entry=""),)
        result = apply_chain_resolutions(by_image, chains, resolutions)
        assert result["vbmeta.img"].chain_partitions == ()

    def test_no_chain_images_unchanged(self) -> None:
        by_image = {
            "boot.img": _config("boot.img", "boot", DescriptorType.HASH),
        }
        result = apply_chain_resolutions(by_image, {}, ())
        assert result["boot.img"].chain_partitions == ()


class TestSelectKeyForAlgorithm:
    def test_rsa2048_algorithm_prefers_2048_key(self) -> None:
        assert (
            select_key_for_algorithm("SHA256_RSA2048", ["key_2048", "key_4096"], "default")
            == "key_2048"
        )

    def test_rsa4096_algorithm_prefers_4096_key(self) -> None:
        assert (
            select_key_for_algorithm("SHA256_RSA4096", ["key_2048", "key_4096"], "default")
            == "key_4096"
        )

    def test_no_matching_key_falls_back_to_default(self) -> None:
        assert select_key_for_algorithm("SHA256_RSA4096", ["key_2048"], "default") == "default"

    def test_none_algorithm_falls_back_to_default(self) -> None:
        assert select_key_for_algorithm(None, ["key_2048", "key_4096"], "default") == "default"


class PerImageFakeAvbTool(FakeAvbTool):
    """FakeAvbTool answering ``inspect_image`` per image file stem."""

    def __init__(self, outputs: dict[str, AvbToolResult]) -> None:
        super().__init__()
        self._outputs = outputs

    def _record(self, name: str, args: tuple, kwargs: dict) -> AvbToolResult:
        if name == "inspect_image" and args[0].stem in self._outputs:
            self.calls.append((name, args, kwargs))
            return self._outputs[args[0].stem]
        return super()._record(name, args, kwargs)


def _make_workspace(tmp_path: Path) -> WorkspacePaths:
    ws = WorkspacePaths(
        root=tmp_path,
        images=tmp_path / "Images",
        profiles=tmp_path / "profiles",
        logs=tmp_path / "Logs",
        staging=tmp_path / ".avbpowertool-staging",
        avbtool_script=tmp_path / "avbtool.py",
    )
    ws.ensure_dirs()
    return ws


def _ok(stdout: str) -> AvbToolResult:
    return AvbToolResult(0, stdout, "", "info_image")


class TestConfigAutoCreateUseCase:
    def test_single_image_builds_one_partition(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        (ws.images / "boot.img").write_bytes(b"x" * 8192)
        avb = PerImageFakeAvbTool({"boot": _ok(SAMPLE_HASH)})

        result = ConfigAutoCreateUseCase(ws, avb).execute(
            ConfigAutoCreateRequest(image_dir=ws.images)
        )

        assert result.scanned_images == ("boot",)
        assert result.skipped_images == ()
        assert result.issues == ()
        assert result.chain_issues == ()
        assert [p.partition_name for p in result.partitions] == ["boot"]
        assert result.partitions[0].image == "boot.img"
        assert result.partitions[0].partition_size == 8192

    def test_vbmeta_includes_are_pruned_to_the_scan(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        (ws.images / "boot.img").write_bytes(b"x" * 4096)
        (ws.images / "vbmeta.img").write_bytes(b"x" * 4096)
        avb = PerImageFakeAvbTool(
            {"boot": _ok(SAMPLE_HASH), "vbmeta": _ok(SAMPLE_VBMETA_WITH_DESCS)}
        )

        result = ConfigAutoCreateUseCase(ws, avb).execute(
            ConfigAutoCreateRequest(image_dir=ws.images)
        )

        # vbmeta.img embeds dtbo/init_boot, neither of which was scanned
        assert result.scanned_images == ("boot", "vbmeta")
        by_name = {p.partition_name: p for p in result.partitions}
        assert set(by_name) == {"boot", "vbmeta"}
        assert by_name["vbmeta"].included_partitions == ("boot",)
        assert by_name["boot"].image == "boot.img"

    def test_image_names_filter_scans_only_the_subset(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        for name in ("boot", "dtbo", "vbmeta"):
            (ws.images / f"{name}.img").write_bytes(b"x" * 4096)
        avb = PerImageFakeAvbTool(
            {
                "boot": _ok(SAMPLE_HASH),
                "dtbo": _ok(SAMPLE_HASH),
                "vbmeta": _ok(SAMPLE_VBMETA_WITH_DESCS),
            }
        )

        result = ConfigAutoCreateUseCase(ws, avb).execute(
            ConfigAutoCreateRequest(image_dir=ws.images, image_names=("boot",))
        )

        assert result.scanned_images == ("boot",)
        assert [p.partition_name for p in result.partitions] == ["boot"]
        assert [call[1][0].stem for call in avb.calls] == ["boot"]

    def test_image_without_vbmeta_structure_is_skipped_with_issue(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        (ws.images / "boot.img").write_bytes(b"x" * 4096)
        (ws.images / "raw.img").write_bytes(b"raw")
        avb = PerImageFakeAvbTool(
            {
                "boot": _ok(SAMPLE_HASH),
                "raw": AvbToolResult(1, "", SAMPLE_NO_FOOTER, "info_image"),
            }
        )

        result = ConfigAutoCreateUseCase(ws, avb).execute(
            ConfigAutoCreateRequest(image_dir=ws.images)
        )

        assert result.scanned_images == ("boot", "raw")
        assert result.skipped_images == ("raw",)
        assert [p.partition_name for p in result.partitions] == ["boot"]
        assert [i.error_code for i in result.issues] == ["image.no_vbmeta_structure"]

    def test_allow_fallback_false_leaves_vbmeta_includes_empty(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        (ws.images / "boot.img").write_bytes(b"x" * 4096)
        (ws.images / "vbmeta.img").write_bytes(b"x" * 4096)
        avb = PerImageFakeAvbTool(
            {"boot": _ok(SAMPLE_HASH), "vbmeta": _ok(SAMPLE_VBMETA_WITH_DESCS)}
        )
        use_case = ConfigAutoCreateUseCase(ws, avb)

        with_fallback = use_case.execute(ConfigAutoCreateRequest(image_dir=ws.images))
        vbmeta = next(p for p in with_fallback.partitions if p.partition_name == "vbmeta")
        assert vbmeta.included_partitions == ("boot",)

        without_fallback = use_case.execute(
            ConfigAutoCreateRequest(image_dir=ws.images, allow_fallback=False)
        )
        vbmeta = next(p for p in without_fallback.partitions if p.partition_name == "vbmeta")
        assert vbmeta.included_partitions == ()

    def test_chain_issues_are_reported_separately(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        (ws.images / "vbmeta.img").write_bytes(b"x" * 4096)
        avb = PerImageFakeAvbTool({"vbmeta": _ok(SAMPLE_VBMETA_WITH_CHAIN)})

        result = ConfigAutoCreateUseCase(ws, avb).execute(
            ConfigAutoCreateRequest(image_dir=ws.images)
        )

        # No key store holds the chained public keys -> both chains unresolved.
        assert [i.error_code for i in result.chain_issues] == [
            "chain.key_not_found",
            "chain.key_not_found",
        ]
        assert result.issues == ()
        vbmeta = next(p for p in result.partitions if p.partition_name == "vbmeta")
        assert vbmeta.chain_partitions == ()

    def test_resolve_chains_false_skips_resolution(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        (ws.images / "vbmeta.img").write_bytes(b"x" * 4096)
        avb = PerImageFakeAvbTool({"vbmeta": _ok(SAMPLE_VBMETA_WITH_CHAIN)})

        result = ConfigAutoCreateUseCase(ws, avb).execute(
            ConfigAutoCreateRequest(image_dir=ws.images, resolve_chains=False)
        )

        assert result.chain_issues == ()
        assert not any(call[0] == "extract_public_key" for call in avb.calls)

    def test_key_id_override_wins(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        (ws.images / "boot.img").write_bytes(b"x" * 4096)
        avb = PerImageFakeAvbTool({"boot": _ok(SAMPLE_HASH)})

        result = ConfigAutoCreateUseCase(ws, avb).execute(
            ConfigAutoCreateRequest(
                image_dir=ws.images,
                key_id="explicit",
                available_keys=("key_4096",),
                default_key_id="key_4096",
            )
        )

        assert result.partitions[0].key_id == "explicit"

    def test_missing_directory_reports_issue(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        avb = FakeAvbTool()

        result = ConfigAutoCreateUseCase(ws, avb).execute(
            ConfigAutoCreateRequest(image_dir=tmp_path / "nope")
        )

        assert result.partitions == ()
        assert result.scanned_images == ()
        assert [i.error_code for i in result.issues] == ["config.auto_dir_not_found"]
        assert avb.calls == []

    def test_directory_without_images_returns_empty_result(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        (ws.images / "notes.txt").write_text("not an image", encoding="utf-8")
        avb = FakeAvbTool()

        result = ConfigAutoCreateUseCase(ws, avb).execute(
            ConfigAutoCreateRequest(image_dir=ws.images)
        )

        assert result.partitions == ()
        assert result.scanned_images == ()
        assert result.issues == ()
        assert avb.calls == []

    def test_hashtree_image_metadata(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        (ws.images / "system.img").write_bytes(b"x" * 4096)
        avb = PerImageFakeAvbTool({"system": _ok(SAMPLE_HASHTREE)})

        result = ConfigAutoCreateUseCase(ws, avb).execute(
            ConfigAutoCreateRequest(image_dir=ws.images)
        )

        assert [p.descriptor for p in result.partitions] == [DescriptorType.HASHTREE]


# ---------------------------------------------------------------------------
# ConfigCreateFromImagesUseCase
# ---------------------------------------------------------------------------

PUB_BLOB = b"\x30\x81\x89\x02\x01\x00fake-public-key-blob"
PUB_SHA1 = hashlib.sha1(PUB_BLOB).hexdigest()

#: A vbmeta image embedding exactly one descriptor, for the scanned ``boot``.
VBMETA_EMBEDDING_BOOT = """\
Footer version:           1.0
Image size:               4096 bytes
Algorithm:                SHA256_RSA4096
Rollback Index:           0
Flags:                    0
Rollback Index Location:  0
Release String:           'avbtool 1.3.0'
Descriptors:
    Hash descriptor:
      Image Size:            4194304 bytes
      Hash Algorithm:        sha256
      Partition Name:        boot
      Salt:                  aabbccddeeff
      Digest:                1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b
      Flags:                 0
"""

#: The two-chain fixture, with both chain public keys set to PUB_SHA1 so the
#: single pre-seeded key in the store resolves them.
CHAIN_OUTPUT = SAMPLE_VBMETA_WITH_CHAIN.replace("b" * 40, PUB_SHA1).replace("a" * 40, PUB_SHA1)


class WritingFakeAvbTool(PerImageFakeAvbTool):
    """Per-image fake whose ``extract_public_key`` writes a known blob."""

    def extract_public_key(self, key_path: Path, output_path: Path) -> AvbToolResult:
        self._record("extract_public_key", (key_path, output_path), {})
        output_path.write_bytes(PUB_BLOB)
        return AvbToolResult(0, "", "", "extract_public_key")


def _create_from_images(
    ws: WorkspacePaths, avb: FakeAvbTool, **overrides: Any
) -> ConfigCreateFromImagesResult:
    request = ConfigCreateFromImagesRequest(profile_id="dev", **overrides)
    return ConfigCreateFromImagesUseCase(ws, avb).execute(request)


class TestConfigCreateFromImagesUseCase:
    def test_creates_profile_from_the_scanned_images(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        (ws.images / "boot.img").write_bytes(b"x" * 8192)
        (ws.images / "vbmeta.img").write_bytes(b"x" * 4096)
        avb = PerImageFakeAvbTool({"boot": _ok(SAMPLE_HASH), "vbmeta": _ok(VBMETA_EMBEDDING_BOOT)})

        result = _create_from_images(ws, avb)

        assert result.created is True
        assert result.partition_count == 2
        assert result.chain_count == 0
        assert result.scanned_images == ("boot", "vbmeta")
        assert result.skipped_images == ()
        assert result.issues == ()

        profile = ProfileRepository(ws).load("dev")
        assert set(profile.partitions) == {"boot", "vbmeta"}
        assert profile.partitions["vbmeta"].included_partitions == ("boot",)
        assert (ws.resolve_key_dir("dev") / "manifest.json").is_file()

    def test_image_names_restricts_the_generated_partitions(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        for name in ("boot", "dtbo", "vbmeta"):
            (ws.images / f"{name}.img").write_bytes(b"x" * 4096)
        avb = PerImageFakeAvbTool(
            {
                "boot": _ok(SAMPLE_HASH),
                "dtbo": _ok(SAMPLE_HASH),
                "vbmeta": _ok(VBMETA_EMBEDDING_BOOT),
            }
        )

        result = _create_from_images(ws, avb, image_names=("boot",))

        assert result.created is True
        assert result.scanned_images == ("boot",)
        assert result.partition_count == 1
        assert set(ProfileRepository(ws).load("dev").partitions) == {"boot"}
        # Only the requested image was ever inspected.
        assert [call[1][0].stem for call in avb.calls] == ["boot"]

    def test_missing_image_name_creates_nothing(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        (ws.images / "boot.img").write_bytes(b"x" * 4096)
        avb = PerImageFakeAvbTool({"boot": _ok(SAMPLE_HASH)})

        result = _create_from_images(ws, avb, image_names=("boot", "ghost"))

        assert result.created is False
        assert result.partition_count == 0
        assert [i.error_code for i in result.issues] == ["image.not_found"]
        assert "ghost.img" in result.issues[0].message
        assert not ws.resolve_profile_dir("dev").exists()
        assert avb.calls == []

    def test_image_without_avb_structure_is_fatal_by_default(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        (ws.images / "boot.img").write_bytes(b"x" * 4096)
        (ws.images / "raw.img").write_bytes(b"raw")
        avb = PerImageFakeAvbTool(
            {
                "boot": _ok(SAMPLE_HASH),
                "raw": AvbToolResult(1, "", SAMPLE_NO_FOOTER, "info_image"),
            }
        )

        result = _create_from_images(ws, avb)

        assert result.created is False
        assert [i.error_code for i in result.issues] == ["image.no_vbmeta_structure"]
        assert result.skipped_images == ("raw",)
        assert not ws.resolve_profile_dir("dev").exists()

    def test_skip_non_avb_creates_the_profile_and_reports_the_skip(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        (ws.images / "boot.img").write_bytes(b"x" * 4096)
        (ws.images / "raw.img").write_bytes(b"raw")
        avb = PerImageFakeAvbTool(
            {
                "boot": _ok(SAMPLE_HASH),
                "raw": AvbToolResult(1, "", SAMPLE_NO_FOOTER, "info_image"),
            }
        )

        result = _create_from_images(ws, avb, skip_non_avb=True)

        assert result.created is True
        assert result.skipped_images == ("raw",)
        assert result.partition_count == 1
        assert "image.no_vbmeta_structure" not in [i.error_code for i in result.issues]
        assert set(ProfileRepository(ws).load("dev").partitions) == {"boot"}

    def test_existing_profile_is_a_conflict_without_overwrite(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        (ws.images / "boot.img").write_bytes(b"x" * 4096)
        avb = PerImageFakeAvbTool({"boot": _ok(SAMPLE_HASH)})

        first = _create_from_images(ws, avb)
        second = _create_from_images(ws, avb)

        assert first.created is True
        assert second.created is False
        assert [i.error_code for i in second.issues] == ["config.profile_exists"]
        assert set(ProfileRepository(ws).load("dev").partitions) == {"boot"}

    def test_overwrite_replaces_partitions_and_keeps_the_key_store(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        (ws.images / "boot.img").write_bytes(b"x" * 4096)
        first_tool = PerImageFakeAvbTool({"boot": _ok(SAMPLE_HASH)})
        assert _create_from_images(ws, first_tool).created is True

        # A user drops a key into the store before regenerating.
        key_dir = ws.resolve_key_dir("dev")
        manifest = {"testkey_rsa4096": {"private_key": "testkey_rsa4096.pem"}}
        (key_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (key_dir / "testkey_rsa4096.pem").write_text("fake key", encoding="utf-8")

        (ws.images / "boot.img").unlink()
        (ws.images / "dtbo.img").write_bytes(b"x" * 4096)
        second_tool = PerImageFakeAvbTool({"dtbo": _ok(SAMPLE_HASH)})

        result = _create_from_images(ws, second_tool, overwrite=True)

        assert result.created is True
        assert set(ProfileRepository(ws).load("dev").partitions) == {"dtbo"}
        # keys/ content survived the overwrite
        assert json.loads((key_dir / "manifest.json").read_text(encoding="utf-8")) == manifest
        assert (key_dir / "testkey_rsa4096.pem").is_file()

    def test_directory_without_usable_images_reports_no_partitions(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        (ws.images / "notes.txt").write_text("not an image", encoding="utf-8")
        avb = FakeAvbTool()

        result = _create_from_images(ws, avb)

        assert result.created is False
        assert [i.error_code for i in result.issues] == ["config.no_partitions"]
        assert not ws.resolve_profile_dir("dev").exists()

    def test_only_non_avb_images_reports_no_partitions(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        (ws.images / "raw.img").write_bytes(b"raw")
        avb = PerImageFakeAvbTool({"raw": AvbToolResult(1, "", SAMPLE_NO_FOOTER, "info_image")})

        result = _create_from_images(ws, avb, skip_non_avb=True)

        assert result.created is False
        assert [i.error_code for i in result.issues] == ["config.no_partitions"]
        assert result.skipped_images == ("raw",)
        assert not ws.resolve_profile_dir("dev").exists()

    def test_missing_keys_are_reported_without_failing(self, tmp_path: Path) -> None:
        """A signed partition whose key is absent is reported, not fatal
        (the fixture is signed on purpose: an unsigned partition needs no
        key, so it would never be reported here)."""
        ws = _make_workspace(tmp_path)
        (ws.images / "init_boot.img").write_bytes(b"x" * 4096)
        avb = PerImageFakeAvbTool({"init_boot": _ok(SIGNED_INIT_BOOT)})

        result = _create_from_images(ws, avb, key_id="testkey_rsa4096")

        assert result.created is True
        assert result.issues == ()
        assert result.missing_keys == ("testkey_rsa4096",)

    def test_activate_writes_the_active_profile(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        (ws.images / "boot.img").write_bytes(b"x" * 4096)
        avb = PerImageFakeAvbTool({"boot": _ok(SAMPLE_HASH)})

        inactive = _create_from_images(ws, avb)
        assert inactive.created is True
        assert not (ws.root / ".active-profile").exists()

        (ws.images / "dtbo.img").write_bytes(b"x" * 4096)
        avb_dtbo = PerImageFakeAvbTool({"dtbo": _ok(SAMPLE_HASH)})
        activated = _create_from_images(ws, avb_dtbo, overwrite=True, activate=True)

        assert activated.created is True
        assert (ws.root / ".active-profile").read_text(encoding="utf-8") == "dev"

    def test_invalid_profile_id_creates_nothing(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        (ws.images / "boot.img").write_bytes(b"x" * 4096)
        avb = PerImageFakeAvbTool({"boot": _ok(SAMPLE_HASH)})

        result = ConfigCreateFromImagesUseCase(ws, avb).execute(
            ConfigCreateFromImagesRequest(profile_id="bad id!")
        )

        assert result.created is False
        assert [i.error_code for i in result.issues] == ["config.invalid_profile_id"]
        assert not (ws.profiles / "bad_id_").exists()
        assert avb.calls == []

    def test_chain_entries_are_resolved_and_counted(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        key_dir = ws.resolve_key_dir("dev")
        key_dir.mkdir(parents=True)
        (key_dir / "key.pem").write_text("fake key", encoding="utf-8")
        (key_dir / "manifest.json").write_text(
            json.dumps({"default": {"private_key": "key.pem"}}), encoding="utf-8"
        )
        (ws.images / "vbmeta.img").write_bytes(b"x" * 4096)
        avb = WritingFakeAvbTool({"vbmeta": _ok(CHAIN_OUTPUT)})

        result = _create_from_images(ws, avb, overwrite=True)

        assert result.created is True
        assert result.chain_count == 2
        assert result.issues == ()
        vbmeta = ProfileRepository(ws).load("dev").partitions["vbmeta"]
        assert vbmeta.chain_partitions == (
            "vbmeta_system:1:key.pem.bin",
            "vbmeta_vendor:2:key.pem.bin",
        )

    def test_unresolved_chains_do_not_block_creation(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        (ws.images / "vbmeta.img").write_bytes(b"x" * 4096)
        avb = PerImageFakeAvbTool({"vbmeta": _ok(SAMPLE_VBMETA_WITH_CHAIN)})

        result = _create_from_images(ws, avb)

        assert result.created is True
        assert result.chain_count == 0
        # No key store holds the chained public keys -> reported, not fatal.
        # The emptied vbmeta is reported by the (non-blocking) domain
        # validation, exactly as the profile will be until it is edited.
        assert [i.error_code for i in result.issues] == [
            "chain.key_not_found",
            "chain.key_not_found",
            "config.vbmeta_no_contents",
        ]

    def test_explicit_image_directory_is_scanned(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        other = tmp_path / "other_images"
        other.mkdir()
        (other / "boot.img").write_bytes(b"x" * 4096)
        avb = PerImageFakeAvbTool({"boot": _ok(SAMPLE_HASH)})

        result = _create_from_images(ws, avb, image_dir=other)

        assert result.created is True
        assert result.scanned_images == ("boot",)
        assert set(ProfileRepository(ws).load("dev").partitions) == {"boot"}


# ---------------------------------------------------------------------------
# Key selection: only keys that really exist may be written into a profile
# ---------------------------------------------------------------------------


def _hash_output(partition: str, algorithm: str) -> str:
    """The hash fixture, re-labelled for *partition* and *algorithm*."""
    return SAMPLE_HASH.replace(
        "Partition Name:        boot", f"Partition Name:        {partition}"
    ).replace("Algorithm:                NONE", f"Algorithm:                {algorithm}")


UNSIGNED_DTBO = _hash_output("dtbo", "NONE")
SIGNED_INIT_BOOT = _hash_output("init_boot", "SHA256_RSA4096")


def _seed_key_store(ws: WorkspacePaths, profile_id: str, key_ids: tuple[str, ...]) -> None:
    """Create the profile's key store holding *key_ids* (with real files)."""
    key_dir = ws.resolve_key_dir(profile_id)
    key_dir.mkdir(parents=True, exist_ok=True)
    manifest = {key_id: {"private_key": f"{key_id}.pem"} for key_id in key_ids}
    for entry in manifest.values():
        (key_dir / entry["private_key"]).write_text("fake key", encoding="utf-8")
    (key_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


class TestConfigCreateFromImagesKeySelection:
    """The generated key_ids must all exist in the profile's key store."""

    def _images(self, ws: WorkspacePaths, *names: str) -> PerImageFakeAvbTool:
        outputs = {"dtbo": UNSIGNED_DTBO, "init_boot": SIGNED_INIT_BOOT}
        for name in names:
            (ws.images / f"{name}.img").write_bytes(b"x" * 4096)
        return PerImageFakeAvbTool({name: _ok(outputs[name]) for name in names})

    def _two_images(self, ws: WorkspacePaths) -> PerImageFakeAvbTool:
        return self._images(ws, "dtbo", "init_boot")

    def test_multiple_keys_leave_unsigned_partitions_keyless(self, tmp_path: Path) -> None:
        """Two keys give no principled default: unsigned partitions get an
        empty key_id, signed ones get their size match."""
        ws = _make_workspace(tmp_path)
        _seed_key_store(ws, "dev", ("testkey_rsa2048", "testkey_rsa4096"))
        avb = self._two_images(ws)

        result = _create_from_images(ws, avb, overwrite=True)

        assert result.created is True
        partitions = ProfileRepository(ws).load("dev").partitions
        assert partitions["dtbo"].algorithm == SigningAlgorithm.NONE
        assert partitions["dtbo"].key_id == ""
        assert partitions["init_boot"].algorithm == SigningAlgorithm.SHA256_RSA4096
        assert partitions["init_boot"].key_id == "testkey_rsa4096"
        # No invented key id anywhere.
        assert "default" not in {p.key_id for p in partitions.values()}

    def test_single_key_is_used_for_every_partition(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        _seed_key_store(ws, "dev", ("testkey_rsa4096",))
        avb = self._two_images(ws)

        result = _create_from_images(ws, avb, overwrite=True)

        assert result.created is True
        partitions = ProfileRepository(ws).load("dev").partitions
        assert {p.key_id for p in partitions.values()} == {"testkey_rsa4096"}

    def test_empty_key_store_never_invents_a_default(self, tmp_path: Path) -> None:
        """No key in the store: every partition gets an empty key_id (never
        an invented ``"default"``).  Creation still succeeds -- missing keys
        are informational -- and only the signed partition is reported."""
        ws = _make_workspace(tmp_path)
        avb = self._two_images(ws)

        result = _create_from_images(ws, avb)

        assert result.created is True
        partitions = ProfileRepository(ws).load("dev").partitions
        assert {p.key_id for p in partitions.values()} == {""}
        assert result.issues == ()
        assert result.missing_keys == ("",)

    def test_explicit_key_id_override_wins_over_the_key_store(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        _seed_key_store(ws, "dev", ("testkey_rsa2048", "testkey_rsa4096"))
        avb = self._two_images(ws)

        result = _create_from_images(ws, avb, key_id="X", overwrite=True)

        assert result.created is True
        partitions = ProfileRepository(ws).load("dev").partitions
        assert {p.key_id for p in partitions.values()} == {"X"}

    def test_created_profile_validates_without_missing_keys(self, tmp_path: Path) -> None:
        """End-to-end regression: a profile created from images must not
        report keys it never referenced (the invented ``"default"``)."""
        ws = _make_workspace(tmp_path)
        _seed_key_store(ws, "dev", ("testkey_rsa2048", "testkey_rsa4096"))
        avb = self._two_images(ws)

        created = _create_from_images(ws, avb, overwrite=True)
        validated = ConfigValidateUseCase(ws).execute(ConfigValidateRequest(profile_id="dev"))

        assert created.created is True
        assert created.missing_keys == ()
        assert validated.missing_images == ()
        assert validated.missing_keys == ()
