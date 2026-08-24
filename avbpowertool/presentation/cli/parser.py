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
        "--remove-footers", action="store_true", help="Remove existing footers first"
    )
    p_img_sign.add_argument("--json", action="store_true", help="JSON output")
    p_img_sign.set_defaults(action_id=ActionId.IMAGE_SIGN)

    # --- config ---
    p_config = sub.add_parser("config", help="Configuration operations")
    cfg_sub = p_config.add_subparsers(dest="config_command", required=True)

    # config show
    p_cfg_show = cfg_sub.add_parser("show", help="Show current config")
    p_cfg_show.add_argument("--json", action="store_true", help="JSON output")
    p_cfg_show.set_defaults(action_id=ActionId.CONFIG_SHOW)

    # config validate
    p_cfg_val = cfg_sub.add_parser("validate", help="Validate config against workspace")
    p_cfg_val.add_argument("--json", action="store_true", help="JSON output")
    p_cfg_val.set_defaults(action_id=ActionId.CONFIG_VALIDATE)

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
            "kernel_cmdlines=a,b (repeatable; booleans: true/false)"
        ),
    )
    p_cfg_edit.add_argument("--json", action="store_true", help="JSON output")
    p_cfg_edit.set_defaults(action_id=ActionId.CONFIG_EDIT)

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


def main(argv: Sequence[str] | None = None, out: TextIO = sys.stdout) -> int:
    """CLI entry point. Returns exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

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

    # Handle --execute flag for sign
    if action_id == ActionId.IMAGE_SIGN and getattr(args, "execute", False):
        args.dry_run = False

    from avbpowertool.presentation.cli.handlers import dispatch

    return dispatch(args, out)


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

    # Re-dispatch with mapped action
    args.action_id = action
    # Ensure images is a tuple for image commands
    if getattr(args, "images", None) is None:
        args.images = getattr(args, "rest", []) or []
    from avbpowertool.presentation.cli.handlers import dispatch

    return dispatch(args, out)


if __name__ == "__main__":
    sys.exit(main())
