"""Tests for the TUI create-config wizard's auto-mode partition builder."""

from __future__ import annotations

from pathlib import Path

from avbpowertool.domain.models import (
    DescriptorType,
    ImageInspection,
    SigningAlgorithm,
)
from avbpowertool.presentation.tui.views.create_config import _build_auto_partition


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