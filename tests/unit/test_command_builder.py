"""Tests for avbtool command builder — deterministic output.

The canonical builder lives in ``avbpowertool.domain.command_builder``
(footer commands modify their input in place — no ``--output``).
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from avbpowertool.domain.command_builder import (
    build_erase_footer_command,
    build_extract_public_key_command,
    build_hash_footer_command,
    build_hashtree_footer_command,
    build_inspect_command,
    build_vbmeta_command,
)
from avbpowertool.domain.models import (
    DescriptorType,
    PartitionConfig,
    SigningAlgorithm,
)


def _p(posix: str) -> Path:
    """Create a Path that behaves consistently for assertions."""
    return PurePosixPath(posix)  # type: ignore[return-value]


def _make_config(
    descriptor: DescriptorType = DescriptorType.HASH,
    **overrides: object,
) -> PartitionConfig:
    defaults: dict[str, object] = dict(
        image="boot.img",
        descriptor=descriptor,
        algorithm=SigningAlgorithm.SHA256_RSA4096,
        key_id="testkey",
        partition_name="boot",
        rollback_index=0,
        salt="abcdef",
        partition_size=4096,
    )
    defaults.update(overrides)
    return PartitionConfig(**defaults)  # type: ignore[arg-type]


class TestBuildInspectCommand:
    def test_basic(self) -> None:
        cmd = build_inspect_command(_p("/images/boot.img"))
        assert cmd[0] == "info_image"
        assert "--image" in cmd
        assert cmd[cmd.index("--image") + 1] == "/images/boot.img"
        assert "--cert" not in cmd

    def test_with_cert(self) -> None:
        cmd = build_inspect_command(_p("/images/boot.img"), cert=True)
        assert "--cert" in cmd


class TestBuildEraseFooterCommand:
    def test_basic(self) -> None:
        cmd = build_erase_footer_command(_p("/images/boot.img"))
        assert cmd[0] == "erase_footer"
        assert cmd[cmd.index("--image") + 1] == "/images/boot.img"


class TestBuildHashFooterCommand:
    def test_basic_command(self) -> None:
        config = _make_config()
        cmd = build_hash_footer_command(_p("/staging/boot.img"), config, _p("/keys/test.pem"))
        assert cmd[0] == "add_hash_footer"
        assert cmd[cmd.index("--image") + 1] == "/staging/boot.img"
        assert cmd[cmd.index("--partition_name") + 1] == "boot"
        assert cmd[cmd.index("--algorithm") + 1] == "SHA256_RSA4096"
        assert cmd[cmd.index("--key") + 1] == "/keys/test.pem"
        assert cmd[cmd.index("--salt") + 1] == "abcdef"
        assert cmd[cmd.index("--partition_size") + 1] == "4096"

    def test_no_output_flag(self) -> None:
        """add_hash_footer has no --output flag — in-place modification."""
        config = _make_config()
        cmd = build_hash_footer_command(_p("/staging/boot.img"), config, _p("/keys/test.pem"))
        assert "--output" not in cmd

    def test_with_flags(self) -> None:
        config = _make_config(flags=3)
        cmd = build_hash_footer_command(_p("/staging/boot.img"), config, _p("/keys/test.pem"))
        assert "--flags" in cmd
        assert cmd[cmd.index("--flags") + 1] == "3"

    def test_with_props(self) -> None:
        config = _make_config(props=(("key1", "val1"), ("key2", "val2")))
        cmd = build_hash_footer_command(_p("/staging/boot.img"), config, _p("/keys/test.pem"))
        assert "--prop" in cmd
        assert "key1:val1" in cmd
        assert "key2:val2" in cmd

    def test_deterministic_output(self) -> None:
        config = _make_config()
        args = (_p("/staging/boot.img"), config, _p("/keys/test.pem"))
        cmd1 = build_hash_footer_command(*args)
        cmd2 = build_hash_footer_command(*args)
        assert cmd1 == cmd2

    def test_none_omits_algorithm_and_key(self) -> None:
        config = _make_config(algorithm=SigningAlgorithm.NONE, key_id="")
        cmd = build_hash_footer_command(_p("/staging/dtbo.img"), config)
        assert "--algorithm" not in cmd
        assert "--key" not in cmd

    def test_empty_salt_omitted_for_random(self) -> None:
        """Empty salt must omit --salt so avbtool generates a random one."""
        config = _make_config(salt="")
        cmd = build_hash_footer_command(_p("/staging/boot.img"), config, _p("/keys/test.pem"))
        assert "--salt" not in cmd

    def test_dynamic_partition_size_flag(self) -> None:
        config = _make_config(partition_size=0, dynamic_partition_size=True)
        cmd = build_hash_footer_command(_p("/staging/boot.img"), config, _p("/keys/test.pem"))
        assert "--dynamic_partition_size" in cmd
        assert "--partition_size" not in cmd

    def test_advanced_flags(self) -> None:
        config = _make_config(
            calc_max_image_size=True,
            do_not_append_vbmeta_image=True,
            use_persistent_digest=True,
            do_not_use_ab=True,
            kernel_cmdlines=("androidboot.avb.test=1",),
            chain_partitions=("vbmeta_system:1:sys_pub.bin",),
            prop_from_file=(("my.prop", "props/val.txt"),),
        )
        cmd = build_hash_footer_command(_p("/staging/boot.img"), config, _p("/keys/test.pem"))
        assert "--calc_max_image_size" in cmd
        assert "--do_not_append_vbmeta_image" in cmd
        assert "--use_persistent_digest" in cmd
        assert "--do_not_use_ab" in cmd
        assert "--kernel_cmdline" in cmd
        assert "androidboot.avb.test=1" in cmd
        assert "--chain_partition" in cmd
        assert "--prop_from_file" in cmd
        assert "my.prop:props/val.txt" in cmd


class TestBuildHashtreeFooterCommand:
    def test_basic_command(self) -> None:
        config = _make_config(descriptor=DescriptorType.HASHTREE)
        cmd = build_hashtree_footer_command(_p("/staging/system.img"), config, _p("/keys/test.pem"))
        assert cmd[0] == "add_hashtree_footer"
        assert cmd[cmd.index("--image") + 1] == "/staging/system.img"
        assert cmd[cmd.index("--block_size") + 1] == "4096"
        assert cmd[cmd.index("--algorithm") + 1] == "SHA256_RSA4096"
        assert "--output" not in cmd

    def test_custom_block_size(self) -> None:
        config = _make_config(descriptor=DescriptorType.HASHTREE, block_size=512)
        cmd = build_hashtree_footer_command(_p("/staging/system.img"), config, _p("/keys/test.pem"))
        assert cmd[cmd.index("--block_size") + 1] == "512"

    def test_fec_options(self) -> None:
        config = _make_config(
            descriptor=DescriptorType.HASHTREE,
            do_not_generate_fec=True,
            fec_num_roots=8,
        )
        cmd = build_hashtree_footer_command(_p("/staging/system.img"), config, _p("/keys/test.pem"))
        assert "--do_not_generate_fec" in cmd
        assert cmd[cmd.index("--fec_num_roots") + 1] == "8"

    def test_hashtree_specific_advanced(self) -> None:
        config = _make_config(
            descriptor=DescriptorType.HASHTREE,
            no_hashtree=True,
            check_at_most_once=True,
            setup_as_rootfs_from_kernel=True,
        )
        cmd = build_hashtree_footer_command(_p("/staging/system.img"), config, _p("/keys/test.pem"))
        assert "--no_hashtree" in cmd
        assert "--check_at_most_once" in cmd
        assert "--setup_as_rootfs_from_kernel" in cmd

    def test_none_omits_algorithm_and_key(self) -> None:
        config = _make_config(
            descriptor=DescriptorType.HASHTREE,
            algorithm=SigningAlgorithm.NONE,
            key_id="",
        )
        cmd = build_hashtree_footer_command(_p("/staging/system.img"), config)
        assert "--algorithm" not in cmd
        assert "--key" not in cmd


class TestBuildVbmetaCommand:
    def _make_vbmeta_config(self, **overrides: object) -> PartitionConfig:
        return _make_config(descriptor=DescriptorType.VBMETA, **overrides)

    def test_basic_command(self) -> None:
        config = self._make_vbmeta_config()
        cmd = build_vbmeta_command(_p("/staging/vbmeta.img"), config, _p("/keys/test.pem"))
        assert cmd[0] == "make_vbmeta_image"
        assert cmd[cmd.index("--output") + 1] == "/staging/vbmeta.img"
        assert cmd[cmd.index("--algorithm") + 1] == "SHA256_RSA4096"
        assert cmd[cmd.index("--key") + 1] == "/keys/test.pem"

    def test_with_include_descriptors(self) -> None:
        config = self._make_vbmeta_config()
        cmd = build_vbmeta_command(
            _p("/staging/vbmeta.img"),
            config,
            _p("/keys/test.pem"),
            include_descriptors=(_p("/staging/boot.img"), _p("/staging/system.img")),
        )
        assert "--include_descriptors_from_image" in cmd
        assert "/staging/boot.img" in cmd
        assert "/staging/system.img" in cmd

    def test_with_chain_partitions(self) -> None:
        config = self._make_vbmeta_config()
        cmd = build_vbmeta_command(
            _p("/staging/vbmeta.img"),
            config,
            _p("/keys/test.pem"),
            chain_partitions=("vbmeta_system:1:sys_key.pem",),
        )
        assert "--chain_partition" in cmd
        assert "vbmeta_system:1:sys_key.pem" in cmd

    def test_none_omits_algorithm_and_key(self) -> None:
        config = self._make_vbmeta_config(algorithm=SigningAlgorithm.NONE, key_id="")
        cmd = build_vbmeta_command(_p("/staging/vbmeta.img"), config)
        assert "--algorithm" not in cmd
        assert "--key" not in cmd

    def test_padding_and_cmdlines(self) -> None:
        config = self._make_vbmeta_config(
            padding_size=64,
            kernel_cmdlines=("androidboot.avb.avb_version=1.2",),
        )
        cmd = build_vbmeta_command(_p("/staging/vbmeta.img"), config, _p("/keys/test.pem"))
        assert cmd[cmd.index("--padding_size") + 1] == "64"
        assert "--kernel_cmdline" in cmd
        assert "androidboot.avb.avb_version=1.2" in cmd


class TestBuildExtractPublicKeyCommand:
    def test_basic(self) -> None:
        cmd = build_extract_public_key_command(
            _p("/keys/test.pem"),
            _p("/keys/test_pub.bin"),
        )
        assert cmd[0] == "extract_public_key"
        assert cmd[cmd.index("--key") + 1] == "/keys/test.pem"
        assert cmd[cmd.index("--output") + 1] == "/keys/test_pub.bin"
