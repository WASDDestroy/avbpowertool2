"""Build avbtool argument lists from domain objects.

All functions return plain lists of strings (the avbtool subcommand
and its arguments, without the python interpreter or script path).

Footer commands (``add_hash_footer`` / ``add_hashtree_footer``) modify
the image **in place** — they have no ``--output`` flag.  The caller
passes the staging copy as ``image_path`` and is responsible for copying
the original there first (see ``domain/signing_plan.py`` /
``application/services/sign_images.py``).

Argument set mirrors ``domain/command_spec.py``: an option is only
emitted when its config value differs from the default, except for a
small fixed header (identity / rollback fields) that avbtool always
accepts.
"""

from __future__ import annotations

from pathlib import Path

from avbpowertool.domain.models import PartitionConfig


def build_inspect_command(image_path: Path, cert: bool = False) -> list[str]:
    """Build arg list for avbtool info_image."""
    cmd = ["info_image", "--image", str(image_path)]
    if cert:
        cmd.append("--cert")
    return cmd


def build_erase_footer_command(image_path: Path) -> list[str]:
    """Build arg list for avbtool erase_footer."""
    return ["erase_footer", "--image", str(image_path)]


def build_hash_footer_command(
    image_path: Path,
    config: PartitionConfig,
    key_path: Path | None = None,
) -> list[str]:
    """Build arg list for avbtool add_hash_footer (operates in place).

    ``image_path`` must point at the file to modify (normally a staging
    copy).  ``key_path`` may be None for unsigned (NONE algorithm)
    footers.
    """
    cmd = [
        "add_hash_footer",
        "--image",
        str(image_path),
        "--partition_name",
        config.partition_name,
        "--hash_algorithm",
        config.hash_algorithm,
        "--rollback_index",
        str(config.rollback_index),
        "--rollback_index_location",
        str(config.rollback_index_location),
    ]
    if config.salt:
        # Empty salt -> omit --salt so avbtool generates a random one.
        cmd.extend(["--salt", config.salt])
    if config.partition_size > 0:
        cmd.extend(["--partition_size", str(config.partition_size)])
    if config.dynamic_partition_size:
        cmd.append("--dynamic_partition_size")
    if key_path is not None:
        cmd.extend(["--algorithm", config.algorithm.value, "--key", str(key_path)])
    _append_common_args(cmd, config)
    return cmd


def build_hashtree_footer_command(
    image_path: Path,
    config: PartitionConfig,
    key_path: Path | None = None,
) -> list[str]:
    """Build arg list for avbtool add_hashtree_footer (operates in place).

    ``key_path`` may be None for unsigned (NONE algorithm) footers.
    """
    cmd = [
        "add_hashtree_footer",
        "--image",
        str(image_path),
        "--partition_name",
        config.partition_name,
        "--hash_algorithm",
        config.hash_algorithm,
        "--rollback_index",
        str(config.rollback_index),
        "--rollback_index_location",
        str(config.rollback_index_location),
        "--block_size",
        str(config.block_size),
    ]
    if config.salt:
        cmd.extend(["--salt", config.salt])
    if config.partition_size > 0:
        cmd.extend(["--partition_size", str(config.partition_size)])
    if key_path is not None:
        cmd.extend(["--algorithm", config.algorithm.value, "--key", str(key_path)])
    if config.do_not_generate_fec:
        cmd.append("--do_not_generate_fec")
    if config.fec_num_roots != 2:
        cmd.extend(["--fec_num_roots", str(config.fec_num_roots)])
    if config.no_hashtree:
        cmd.append("--no_hashtree")
    if config.check_at_most_once:
        cmd.append("--check_at_most_once")
    if config.setup_as_rootfs_from_kernel:
        cmd.append("--setup_as_rootfs_from_kernel")
    _append_common_args(cmd, config)
    return cmd


