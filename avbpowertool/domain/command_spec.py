"""Declarative avbtool command specifications.

Port of the Android Compose app's command data model
(``AvbModels.kt`` / ``AvbCommands.all``) for the commands AVBPowerTool2
supports.  This module is the **single source of truth** for avbtool
command arguments: config validation, CLI/TUI forms, and the command
builder all derive from these tables, so field names cannot drift from
the actual avbtool CLI.

Each :class:`CommandArg` binds an avbtool ``--flag`` to a
``PartitionConfig`` field.  ``repeatable`` arguments map to tuple fields;
``advanced`` arguments are folded behind an "Advanced" group in forms.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ArgType(Enum):
    """Semantic type of an avbtool argument (mirrors the Android model)."""

    IMAGE = "image"  # input image path
    FILE = "file"  # other file path (key, metadata, descriptor source)
    TEXT = "text"  # free-form string
    INT = "int"  # integer
    BOOL = "bool"  # boolean switch (present = true)
    SIZE = "size"  # byte size (partition size)
    ALGORITHM = "algorithm"  # signing algorithm enum
    HASH_ALGORITHM = "hash_algorithm"  # sha1 / sha256 / blake2b-256
    FLAGS = "flags"  # integer bitmask
    CHAIN_PARTITION = "chain_partition"  # PART_NAME:ROLLBACK_SLOT:KEY_PATH


@dataclass(frozen=True)
class CommandArg:
    """A single avbtool command argument."""

    flag: str  # avbtool option name, e.g. "--partition_size"
    config_field: str  # PartitionConfig field this argument maps to
    arg_type: ArgType
    required: bool = False
    default: object | None = None
    advanced: bool = False
    repeatable: bool = False


@dataclass(frozen=True)
class CommandSpec:
    """Full specification of one avbtool subcommand."""

    id: str
    inputs: tuple[CommandArg, ...] = ()
    outputs: tuple[CommandArg, ...] = ()
    args: tuple[CommandArg, ...] = ()


# ---------------------------------------------------------------------------
# Command registry — exact port of AvbCommands.all for the 5 supported
# commands (argument order matches the Android model).
# ---------------------------------------------------------------------------

#: avbtool options shared by add_hash_footer / add_hashtree_footer /
#: make_vbmeta_image (avbtool._add_common_args + _add_common_footer_args).
_COMMON_ARGS: tuple[CommandArg, ...] = (
    CommandArg("--algorithm", "algorithm", ArgType.ALGORITHM, default="NONE"),
    CommandArg("--key", "key_id", ArgType.FILE),
    CommandArg("--signing_helper", "signing_helper", ArgType.TEXT, advanced=True),
    CommandArg(
        "--signing_helper_with_files", "signing_helper_with_files", ArgType.TEXT, advanced=True
    ),
    CommandArg("--public_key_metadata", "public_key_metadata", ArgType.FILE, advanced=True),
    CommandArg("--rollback_index", "rollback_index", ArgType.INT, default=0),
    CommandArg(
        "--rollback_index_location",
        "rollback_index_location",
        ArgType.INT,
        default=0,
        advanced=True,
    ),
    CommandArg(
        "--append_to_release_string", "append_to_release_string", ArgType.TEXT, advanced=True
    ),
    CommandArg("--prop", "props", ArgType.TEXT, repeatable=True),
    CommandArg("--prop_from_file", "prop_from_file", ArgType.TEXT, repeatable=True, advanced=True),
    CommandArg("--kernel_cmdline", "kernel_cmdlines", ArgType.TEXT, repeatable=True, advanced=True),
    CommandArg(
        "--setup_rootfs_from_kernel", "setup_rootfs_from_kernel", ArgType.FILE, advanced=True
    ),
    CommandArg(
        "--include_descriptors_from_image",
        "include_descriptors_from_image",
        ArgType.FILE,
        repeatable=True,
    ),
    CommandArg(
        "--print_required_libavb_version",
        "print_required_libavb_version",
        ArgType.BOOL,
        advanced=True,
    ),
    CommandArg(
        "--chain_partition",
        "chain_partitions",
        ArgType.CHAIN_PARTITION,
        repeatable=True,
        advanced=True,
    ),
    CommandArg(
        "--chain_partition_do_not_use_ab",
        "chain_partitions_do_not_use_ab",
        ArgType.CHAIN_PARTITION,
        repeatable=True,
        advanced=True,
    ),
    CommandArg("--flags", "flags", ArgType.FLAGS, default=0),
    CommandArg(
        "--set_hashtree_disabled_flag", "set_hashtree_disabled_flag", ArgType.BOOL, advanced=True
    ),
    CommandArg(
        "--set_verification_disabled_flag",
        "set_verification_disabled_flag",
        ArgType.BOOL,
        advanced=True,
    ),
    CommandArg("--use_persistent_digest", "use_persistent_digest", ArgType.BOOL, advanced=True),
    CommandArg("--do_not_use_ab", "do_not_use_ab", ArgType.BOOL, advanced=True),
)

_COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec(
        id="add_hash_footer",
        inputs=(CommandArg("--image", "image", ArgType.IMAGE, required=True),),
        args=(
            CommandArg("--partition_size", "partition_size", ArgType.SIZE),
            CommandArg("--dynamic_partition_size", "dynamic_partition_size", ArgType.BOOL),
            CommandArg("--partition_name", "partition_name", ArgType.TEXT),
            CommandArg(
                "--hash_algorithm", "hash_algorithm", ArgType.HASH_ALGORITHM, default="sha256"
            ),
            CommandArg("--salt", "salt", ArgType.TEXT),
            CommandArg("--calc_max_image_size", "calc_max_image_size", ArgType.BOOL),
            CommandArg("--do_not_append_vbmeta_image", "do_not_append_vbmeta_image", ArgType.BOOL),
            CommandArg("--output_vbmeta_image", "output_vbmeta_image", ArgType.TEXT, advanced=True),
        )
        + _COMMON_ARGS,
    ),
    CommandSpec(
        id="add_hashtree_footer",
        inputs=(CommandArg("--image", "image", ArgType.IMAGE, required=True),),
        args=(
            CommandArg("--partition_size", "partition_size", ArgType.SIZE, default=0),
            CommandArg("--partition_name", "partition_name", ArgType.TEXT, default=""),
            CommandArg(
                "--hash_algorithm", "hash_algorithm", ArgType.HASH_ALGORITHM, default="sha256"
            ),
            CommandArg("--salt", "salt", ArgType.TEXT),
            CommandArg("--block_size", "block_size", ArgType.INT, default=4096),
            CommandArg("--do_not_generate_fec", "do_not_generate_fec", ArgType.BOOL),
            CommandArg("--fec_num_roots", "fec_num_roots", ArgType.INT, default=2),
            CommandArg("--calc_max_image_size", "calc_max_image_size", ArgType.BOOL),
            CommandArg("--do_not_append_vbmeta_image", "do_not_append_vbmeta_image", ArgType.BOOL),
            CommandArg(
                "--setup_as_rootfs_from_kernel",
                "setup_as_rootfs_from_kernel",
                ArgType.BOOL,
                advanced=True,
            ),
            CommandArg("--no_hashtree", "no_hashtree", ArgType.BOOL, advanced=True),
            CommandArg("--check_at_most_once", "check_at_most_once", ArgType.BOOL, advanced=True),
            CommandArg("--output_vbmeta_image", "output_vbmeta_image", ArgType.TEXT, advanced=True),
        )
        + _COMMON_ARGS,
    ),
    CommandSpec(
        id="make_vbmeta_image",
        outputs=(CommandArg("--output", "", ArgType.FILE, required=True),),
        args=(CommandArg("--padding_size", "padding_size", ArgType.INT, default=0, advanced=True),)
        + _COMMON_ARGS,
    ),
    CommandSpec(
        id="info_image",
        inputs=(CommandArg("--image", "image", ArgType.IMAGE, required=True),),
        args=(CommandArg("--cert", "", ArgType.BOOL),),
    ),
    CommandSpec(
        id="extract_public_key",
        outputs=(CommandArg("--output", "", ArgType.FILE, required=True),),
        args=(CommandArg("--key", "key_id", ArgType.FILE, required=True),),
    ),
)

#: Lookup: command id -> CommandSpec.
COMMANDS: dict[str, CommandSpec] = {spec.id: spec for spec in _COMMANDS}


def spec_for(command_id: str) -> CommandSpec | None:
    """Return the CommandSpec for a command id, or None."""
    return COMMANDS.get(command_id)
