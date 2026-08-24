"""Build avbtool argument lists from domain objects.

All functions return plain lists of strings (the avbtool subcommand
and its arguments, without the python interpreter or script path).
"""

from __future__ import annotations

from pathlib import Path

from avbpowertool.domain.models import PartitionConfig, SigningAlgorithm


def build_inspect_command(image_path: Path) -> list[str]:
    """Build arg list for avbtool info_image."""
    return ["info_image", "--image", str(image_path)]


def build_erase_footer_command(image_path: Path) -> list[str]:
    """Build arg list for avbtool erase_footer."""
    return ["erase_footer", "--image", str(image_path)]


def build_hash_footer_command(
    image_path: Path,
    output_path: Path,
    config: PartitionConfig,
    key_path: Path | None = None,
) -> list[str]:
    """Build arg list for avbtool add_hash_footer.

    ``key_path`` may be None for unsigned (NONE algorithm) footers.
    """
    cmd = [
        "add_hash_footer",
        "--image",
        str(image_path),
        "--output",
        str(output_path),
        "--partition_name",
        config.partition_name,
        "--salt",
        config.salt,
        "--rollback_index",
        str(config.rollback_index),
        "--rollback_index_location",
        str(config.rollback_index_location),
        "--hash_algorithm",
        config.hash_algorithm,
    ]
    if key_path is not None:
        cmd.extend(["--algorithm", config.algorithm.value, "--key", str(key_path)])
    if config.flags:
        cmd.extend(["--flags", str(config.flags)])
    for k, v in config.props:
        cmd.extend(["--prop", f"{k}:{v}"])
    return cmd


def build_hashtree_footer_command(
    image_path: Path,
    output_path: Path,
    config: PartitionConfig,
    key_path: Path | None = None,
) -> list[str]:
    """Build arg list for avbtool add_hashtree_footer.

    ``key_path`` may be None for unsigned (NONE algorithm) footers.
    """
    cmd = [
        "add_hashtree_footer",
        "--image",
        str(image_path),
        "--output",
        str(output_path),
        "--partition_name",
        config.partition_name,
        "--salt",
        config.salt,
        "--rollback_index",
        str(config.rollback_index),
        "--rollback_index_location",
        str(config.rollback_index_location),
        "--data_block_size",
        str(config.data_block_size),
        "--hash_block_size",
        str(config.hash_block_size),
    ]
    if key_path is not None:
        cmd.extend(["--algorithm", config.algorithm.value, "--key", str(key_path)])
    if config.flags:
        cmd.extend(["--flags", str(config.flags)])
    for k, v in config.props:
        cmd.extend(["--prop", f"{k}:{v}"])
    return cmd


def build_vbmeta_command(
    output_path: Path,
    algorithm: SigningAlgorithm,
    key_path: Path | None,
    rollback_index: int,
    include_descriptors: tuple[Path, ...] = (),
    chain_partitions: tuple[str, ...] = (),
    flags: int = 0,
    props: tuple[tuple[str, str], ...] = (),
) -> list[str]:
    """Build arg list for avbtool make_vbmeta_image.

    ``key_path`` may be None for unsigned (NONE algorithm) vbmeta.
    """
    cmd = [
        "make_vbmeta_image",
        "--output",
        str(output_path),
        "--rollback_index",
        str(rollback_index),
    ]
    if key_path is not None:
        cmd.extend(["--algorithm", algorithm.value, "--key", str(key_path)])
    for desc_path in include_descriptors:
        cmd.extend(["--include_descriptors_from_image", str(desc_path)])
    for chain in chain_partitions:
        cmd.extend(["--chain_partition", chain])
    if flags:
        cmd.extend(["--flags", str(flags)])
    for k, v in props:
        cmd.extend(["--prop", f"{k}:{v}"])
    return cmd


def build_extract_public_key_command(key_path: Path, output_path: Path) -> list[str]:
    """Build arg list for avbtool extract_public_key."""
    return [
        "extract_public_key",
        "--key",
        str(key_path),
        "--output",
        str(output_path),
    ]
