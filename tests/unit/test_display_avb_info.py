"""Tests for the TUI current-config display helper."""

from __future__ import annotations

from avbpowertool.domain.models import (
    AvbProfile,
    DescriptorType,
    PartitionConfig,
    SigningAlgorithm,
)
from avbpowertool.infrastructure.persistence.profile_codec import (
    decode_profile_with_issues,
    encode_profile,
)
from avbpowertool.presentation.i18n import init_i18n
from avbpowertool.presentation.tui.views.display_avb_info import partition_config_lines

init_i18n("en")


def _config(**overrides: object) -> PartitionConfig:
    data: dict = dict(
        image="boot.img",
        descriptor=DescriptorType.HASH,
        algorithm=SigningAlgorithm.SHA256_RSA4096,
        key_id="testkey",
        partition_name="boot",
    )
    data.update(overrides)  # type: ignore[arg-type]
    return PartitionConfig(**data)  # type: ignore[arg-type]


class TestPartitionConfigLines:
    def test_core_fields_always_shown(self) -> None:
        assert partition_config_lines(_config()) == [
            "[boot]",
            "  Image: boot.img",
            "  Descriptor: hash",
            "  Algorithm: SHA256_RSA4096",
            "  Key ID: testkey",
        ]

    def test_non_default_fields_are_shown(self) -> None:
        pc = _config(
            partition_size=4096,
            dynamic_partition_size=True,
            rollback_index=3,
            rollback_index_location=1,
            salt="a1b2c3",
            hash_algorithm="sha512",
            flags=2,
            props=(("a", "1"),),
            prop_from_file=(("b", "2"),),
            set_hashtree_disabled_flag=True,
            set_verification_disabled_flag=True,
            included_partitions=("dtbo",),
            chain_partitions=("vbmeta_system:1:k.pem",),
            kernel_cmdlines=("androidboot.foo=bar",),
            padding_size=4096,
            use_persistent_digest=True,
        )
        joined = "\n".join(partition_config_lines(pc))
        for needle in [
            "  Partition Size: 4096",
            "  Dynamic Partition Size: true",
            "  Rollback Index: 3",
            "  Rollback Index Location: 1",
            "  Salt: a1b2c3",
            "  Hash Algorithm: sha512",
            "  Flags: 2",
            "  Props:",
            "    a = 1",
            "  Prop From File:",
            "    b = 2",
            "  Set Hashtree Disabled: true",
            "  Set Verification Disabled: true",
            "  Included Partitions: dtbo",
            "  Chain Partitions: vbmeta_system:1:k.pem",
            "  Kernel Cmdlines: androidboot.foo=bar",
            "  Padding Size: 4096",
            "  Use Persistent Digest: true",
        ]:
            assert needle in joined

    def test_default_fields_are_omitted(self) -> None:
        joined = "\n".join(partition_config_lines(_config()))
        for needle in [
            "Partition Size",
            "Dynamic Partition Size",
            "Rollback Index",
            "Salt",
            "Hash Algorithm",
            "Flags",
            "Props",
            "Included Partitions",
            "Padding Size",
        ]:
            assert needle not in joined

    def test_hashtree_fields_only_for_hashtree_descriptor(self) -> None:
        pc = _config(
            descriptor=DescriptorType.HASHTREE,
            block_size=1024,
            fec_num_roots=4,
            do_not_generate_fec=True,
            no_hashtree=True,
            check_at_most_once=True,
            setup_as_rootfs_from_kernel=True,
        )
        joined = "\n".join(partition_config_lines(pc))
        for needle in [
            "  Block Size: 1024",
            "  FEC Num Roots: 4",
            "  Do Not Generate FEC: true",
            "  No Hashtree: true",
            "  Check At Most Once: true",
            "  Setup As Rootfs From Kernel: true",
        ]:
            assert needle in joined

    def test_hashtree_defaults_not_shown(self) -> None:
        joined = "\n".join(partition_config_lines(_config(descriptor=DescriptorType.HASHTREE)))
        assert "Block Size" not in joined
        assert "FEC" not in joined

    def test_vbmeta_and_signing_helper_fields(self) -> None:
        pc = _config(
            descriptor=DescriptorType.VBMETA,
            included_partitions=("boot", "system"),
            include_descriptors_from_image=("boot.img",),
            chain_partitions=("vbmeta_system:1:k.pem",),
            chain_partitions_do_not_use_ab=("vendor",),
            setup_rootfs_from_kernel="/system",
            output_vbmeta_image="vbmeta.img",
            calc_max_image_size=True,
            do_not_append_vbmeta_image=True,
            print_required_libavb_version=True,
            do_not_use_ab=True,
            signing_helper="/usr/bin/sign",
            signing_helper_with_files="/usr/bin/signw",
            public_key_metadata="meta",
            append_to_release_string="release",
        )
        joined = "\n".join(partition_config_lines(pc))
        for needle in [
            "  Included Partitions: boot, system",
            "  Include Descriptors From Image: boot.img",
            "  Chain Partitions: vbmeta_system:1:k.pem",
            "  Chain Partitions (no AB): vendor",
            "  Setup Rootfs From Kernel: /system",
            "  Output Vbmeta Image: vbmeta.img",
            "  Calc Max Image Size: true",
            "  Do Not Append Vbmeta Image: true",
            "  Print Required Libavb Version: true",
            "  Do Not Use AB: true",
            "  Signing Helper: /usr/bin/sign",
            "  Signing Helper With Files: /usr/bin/signw",
            "  Public Key Metadata: meta",
            "  Append To Release String: release",
        ]:
            assert needle in joined

    def test_roundtrip_preserves_displayed_fields(self) -> None:
        """The rendered lines survive an encode/decode round trip, so the
        view stays faithful to what the profile codec persists."""
        pc = _config(
            partition_size=8192,
            dynamic_partition_size=True,
            rollback_index=7,
            rollback_index_location=2,
            salt="deadbeef",
            hash_algorithm="sha512",
            flags=3,
            props=(("k", "v"),),
            set_verification_disabled_flag=True,
            included_partitions=("boot",),
            padding_size=2048,
        )
        profile = AvbProfile(id="p", name="P", partitions={"boot": pc})
        decoded, _issues = decode_profile_with_issues(encode_profile(profile))
        assert partition_config_lines(decoded.partitions["boot"]) == partition_config_lines(pc)
