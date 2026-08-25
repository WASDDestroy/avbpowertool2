"""Tests for the TUI create-config wizard's auto-mode partition builder."""

from __future__ import annotations

from pathlib import Path

from avbpowertool.application.commands import ChainKeyResolution
from avbpowertool.domain.models import (
    ChainDescriptor,
    DescriptorType,
    ImageInspection,
    PartitionConfig,
    SigningAlgorithm,
)
from avbpowertool.presentation.tui.views.create_config import (
    _apply_chain_resolutions,
    _build_auto_partition,
    _finalize_vbmeta_includes,
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
        config = _build_auto_partition(_inspection(), tmp_path)

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
        config = _build_auto_partition(
            _inspection(algorithm="SHA256_RSA4096"), tmp_path
        )
        assert config is not None
        assert config.algorithm == SigningAlgorithm.SHA256_RSA4096

    def test_flag_bits(self, tmp_path: Path) -> None:
        config = _build_auto_partition(_inspection(flags="3"), tmp_path)
        assert config is not None
        assert config.flags == 3
        assert config.set_hashtree_disabled_flag is True
        assert config.set_verification_disabled_flag is True

    def test_hash_algorithm_clamped(self, tmp_path: Path) -> None:
        config = _build_auto_partition(
            _inspection(hash_algorithm="foobar"), tmp_path
        )
        assert config is not None
        assert config.hash_algorithm == "sha256"

    def test_hash_algorithm_missing_defaults(self, tmp_path: Path) -> None:
        config = _build_auto_partition(
            _inspection(hash_algorithm=None), tmp_path
        )
        assert config is not None
        assert config.hash_algorithm == "sha256"

    def test_hashtree_hash_algorithm_read(self, tmp_path: Path) -> None:
        config = _build_auto_partition(
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
        config = _build_auto_partition(
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
        assert _build_auto_partition(inspection, tmp_path) is None

    def test_empty_values_fall_back(self, tmp_path: Path) -> None:
        config = _build_auto_partition(
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
        partitions = _finalize_vbmeta_includes(by_image, included)
        vbmeta = next(p for p in partitions if p.partition_name == "vbmeta")
        # "odm"/"init_boot" are not in the scan -> dropped
        assert vbmeta.included_partitions == ("dtbo",)

    def test_falls_back_to_other_scanned_partitions(self) -> None:
        by_image = {
            "boot.img": _config("boot.img", "boot", DescriptorType.HASH),
            "system.img": _config("system.img", "system", DescriptorType.HASHTREE),
            "vbmeta.img": _config("vbmeta.img", "vbmeta", DescriptorType.VBMETA),
        }
        partitions = _finalize_vbmeta_includes(by_image, {})
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
        partitions = _finalize_vbmeta_includes(by_image, {})
        vbmeta = next(p for p in partitions if p.partition_name == "vbmeta")
        assert vbmeta.included_partitions == ("boot",)
        vbmeta_system = next(
            p for p in partitions if p.partition_name == "vbmeta_system"
        )
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
        partitions = _finalize_vbmeta_includes(by_image, {"vbmeta.img": ("dtbo",)})
        names = {p.partition_name for p in partitions}
        assert names == {"boot", "dtbo", "vbmeta", "vbmeta_system"}
        # the real dtbo.img config keeps its own image file
        dtbo = next(p for p in partitions if p.partition_name == "dtbo")
        assert dtbo.image == "dtbo.img"


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
        result = _apply_chain_resolutions(by_image, chains, resolutions)
        vbmeta = result["vbmeta.img"]
        assert vbmeta.chain_partitions == (
            "vbmeta_system:1:key.pem",
            "vbmeta_vendor:2:other.pem",
        )

    def test_unresolved_entries_are_skipped(self) -> None:
        by_image = {
            "vbmeta.img": _config("vbmeta.img", "vbmeta", DescriptorType.VBMETA),
        }
        chains = {
            "vbmeta.img": (ChainDescriptor("vbmeta_system", "1", "a" * 40),)
        }
        resolutions = (ChainKeyResolution(entry=""),)
        result = _apply_chain_resolutions(by_image, chains, resolutions)
        assert result["vbmeta.img"].chain_partitions == ()

    def test_no_chain_images_unchanged(self) -> None:
        by_image = {
            "boot.img": _config("boot.img", "boot", DescriptorType.HASH),
        }
        result = _apply_chain_resolutions(by_image, {}, ())
        assert result["boot.img"].chain_partitions == ()