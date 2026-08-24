"""Tests for avbtool command builder — deterministic output."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from avbpowertool.domain.models import (
    DescriptorType,
    PartitionConfig,
    SigningAlgorithm,
)
from avbpowertool.infrastructure.avbtool.command_builder import (
    build_erase_footer_command,
    build_extract_public_key_command,
    build_hash_footer_command,
    build_hashtree_footer_command,
    build_inspect_command,
    build_vbmeta_command,
)


def _p(posix: str) -> Path:
    """Create a Path that behaves consistently for assertions."""
    return PurePosixPath(posix)  # type: ignore[return-value]


class TestBuildInspectCommand:
    def test_basic(self) -> None:
        cmd = build_inspect_command(_p("/images/boot.img"))
        assert cmd[0] == "info_image"
        assert "--image" in cmd
        assert cmd[cmd.index("--image") + 1] == "/images/boot.img"


class TestBuildEraseFooterCommand:
    def test_basic(self) -> None:
        cmd = build_erase_footer_command(_p("/images/boot.img"))
        assert cmd[0] == "erase_footer"
        assert cmd[cmd.index("--image") + 1] == "/images/boot.img"


class TestBuildHashFooterCommand:
    def _make_config(self, **overrides: object) -> PartitionConfig:
        defaults: dict[str, object] = dict(
            image="boot.img",
            descriptor=DescriptorType.HASH,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="testkey",
            partition_name="boot",
            rollback_index=0,
            salt="abcdef",
        )
        defaults.update(overrides)
        return PartitionConfig(**defaults)  # type: ignore[arg-type]

    def test_basic_command(self) -> None:
        config = self._make_config()
        cmd = build_hash_footer_command(
            _p("/img/boot.img"),
            _p("/staging/boot.img"),
            config,
            _p("/keys/test.pem"),
        )
        assert cmd[0] == "add_hash_footer"
        assert cmd[cmd.index("--image") + 1] == "/img/boot.img"
        assert cmd[cmd.index("--partition_name") + 1] == "boot"
        assert cmd[cmd.index("--algorithm") + 1] == "SHA256_RSA4096"
        assert cmd[cmd.index("--key") + 1] == "/keys/test.pem"
        assert cmd[cmd.index("--salt") + 1] == "abcdef"

    def test_with_flags(self) -> None:
        config = self._make_config(flags=3)
        cmd = build_hash_footer_command(
            _p("/img/boot.img"),
            _p("/staging/boot.img"),
            config,
            _p("/keys/test.pem"),
        )
        assert "--flags" in cmd
        flag_idx = cmd.index("--flags")
        assert cmd[flag_idx + 1] == "3"

    def test_with_props(self) -> None:
        config = self._make_config(props=(("key1", "val1"), ("key2", "val2")))
        cmd = build_hash_footer_command(
            _p("/img/boot.img"),
            _p("/staging/boot.img"),
            config,
            _p("/keys/test.pem"),
        )
        assert "--prop" in cmd
        assert "key1:val1" in cmd
        assert "key2:val2" in cmd

    def test_deterministic_output(self) -> None:
        config = self._make_config()
        args = (_p("/img/boot.img"), _p("/staging/boot.img"), config, _p("/keys/test.pem"))
        cmd1 = build_hash_footer_command(*args)
        cmd2 = build_hash_footer_command(*args)
        assert cmd1 == cmd2

    def test_none_omits_algorithm_and_key(self) -> None:
        config = self._make_config(algorithm=SigningAlgorithm.NONE, key_id="")
        cmd = build_hash_footer_command(
            _p("/img/dtbo.img"),
            _p("/staging/dtbo.img"),
            config,
            None,
        )
        assert "--algorithm" not in cmd
        assert "--key" not in cmd
        assert "--hash_algorithm" in cmd


class TestBuildHashtreeFooterCommand:
    def _make_config(self, **overrides: object) -> PartitionConfig:
        defaults: dict[str, object] = dict(
            image="system.img",
            descriptor=DescriptorType.HASHTREE,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="testkey",
            partition_name="system",
            rollback_index=0,
            salt="aabb",
            data_block_size=4096,
            hash_block_size=4096,
        )
        defaults.update(overrides)
        return PartitionConfig(**defaults)  # type: ignore[arg-type]

    def test_basic_command(self) -> None:
        config = self._make_config()
        cmd = build_hashtree_footer_command(
            _p("/img/system.img"),
            _p("/staging/system.img"),
            config,
            _p("/keys/test.pem"),
        )
        assert cmd[0] == "add_hashtree_footer"
        assert "--data_block_size" in cmd
        assert "--hash_block_size" in cmd
        assert "4096" in cmd

    def test_custom_block_sizes(self) -> None:
        config = self._make_config(data_block_size=512, hash_block_size=512)
        cmd = build_hashtree_footer_command(
            _p("/img/system.img"),
            _p("/staging/system.img"),
            config,
            _p("/keys/test.pem"),
        )
        assert "512" in cmd


class TestBuildVbmetaCommand:
    def test_basic_command(self) -> None:
        cmd = build_vbmeta_command(
            output_path=_p("/staging/vbmeta.img"),
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_path=_p("/keys/test.pem"),
            rollback_index=0,
        )
        assert cmd[0] == "make_vbmeta_image"
        assert cmd[cmd.index("--output") + 1] == "/staging/vbmeta.img"
        assert cmd[cmd.index("--algorithm") + 1] == "SHA256_RSA4096"

    def test_with_include_descriptors(self) -> None:
        cmd = build_vbmeta_command(
            output_path=_p("/staging/vbmeta.img"),
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_path=_p("/keys/test.pem"),
            rollback_index=0,
            include_descriptors=(_p("/staging/boot.img"), _p("/staging/system.img")),
        )
        assert cmd.count("--include_descriptors_from_image") == 2
        # Check the descriptor paths are in the command
        desc_args = [
            cmd[i + 1] for i, arg in enumerate(cmd) if arg == "--include_descriptors_from_image"
        ]
        assert "/staging/boot.img" in desc_args
        assert "/staging/system.img" in desc_args

    def test_with_chain_partitions(self) -> None:
        cmd = build_vbmeta_command(
            output_path=_p("/staging/vbmeta.img"),
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_path=_p("/keys/test.pem"),
            rollback_index=0,
            chain_partitions=("vbmeta_system:1:sys_key.pem",),
        )
        assert "--chain_partition" in cmd
        assert "vbmeta_system:1:sys_key.pem" in cmd

    def test_none_omits_algorithm_and_key(self) -> None:
        cmd = build_vbmeta_command(
            output_path=_p("/staging/vbmeta.img"),
            algorithm=SigningAlgorithm.NONE,
            key_path=None,
            rollback_index=0,
        )
        assert "--algorithm" not in cmd
        assert "--key" not in cmd


class TestBuildExtractPublicKeyCommand:
    def test_basic(self) -> None:
        cmd = build_extract_public_key_command(
            _p("/keys/test.pem"),
            _p("/keys/test_pub.bin"),
        )
        assert cmd[0] == "extract_public_key"
        assert cmd[cmd.index("--key") + 1] == "/keys/test.pem"
        assert cmd[cmd.index("--output") + 1] == "/keys/test_pub.bin"
