"""AVBPowerTool v2 CLI — argparse dispatch via stable ActionId.

Every handler builds a typed request, calls an application use-case,
and renders the result.  Dispatch is controlled by ActionId, never by
display strings or argument names.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import TextIO

from avbpowertool.presentation.actions import ActionId


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="avbpowertool",
        description="AVB Power Tool — image inspection, signing, and config management",
    )
    sub = parser.add_subparsers(dest="command")

    # --- image ---
    p_image = sub.add_parser("image", help="Image operations")
    img_sub = p_image.add_subparsers(dest="image_command", required=True)

    # image inspect
    p_img_inspect = img_sub.add_parser("inspect", help="Read AVB metadata from images")
    p_img_inspect.add_argument("images", nargs="+", help="Image names")
    p_img_inspect.add_argument("--cert", action="store_true", help="Also read the certificate")
    p_img_inspect.add_argument("--json", action="store_true", help="JSON output")
    p_img_inspect.set_defaults(action_id=ActionId.IMAGE_INSPECT)

    # image sign
    p_img_sign = img_sub.add_parser("sign", help="Sign images")
    p_img_sign.add_argument("images", nargs="+", help="Image names to sign")
    p_img_sign.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Generate signing plan without execution",
    )
    p_img_sign.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Actually execute signing (requires --yes)",
    )
    p_img_sign.add_argument("--yes", action="store_true", help="Confirm execution")
    p_img_sign.add_argument(
        "--profile",
        default="current",
        help="Profile ID (default: current — resolved to the active profile)",
    )
    p_img_sign.add_argument(
        "--remove-footers", action="store_true", help="Remove existing footers first"
    )
    p_img_sign.add_argument("--json", action="store_true", help="JSON output")
    p_img_sign.set_defaults(action_id=ActionId.IMAGE_SIGN)

    # --- config ---
    p_config = sub.add_parser("config", help="Configuration operations")
    cfg_sub = p_config.add_subparsers(dest="config_command", required=True)

    # config show
    p_cfg_show = cfg_sub.add_parser("show", help="Show current config")
    p_cfg_show.add_argument(
        "--profile",
        default="current",
        help="Profile ID (default: current — resolved to the active profile)",
    )
    p_cfg_show.add_argument("--json", action="store_true", help="JSON output")
    p_cfg_show.set_defaults(action_id=ActionId.CONFIG_SHOW)

    # config validate
    p_cfg_val = cfg_sub.add_parser("validate", help="Validate config against workspace")
    p_cfg_val.add_argument(
        "--profile",
        default="current",
        help="Profile ID (default: current — resolved to the active profile)",
    )
    p_cfg_val.add_argument("--json", action="store_true", help="JSON output")
    p_cfg_val.set_defaults(action_id=ActionId.CONFIG_VALIDATE)

    # config create
    p_cfg_create = cfg_sub.add_parser(
        "create",
        help="Create a new profile (optionally from images or with no partitions)",
    )
    p_cfg_create.add_argument("--id", dest="profile_id", required=True, help="New profile ID")
    p_cfg_create.add_argument(
        "--name",
        dest="profile_name",
        default=None,
        help="Profile display name (default: the value of --id)",
    )
    # --from-images and --allow-empty are two different creation sources:
    # one fills the profile from images, the other deliberately leaves it
    # empty.  argparse rejects the combination with exit code 2.
    create_source = p_cfg_create.add_mutually_exclusive_group()
    create_source.add_argument(
        "--from-images",
        dest="from_images",
        nargs="?",
        const="",
        default=None,
        metavar="DIR",
        help="Generate the partitions from images (default: the workspace Images/ directory)",
    )
    create_source.add_argument(
        "--allow-empty",
        action="store_true",
        help="Allow creating a profile with no partitions",
    )
    p_cfg_create.add_argument(
        "--images",
        action="append",
        default=None,
        metavar="NAMES",
        help="Comma-separated image names to use with --from-images "
        "(e.g. boot,dtbo or boot.img); may be repeated",
    )
    p_cfg_create.add_argument(
        "--key",
        dest="key_id",
        default=None,
        help="Key ID to use for every generated partition (default: automatic)",
    )
    p_cfg_create.add_argument(
        "--no-chain-resolve",
        dest="resolve_chains",
        action="store_false",
        default=True,
        help="Do not resolve the chain partitions read from the vbmeta images",
    )
    p_cfg_create.add_argument(
        "--include-fallback",
        dest="include_fallback",
        action="store_true",
        help="Let a vbmeta without embedded descriptors include every other scanned partition",
    )
    p_cfg_create.add_argument(
        "--skip-non-avb",
        dest="skip_non_avb",
        action="store_true",
        help="Skip images without an AVB structure instead of failing",
    )
    p_cfg_create.add_argument(
        "--overwrite",
        action="store_true",
        help="Reuse an existing profile directory (its keys/ are kept, its partitions "
        "replaced); requires --from-images",
    )
    create_activation = p_cfg_create.add_mutually_exclusive_group()
    create_activation.add_argument(
        "--activate",
        dest="activate",
        action="store_true",
        help="Make the new profile the active one (writes .active-profile; default: not activated)",
    )
    create_activation.add_argument(
        "--no-activate",
        dest="activate",
        action="store_false",
        help="Do not touch .active-profile (default)",
    )
    p_cfg_create.add_argument("--json", action="store_true", help="JSON output")
    p_cfg_create.set_defaults(action_id=ActionId.CONFIG_CREATE, activate=False)

    # config list
    p_cfg_list = cfg_sub.add_parser("list", help="List all profiles")
    p_cfg_list.add_argument("--json", action="store_true", help="JSON output")
    p_cfg_list.set_defaults(action_id=ActionId.CONFIG_LIST)

    # config activate
    p_cfg_act = cfg_sub.add_parser("activate", help="Activate a profile")
    p_cfg_act.add_argument("profile", help="Profile ID to activate")
    p_cfg_act.add_argument("--json", action="store_true", help="JSON output")
    p_cfg_act.set_defaults(action_id=ActionId.CONFIG_ACTIVATE)

    # config import
    p_cfg_imp = cfg_sub.add_parser("import", help="Import config from archive")
    p_cfg_imp.add_argument("archive", help="Path to ZIP archive")
    p_cfg_imp.add_argument("--json", action="store_true", help="JSON output")
    p_cfg_imp.set_defaults(action_id=ActionId.CONFIG_IMPORT)

    # config import-legacy (v1 -> v2 auto-conversion)
    p_cfg_imp_legacy = cfg_sub.add_parser(
        "import-legacy",
        help="Import a legacy v1 config archive (auto-converts to v3)",
    )
    p_cfg_imp_legacy.add_argument("archive", help="Path to legacy v1 ZIP archive")
    p_cfg_imp_legacy.add_argument(
        "--name",
        dest="profile_id",
        default=None,
        help="New profile ID (default: derived from archive)",
    )
    p_cfg_imp_legacy.add_argument(
        "--no-activate",
        action="store_true",
        help="Do not activate the imported profile",
    )
    p_cfg_imp_legacy.add_argument("--json", action="store_true", help="JSON output")
    p_cfg_imp_legacy.set_defaults(action_id=ActionId.CONFIG_IMPORT_LEGACY)

    # config export
    p_cfg_exp = cfg_sub.add_parser("export", help="Export config to archive")
    p_cfg_exp.add_argument("profile", help="Profile ID to export")
    p_cfg_exp.add_argument("--output", help="Output path (default: <profile>.zip)")
    p_cfg_exp.add_argument("--json", action="store_true", help="JSON output")
    p_cfg_exp.set_defaults(action_id=ActionId.CONFIG_EXPORT)

    # config migrate (v2 -> v3)
    p_cfg_migrate = cfg_sub.add_parser(
        "migrate",
        help="Upgrade a profile to the current schema version (v2 -> v3)",
    )
    p_cfg_migrate.add_argument("--profile", default="current", help="Profile ID (default: current)")
    p_cfg_migrate.add_argument("--json", action="store_true", help="JSON output")
    p_cfg_migrate.set_defaults(action_id=ActionId.CONFIG_MIGRATE)

    # config edit (update individual partition fields)
    p_cfg_edit = cfg_sub.add_parser("edit", help="Update fields of one partition config")
    p_cfg_edit.add_argument("--profile", default="current", help="Profile ID (default: current)")
    p_cfg_edit.add_argument("partition", help="Partition name to edit (e.g. boot)")
    p_cfg_edit.add_argument(
        "--set",
        dest="updates",
        action="append",
        metavar="FIELD=VALUE",
        default=[],
        help=(
            "Set a field, e.g. partition_size=67108864, block_size=4096, "
            "key_id=testkey_rsa4096, algorithm=SHA256_RSA2048, image=boot.img, "
            "kernel_cmdlines=a,b or props=key:value,key2:value2 "
            "(repeatable; replaces the whole field; booleans: true/false)"
        ),
    )
    p_cfg_edit.add_argument(
        "--unset",
        dest="unsets",
        action="append",
        metavar="FIELD",
        default=[],
        help=(
            "Reset a field to its empty value: str -> '', int -> 0, bool -> false, "
            "tuple -> empty (repeatable; fields that reject empty values, such as "
            "image and algorithm, report their normal error)"
        ),
    )
    p_cfg_edit.add_argument(
        "--append",
        dest="appends",
        action="append",
        metavar="FIELD=ITEM",
        default=[],
        help=(
            "Append ITEM to a tuple field (repeatable, tuple fields only: "
            "kernel_cmdlines, chain_partitions, chain_partitions_do_not_use_ab, "
            "included_partitions, include_descriptors_from_image, props, "
            "prop_from_file). For the chain fields ITEM must be a full "
            "PART:SLOT:KEYFILE triple (SLOT a number >= 1); an ITEM for an "
            "already-chained partition replaces that entry in place"
        ),
    )
    p_cfg_edit.add_argument(
        "--remove",
        dest="removes",
        action="append",
        metavar="FIELD=ITEM",
        default=[],
        help=(
            "Remove ITEM from a tuple field (repeatable, tuple fields only). The "
            "chain fields match by partition name (bare name or full triple); other "
            "tuple fields match the whole item"
        ),
    )
    p_cfg_edit.add_argument("--json", action="store_true", help="JSON output")
    p_cfg_edit.set_defaults(action_id=ActionId.CONFIG_EDIT)

    # config check-chains (read-only chain/key consistency check)
    p_cfg_check = cfg_sub.add_parser(
        "check-chains",
        help="Check every chain partition of a profile against its key store",
    )
    p_cfg_check.add_argument(
        "--profile",
        default="current",
        help="Profile ID (default: current — resolved to the active profile)",
    )
    p_cfg_check.add_argument("--json", action="store_true", help="JSON output")
    p_cfg_check.set_defaults(action_id=ActionId.CONFIG_CHECK_CHAINS)

    # config rename (directory id and/or display name)
    p_cfg_rename = cfg_sub.add_parser(
        "rename",
        help="Rename a profile (its directory id and/or its display name)",
    )
    p_cfg_rename.add_argument(
        "old_profile_id", metavar="OLD", help="Current profile ID (directory name)"
    )
    p_cfg_rename.add_argument(
        "new_profile_id",
        metavar="NEW",
        help="New profile ID (directory name); use the same value as OLD to only set --name",
    )
    p_cfg_rename.add_argument(
        "--name",
        dest="new_name",
        default=None,
        help="New display name (default: keep the current one)",
    )
    p_cfg_rename.add_argument("--json", action="store_true", help="JSON output")
    p_cfg_rename.set_defaults(action_id=ActionId.CONFIG_RENAME)

    # config delete (destructive; --yes is a hard gate)
    p_cfg_delete = cfg_sub.add_parser(
        "delete",
        help="Delete a profile (its directory, including its keys)",
    )
    p_cfg_delete.add_argument("profile", help="Profile ID to delete")
    p_cfg_delete.add_argument(
        "--yes",
        action="store_true",
        help="Confirm the deletion (required; without it nothing is removed)",
    )
    p_cfg_delete.add_argument(
        "--force",
        action="store_true",
        help="Also delete the active profile and clear .active-profile",
    )
    p_cfg_delete.add_argument("--json", action="store_true", help="JSON output")
    p_cfg_delete.set_defaults(action_id=ActionId.CONFIG_DELETE)

    # --- keys ---
    p_keys = sub.add_parser("keys", help="Key store operations")
    keys_sub = p_keys.add_subparsers(dest="keys_command", required=True)

    # keys list
    p_keys_list = keys_sub.add_parser("list", help="List the keys in a profile's key store")
    p_keys_list.add_argument(
        "--profile",
        default="current",
        help="Profile ID (default: current — resolved to the active profile)",
    )
    p_keys_list.add_argument("--json", action="store_true", help="JSON output")
    p_keys_list.set_defaults(action_id=ActionId.KEY_LIST)

    # keys discover
    p_keys_discover = keys_sub.add_parser(
        "discover",
        help="Register the .pem files in the key store in manifest.json",
    )
    p_keys_discover.add_argument(
        "--profile",
        default="current",
        help="Profile ID (default: current — resolved to the active profile)",
    )
    discover_mode = p_keys_discover.add_mutually_exclusive_group()
    discover_mode.add_argument(
        "--merge",
        dest="merge",
        action="store_true",
        default=True,
        help=(
            "Keep existing manifest entries and their cached public keys "
            "(default); an entry keeps its public_key only while it still "
            "points at the same private-key filename"
        ),
    )
    discover_mode.add_argument(
        "--replace",
        dest="merge",
        action="store_false",
        default=argparse.SUPPRESS,
        help="Rebuild manifest.json from the discovered .pem files only (drops public keys)",
    )
    p_keys_discover.add_argument("--json", action="store_true", help="JSON output")
    p_keys_discover.set_defaults(action_id=ActionId.KEY_DISCOVER, merge=True)

    # keys ensure-public
    p_keys_ensure = keys_sub.add_parser(
        "ensure-public",
        help="Extract the missing public keys (<name>.pem.bin) and register them",
    )
    p_keys_ensure.add_argument(
        "--profile",
        default="current",
        help="Profile ID (default: current — resolved to the active profile)",
    )
    p_keys_ensure.add_argument("--json", action="store_true", help="JSON output")
    p_keys_ensure.set_defaults(action_id=ActionId.KEY_ENSURE_PUBLIC)

    # keys add
    p_keys_add = keys_sub.add_parser("add", help="Add a key entry to manifest.json")
    p_keys_add.add_argument("key_id", help="Key ID to register")
    p_keys_add.add_argument(
        "--file",
        dest="private_key_filename",
        required=True,
        metavar="NAME.pem",
        help="Private-key filename inside the key store directory (not copied from elsewhere)",
    )
    p_keys_add.add_argument(
        "--profile",
        default="current",
        help="Profile ID (default: current — resolved to the active profile)",
    )
    p_keys_add.add_argument("--json", action="store_true", help="JSON output")
    p_keys_add.set_defaults(action_id=ActionId.KEY_ADD)

    # keys remove
    p_keys_remove = keys_sub.add_parser("remove", help="Remove a key entry from manifest.json")
    p_keys_remove.add_argument("key_id", help="Key ID to remove")
    p_keys_remove.add_argument(
        "--profile",
        default="current",
        help="Profile ID (default: current — resolved to the active profile)",
    )
    p_keys_remove.add_argument("--json", action="store_true", help="JSON output")
    p_keys_remove.set_defaults(action_id=ActionId.KEY_REMOVE)

    # --- plugin ---
    p_plugin = sub.add_parser("plugin", help="Plugin operations")
    plugin_sub = p_plugin.add_subparsers(dest="plugin_command", required=True)

    # plugin list
    p_plugin_list = plugin_sub.add_parser("list", help="List the plugins under plugins/")
    p_plugin_list.add_argument("--json", action="store_true", help="JSON output")
    p_plugin_list.set_defaults(action_id=ActionId.PLUGIN_LIST)

    # plugin pack
    p_plugin_pack = plugin_sub.add_parser(
        "pack",
        help="Pack a plugin directory into an installable zip",
        epilog=(
            "SOURCE is either a plugin directory path or the id of an installed "
            "plugin. The archive uses the '<plugin_id>/...' layout, so the "
            "result installs as-is with 'plugin install'."
        ),
    )
    p_plugin_pack.add_argument(
        "source",
        metavar="SOURCE",
        help="Plugin directory path or installed plugin ID",
    )
    p_plugin_pack.add_argument(
        "--output",
        help="Output zip path (default: <plugin_id>.zip in the workspace root)",
    )
    p_plugin_pack.add_argument("--json", action="store_true", help="JSON output")
    p_plugin_pack.set_defaults(action_id=ActionId.PLUGIN_PACK)

    # plugin install
    p_plugin_install = plugin_sub.add_parser(
        "install", help="Install a plugin from a directory or a zip archive"
    )
    p_plugin_install.add_argument("source", metavar="SOURCE", help="Plugin directory or .zip path")
    p_plugin_install.add_argument(
        "--force",
        action="store_true",
        help=(
            "Overwrite an already installed plugin with the same id; "
            "also allows installing a lower version (downgrade)"
        ),
    )
    p_plugin_install.add_argument("--json", action="store_true", help="JSON output")
    p_plugin_install.set_defaults(action_id=ActionId.PLUGIN_INSTALL)

    # plugin uninstall (destructive; --yes is a hard gate)
    p_plugin_uninstall = plugin_sub.add_parser(
        "uninstall",
        help="Remove an installed plugin (its directory, including any bundled files)",
    )
    p_plugin_uninstall.add_argument("plugin_id", metavar="PLUGIN_ID", help="Plugin ID to remove")
    p_plugin_uninstall.add_argument(
        "--yes",
        action="store_true",
        help="Confirm the removal (required; without it nothing is removed)",
    )
    p_plugin_uninstall.add_argument("--json", action="store_true", help="JSON output")
    p_plugin_uninstall.set_defaults(action_id=ActionId.PLUGIN_UNINSTALL)

    # plugin run
    #
    # Everything after a standalone ``--`` goes to the plugin verbatim, so
    # ``plugin run <id> --json`` still means "this tool prints JSON" while
    # ``plugin run <id> -- --json`` means "the plugin gets --json".
    # argparse's REMAINDER cannot express both (it also swallows the
    # leading --json), so main() splits argv at the first ``--`` before
    # argparse ever sees it; the parser itself therefore has no positional
    # for the plugin's own arguments.
    p_plugin_run = plugin_sub.add_parser(
        "run",
        help="Run an installed plugin's entry script",
        epilog=(
            "Arguments after a standalone '--' are passed to the plugin verbatim, "
            "e.g. 'avbpowertool plugin run testkey_config_gen -- --core --8e'. "
            "A '--json' before the '--' is consumed by avbpowertool, a '--json' "
            "after it is passed to the plugin."
        ),
    )
    p_plugin_run.add_argument("plugin_id", metavar="PLUGIN_ID", help="Plugin ID to run")
    p_plugin_run.add_argument(
        "--json",
        action="store_true",
        help="JSON output from avbpowertool (the plugin's own output is never captured)",
    )
    p_plugin_run.set_defaults(action_id=ActionId.PLUGIN_RUN)

    # --- about ---
    p_about = sub.add_parser("about", help="Show version info")
    p_about.set_defaults(action_id="about")

    # --- Old command aliases (deprecated) ---
    for old_cmd in ("read", "sign", "get_all_config", "check_l10n"):
        alias = sub.add_parser(old_cmd, help="(deprecated) Use new command instead")
        alias.add_argument("rest", nargs="*", help=argparse.SUPPRESS)
        alias.add_argument("--images", nargs="*", help=argparse.SUPPRESS)
        alias.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
        alias.set_defaults(action_id=f"deprecated:{old_cmd}")

    return parser


def _split_plugin_passthrough(argv: Sequence[str]) -> tuple[list[str], list[str]]:
    """Split ``plugin run`` argv at its first standalone ``--``.

    Returns ``(plugin_args, tool_argv)``: *plugin_args* is what the plugin
    receives verbatim and *tool_argv* is what argparse parses.  The split
    only happens for ``plugin run`` (every other command has no
    pass-through contract), and only at the first ``--``.

    Doing this here rather than with ``nargs=argparse.REMAINDER`` is what
    keeps the two ``--json`` meanings apart: REMAINDER starts consuming at
    the first argument it does not recognize as an option *of the parser*,
    so ``plugin run <id> --json`` would hand ``--json`` to the plugin and
    silently disable the tool's own JSON output.
    """
    tokens = list(argv)
    if tokens[:2] != ["plugin", "run"] or "--" not in tokens:
        return [], tokens

    separator = tokens.index("--")
    return tokens[separator + 1 :], tokens[:separator]


def main(argv: Sequence[str] | None = None, out: TextIO = sys.stdout) -> int:
    """CLI entry point. Returns exit code."""
    parser = build_parser()
    argv_list = list(argv) if argv is not None else sys.argv[1:]
    plugin_args, tool_argv = _split_plugin_passthrough(argv_list)
    args = parser.parse_args(tool_argv)
    # Always present so a handler never has to guess; only ``plugin run``
    # puts anything in it.
    args.plugin_args = plugin_args

    action_id = getattr(args, "action_id", None)

    # Handle deprecated aliases
    if isinstance(action_id, str) and action_id.startswith("deprecated:"):
        old = action_id.split(":", 1)[1]
        print(
            f"warning: '{old}' is deprecated. Use the new command syntax instead.",
            file=sys.stderr,
        )
        return _handle_deprecated(old, args, out)

    if action_id == "about":
        from avbpowertool._version import __version__

        print(f"AVBPowerTool {__version__}", file=out)
        return 0

    if action_id is None:
        # No command: launch TUI
        from avbpowertool.bootstrap import bootstrap
        from avbpowertool.presentation.tui.app import App

        ws = bootstrap()
        app = App(ws)
        app.run()
        return 0

    # CLI mode: bootstrap wires logging (it is TUI-only otherwise) so the
    # invoked command is audited even before any handler runs.
    from avbpowertool.bootstrap import bootstrap
    from avbpowertool.presentation import audit
    from avbpowertool.presentation.cli.handlers import dispatch

    bootstrap()
    audit.log_cli_command(argv_list)

    # Handle --execute flag for sign
    if action_id == ActionId.IMAGE_SIGN and getattr(args, "execute", False):
        args.dry_run = False

    code = dispatch(args, out)
    audit.log_session_end("cli", f"exit_code={code}")
    return code


def _handle_deprecated(old: str, args: argparse.Namespace, out: TextIO) -> int:
    """Map old commands to new action IDs."""
    # For now, just redirect
    mapping = {
        "read": ActionId.IMAGE_INSPECT,
        "sign": ActionId.IMAGE_SIGN,
        "get_all_config": ActionId.CONFIG_LIST,
        "check_l10n": "settings.check_l10n",
    }
    action = mapping.get(old)
    if action is None:
        print(f"error: unknown deprecated command '{old}'", file=sys.stderr)
        return 2

    from avbpowertool.bootstrap import bootstrap
    from avbpowertool.presentation import audit

    # CLI mode: wire logging so the deprecated invocation is audited too.
    bootstrap()
    audit.log_cli_command([old, *(getattr(args, "rest", []) or [])])
    audit.audit_logger().warning("cli deprecated.command: %s mapped to %s", old, action)

    # Re-dispatch with mapped action
    args.action_id = action
    # Ensure images is a tuple for image commands
    if getattr(args, "images", None) is None:
        args.images = getattr(args, "rest", []) or []
    from avbpowertool.presentation.cli.handlers import dispatch

    code = dispatch(args, out)
    audit.log_session_end("cli", f"exit_code={code}")
    return code


if __name__ == "__main__":
    sys.exit(main())
