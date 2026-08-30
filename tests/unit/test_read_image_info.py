"""Tests for the TUI read-image-info display helper."""

from __future__ import annotations

from avbpowertool.domain.models import (
    ChainDescriptor,
    DescriptorType,
    ImageInspection,
)
from avbpowertool.presentation.i18n import init_i18n
from avbpowertool.presentation.tui.views.read_image_info import image_inspection_lines

init_i18n("en")


def _inspection(**overrides: object) -> ImageInspection:
    data: dict = dict(
        image_name="boot",
        image_path="/img/boot.img",
        descriptor=DescriptorType.HASH,
        algorithm="SHA256_RSA4096",
        partition_name="boot",
        public_key_sha1="a" * 40,
        rollback_index="5",
        rollback_index_location="1",
        hash_algorithm="sha256",
        salt="a1b2c3",
        digest="d1e2f3",
        flags="2",
        props=(("android.boot.test", "1"),),
        included_partitions=(),
        chain_descriptors=(),
        raw_extensions=(("Max image size", "4294967296"),),
    )
    data.update(overrides)  # type: ignore[arg-type]
    return ImageInspection(**data)  # type: ignore[arg-type]


class TestImageInspectionLines:
    def test_all_metadata_fields_shown(self) -> None:
        joined = "\n".join(image_inspection_lines(_inspection()))
        for needle in [
            "[boot]",
            "  Path: /img/boot.img",
            "  Descriptor: hash",
            "  Algorithm: SHA256_RSA4096",
            "  Partition Name: boot",
            "  Public Key SHA1: " + "a" * 40,
            "  Rollback Index: 5",
            "  Rollback Index Location: 1",
            "  Hash Algorithm: sha256",
            "  Salt: a1b2c3",
            "  Digest: d1e2f3",
            "  Flags: 2",
            "  Prop: android.boot.test = 1",
            "  Max image size: 4294967296",
        ]:
            assert needle in joined

    def test_no_descriptor_shows_na(self) -> None:
        img = ImageInspection(image_name="raw", image_path="/img/raw.img", descriptor=None)
        lines = image_inspection_lines(img)
        assert "  Descriptor: N/A" in lines
        # only the identity lines exist; optional metadata is omitted
        assert lines == ["[raw]", "  Path: /img/raw.img", "  Descriptor: N/A"]

    def test_vbmeta_shows_included_and_chains(self) -> None:
        img = _inspection(
            descriptor=DescriptorType.VBMETA,
            partition_name=None,
            included_partitions=("dtbo", "init_boot"),
            chain_descriptors=(ChainDescriptor("vbmeta_system", "1", "b" * 40),),
        )
        joined = "\n".join(image_inspection_lines(img))
        assert "  Included Partitions: dtbo, init_boot" in joined
        assert "  Chain: vbmeta_system slot=1 pubkey=" + "b" * 40 in joined