def build_vbmeta_command(
    output_path: Path,
    config: PartitionConfig,
    key_path: Path | None = None,
    include_descriptors: tuple[Path, ...] = (),
    chain_partitions: tuple[str, ...] = (),
    include_props: bool = True,
) -> list[str]:
    """Build arg list for avbtool make_vbmeta_image.

    ``include_descriptors`` holds resolved staging image paths (from
    ``included_partitions`` + ``include_descriptors_from_image``);
    ``chain_partitions`` holds fully-resolved ``PART:SLOT:KEY_PATH``
    triples.  ``key_path`` may be None for unsigned (NONE algorithm)
    vbmeta.  ``include_props`` gates emission of the config's props
    (both ``--prop`` and ``--prop_from_file``).
    """
    cmd = [
        "make_vbmeta_image",
        "--output",
        str(output_path),
        "--rollback_index",
        str(config.rollback_index),
        "--rollback_index_location",
        str(config.rollback_index_location),
    ]
    if key_path is not None:
        cmd.extend(["--algorithm", config.algorithm.value, "--key", str(key_path)])
    for desc_path in include_descriptors:
        cmd.extend(["--include_descriptors_from_image", str(desc_path)])
    for chain in chain_partitions:
        cmd.extend(["--chain_partition", chain])
    for chain in config.chain_partitions_do_not_use_ab:
        cmd.extend(["--chain_partition_do_not_use_ab", chain])
    if config.flags:
        cmd.extend(["--flags", str(config.flags)])
    if config.set_hashtree_disabled_flag:
        cmd.append("--set_hashtree_disabled_flag")
    if config.set_verification_disabled_flag:
        cmd.append("--set_verification_disabled_flag")
    if config.padding_size:
        cmd.extend(["--padding_size", str(config.padding_size)])
    if include_props:
        for k, v in config.props:
            cmd.extend(["--prop", f"{k}:{v}"])
        for k, path in config.prop_from_file:
            cmd.extend(["--prop_from_file", f"{k}:{path}"])
    for cmdline in config.kernel_cmdlines:
        cmd.extend(["--kernel_cmdline", cmdline])
    if config.setup_rootfs_from_kernel:
        cmd.extend(["--setup_rootfs_from_kernel", config.setup_rootfs_from_kernel])
    if config.print_required_libavb_version:
        cmd.append("--print_required_libavb_version")
    if config.signing_helper:
        cmd.extend(["--signing_helper", config.signing_helper])
    if config.signing_helper_with_files:
        cmd.extend(["--signing_helper_with_files", config.signing_helper_with_files])
    if config.public_key_metadata:
        cmd.extend(["--public_key_metadata", config.public_key_metadata])
    if config.append_to_release_string:
        cmd.extend(["--append_to_release_string", config.append_to_release_string])
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


def _append_common_args(cmd: list[str], config: PartitionConfig) -> None:
    """Append the footer-common argument set (see command_spec)."""
    if config.flags:
        cmd.extend(["--flags", str(config.flags)])
    if config.set_hashtree_disabled_flag:
        cmd.append("--set_hashtree_disabled_flag")
    if config.set_verification_disabled_flag:
        cmd.append("--set_verification_disabled_flag")
    if config.calc_max_image_size:
        cmd.append("--calc_max_image_size")
    if config.do_not_append_vbmeta_image:
        cmd.append("--do_not_append_vbmeta_image")
    for k, v in config.props:
        cmd.extend(["--prop", f"{k}:{v}"])
    for k, path in config.prop_from_file:
        cmd.extend(["--prop_from_file", f"{k}:{path}"])
    for cmdline in config.kernel_cmdlines:
        cmd.extend(["--kernel_cmdline", cmdline])
    for img in config.include_descriptors_from_image:
        cmd.extend(["--include_descriptors_from_image", img])
    for chain in config.chain_partitions:
        cmd.extend(["--chain_partition", chain])
    for chain in config.chain_partitions_do_not_use_ab:
        cmd.extend(["--chain_partition_do_not_use_ab", chain])
    if config.output_vbmeta_image:
        cmd.extend(["--output_vbmeta_image", config.output_vbmeta_image])
    if config.setup_rootfs_from_kernel:
        cmd.extend(["--setup_rootfs_from_kernel", config.setup_rootfs_from_kernel])
    if config.print_required_libavb_version:
        cmd.append("--print_required_libavb_version")
    if config.use_persistent_digest:
        cmd.append("--use_persistent_digest")
    if config.do_not_use_ab:
        cmd.append("--do_not_use_ab")
    if config.signing_helper:
        cmd.extend(["--signing_helper", config.signing_helper])
    if config.signing_helper_with_files:
        cmd.extend(["--signing_helper_with_files", config.signing_helper_with_files])
    if config.public_key_metadata:
        cmd.extend(["--public_key_metadata", config.public_key_metadata])
    if config.append_to_release_string:
        cmd.extend(["--append_to_release_string", config.append_to_release_string])
