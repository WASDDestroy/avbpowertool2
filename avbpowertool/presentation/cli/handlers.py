"""CLI handlers — build requests, call use cases, render results."""

from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path
from typing import Any, TextIO, cast

from avbpowertool.application.commands import (
    CheckChainsRequest,
    ConfigCreateFromImagesRequest,
    ConfigCreateRequest,
    ConfigEditRequest,
    ConfigExportRequest,
    ConfigImportRequest,
    ConfigMigrateRequest,
    ConfigShowRequest,
    ConfigValidateRequest,
    InspectImagesRequest,
    KeyAddRequest,
    KeyDiscoveryRequest,
    KeyEnsurePublicRequest,
    KeyListRequest,
    KeyRemoveRequest,
    LegacyImportRequest,
    PluginInstallRequest,
    PluginListRequest,
    PluginPackRequest,
    PluginRunRequest,
    PluginUninstallRequest,
    ProfileActivateRequest,
    ProfileDeleteRequest,
    ProfileListRequest,
    ProfileRenameRequest,
    SignImagesRequest,
)
from avbpowertool.application.services.check_chains import CheckChainsUseCase
from avbpowertool.application.services.config_auto_create import (
    ConfigCreateFromImagesUseCase,
)
from avbpowertool.application.services.inspect_images import InspectImagesUseCase
from avbpowertool.application.services.manage_configs import (
    ConfigCreateUseCase,
    ConfigEditUseCase,
    ConfigExportUseCase,
    ConfigImportUseCase,
    ConfigMigrateUseCase,
    ConfigShowUseCase,
    ConfigValidateUseCase,
    LegacyConfigImportUseCase,
)
from avbpowertool.application.services.manage_keys import (
    KeyAddUseCase,
    KeyDiscoveryUseCase,
    KeyEnsurePublicUseCase,
    KeyListUseCase,
    KeyRemoveUseCase,
)
from avbpowertool.application.services.manage_plugins import (
    PluginInstallUseCase,
    PluginListUseCase,
    PluginPackUseCase,
    PluginRunUseCase,
    PluginUninstallUseCase,
)
from avbpowertool.application.services.manage_profiles import (
    ProfileActivateUseCase,
    ProfileDeleteUseCase,
    ProfileListUseCase,
    ProfileRenameUseCase,
)
from avbpowertool.application.services.sign_images import SignImagesUseCase
from avbpowertool.infrastructure.avbtool.runner import SubprocessAvbTool
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.persistence.profile_repository import ProfileRepository
from avbpowertool.infrastructure.plugins.runner import SubprocessPluginRunner
from avbpowertool.presentation import audit
from avbpowertool.presentation.actions import ActionId
from avbpowertool.presentation.cli.renderer import (
    exit_code_from_issues,
    render_config_check_chains,
    render_config_create,
    render_config_create_from_images,
    render_config_delete,
    render_config_edit,
    render_config_migrate,
    render_config_rename,
    render_config_show,
    render_config_validate,
    render_export,
    render_import,
    render_inspect,
    render_key_add,
    render_key_discovery,
    render_key_ensure_public,
    render_key_list,
    render_key_remove,
    render_legacy_import,
    render_plugin_install,
    render_plugin_list,
    render_plugin_pack,
    render_plugin_run,
    render_plugin_uninstall,
    render_profile_activate,
    render_profile_list,
    render_sign,
)
from avbpowertool.presentation.i18n import get_current_language


def _create_workspace() -> WorkspacePaths:
    return WorkspacePaths.discover()


def _create_avb_tool(workspace: WorkspacePaths) -> SubprocessAvbTool:
    return SubprocessAvbTool(workspace.avbtool_script)


def _create_plugin_runner() -> SubprocessPluginRunner:
    """Build the plugin runner; a factory so tests can monkeypatch it."""
    return SubprocessPluginRunner()


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def dispatch(args: Namespace, out: TextIO = sys.stdout) -> int:
    """Dispatch parsed CLI args to the appropriate handler. Returns exit code."""
    action_id = getattr(args, "action_id", None)
    if action_id is None:
        audit.audit_logger().warning("cli dispatch.refused: no action_id")
        return 2

    as_json = getattr(args, "json", False)
    workspace = _create_workspace()

    handler_map = {
        ActionId.IMAGE_INSPECT: _handle_inspect,
        ActionId.IMAGE_SIGN: _handle_sign,
        ActionId.CONFIG_SHOW: _handle_config_show,
        ActionId.CONFIG_VALIDATE: _handle_config_validate,
        ActionId.CONFIG_CREATE: _handle_config_create,
        ActionId.CONFIG_LIST: _handle_config_list,
        ActionId.CONFIG_ACTIVATE: _handle_config_activate,
        ActionId.CONFIG_IMPORT: _handle_config_import,
        ActionId.CONFIG_IMPORT_LEGACY: _handle_config_import_legacy,
        ActionId.CONFIG_EXPORT: _handle_config_export,
        ActionId.CONFIG_MIGRATE: _handle_config_migrate,
        ActionId.CONFIG_EDIT: _handle_config_edit,
        ActionId.CONFIG_RENAME: _handle_config_rename,
        ActionId.CONFIG_CHECK_CHAINS: _handle_config_check_chains,
        ActionId.CONFIG_DELETE: _handle_config_delete,
        ActionId.KEY_LIST: _handle_key_list,
        ActionId.KEY_DISCOVER: _handle_key_discover,
        ActionId.KEY_ENSURE_PUBLIC: _handle_key_ensure_public,
        ActionId.KEY_ADD: _handle_key_add,
        ActionId.KEY_REMOVE: _handle_key_remove,
        ActionId.PLUGIN_LIST: _handle_plugin_list,
        ActionId.PLUGIN_PACK: _handle_plugin_pack,
        ActionId.PLUGIN_INSTALL: _handle_plugin_install,
        ActionId.PLUGIN_UNINSTALL: _handle_plugin_uninstall,
        ActionId.PLUGIN_RUN: _handle_plugin_run,
    }

    handler = handler_map.get(action_id)
    if handler is None:
        audit.audit_logger().warning("cli dispatch.refused: unsupported action %s", action_id)
        print(f"error: unsupported action {action_id}", file=sys.stderr)
        return 2

    audit.log_action_start("cli", str(action_id), _request_summary(args))
    code = handler(args, workspace, as_json, out)
    audit.log_action_end("cli", str(action_id), f"exit_code={code}")
    return code


def _request_summary(args: Namespace) -> str:
    """One-line rendering of the parsed args for the audit trail."""
    parts: list[str] = []
    items: list[tuple[str, Any]] = sorted((str(k), v) for k, v in vars(args).items())
    for key, value in items:
        if key in ("action_id", "json", "rest") or key.startswith("_"):
            continue
        if value is True:
            parts.append(f"--{key.replace('_', '-')}")
        elif value is False or value is None:
            continue
        elif isinstance(value, list):
            # argparse list values (images, --set updates) are always str.
            str_list = cast("list[str]", value)
            parts.append(" ".join(str_list))
        else:
            parts.append(str(value))
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _handle_inspect(args: Namespace, workspace: WorkspacePaths, as_json: bool, out: TextIO) -> int:
    uc = InspectImagesUseCase(workspace, _create_avb_tool(workspace))
    request = InspectImagesRequest(
        image_names=tuple(args.images),
        with_cert=getattr(args, "cert", False),
    )
    result = uc.execute(request)
    render_inspect(result, as_json, out)
    return exit_code_from_issues(result.issues)


def _handle_sign(args: Namespace, workspace: WorkspacePaths, as_json: bool, out: TextIO) -> int:
    dry_run = getattr(args, "dry_run", True)
    yes = getattr(args, "yes", False)

    # Confirmation for real signing
    if not dry_run and not yes:
        print(
            "This will modify image files. Use --yes to confirm.",
            file=sys.stderr,
        )
        return 1

    uc = SignImagesUseCase(workspace, _create_avb_tool(workspace))
    request = SignImagesRequest(
        image_names=tuple(args.images),
        profile_id=getattr(args, "profile", "current"),
        dry_run=dry_run,
        remove_existing_footers=getattr(args, "remove_footers", False),
    )
    result = uc.execute(request)
    render_sign(result, as_json, out)
    return exit_code_from_issues(result.issues)


def _handle_config_show(
    args: Namespace, workspace: WorkspacePaths, as_json: bool, out: TextIO
) -> int:
    uc = ConfigShowUseCase(workspace)
    request = ConfigShowRequest(profile_id=getattr(args, "profile", "current"))
    result = uc.execute(request)
    render_config_show(result, as_json, out)
    return exit_code_from_issues(result.issues)


def _handle_config_validate(
    args: Namespace, workspace: WorkspacePaths, as_json: bool, out: TextIO
) -> int:
    uc = ConfigValidateUseCase(workspace)
    request = ConfigValidateRequest(profile_id=getattr(args, "profile", "current"))
    result = uc.execute(request)
    render_config_validate(result, as_json, out)
    # config.validate reports its problems as data (missing_images /
    # missing_keys) rather than as issues, so every kind of problem has to
    # map to the same non-zero exit code a script can gate on.
    if result.issues or result.missing_images or result.missing_keys:
        return 1
    return 0


def _parse_image_names(values: list[str] | None) -> tuple[str, ...]:
    """Flatten repeated ``--images a,b`` values into bare image stems.

    Both ``boot`` and ``boot.img`` are accepted; duplicates keep their
    first position so the scan order stays predictable.
    """
    names: list[str] = []
    for value in values or []:
        for item in value.split(","):
            name = item.strip()
            if name.endswith(".img"):
                name = name[: -len(".img")]
            if name and name not in names:
                names.append(name)
    return tuple(names)


def _handle_config_create(
    args: Namespace, workspace: WorkspacePaths, as_json: bool, out: TextIO
) -> int:
    profile_id = args.profile_id
    # None means "no --from-images": keep the plain empty-profile path.
    # "" means the flag was given without a directory -> workspace Images/.
    from_images = getattr(args, "from_images", None)
    if from_images is not None:
        image_dir = workspace.images if from_images == "" else Path(from_images)
        uc = ConfigCreateFromImagesUseCase(workspace, _create_avb_tool(workspace))
        request = ConfigCreateFromImagesRequest(
            profile_id=profile_id,
            profile_name=getattr(args, "profile_name", None) or "",
            image_dir=image_dir,
            image_names=_parse_image_names(getattr(args, "images", None)),
            key_id=getattr(args, "key_id", None),
            resolve_chains=getattr(args, "resolve_chains", True),
            # Only --include-fallback restores the wizard's "include every
            # other partition" behaviour.
            allow_fallback=getattr(args, "include_fallback", False),
            skip_non_avb=getattr(args, "skip_non_avb", False),
            overwrite=getattr(args, "overwrite", False),
            # Scripted creation must not silently change the active profile.
            activate=getattr(args, "activate", False),
        )
        result = uc.execute(request)
        render_config_create_from_images(result, as_json, out)
        return exit_code_from_issues(result.issues)

    # --overwrite only means something when the partitions come from images.
    # Accepting it here would silently ignore the flag (argparse already
    # accepted it), so reject it the way a usage error is rejected.
    if getattr(args, "overwrite", False):
        print("error: --overwrite requires --from-images", file=sys.stderr)
        return 2

    uc = ConfigCreateUseCase(workspace)
    request = ConfigCreateRequest(
        profile_id=profile_id,
        # The use case keeps its strict "empty name is invalid" semantics;
        # the CLI is what defaults the name to the id.
        profile_name=getattr(args, "profile_name", None) or profile_id,
        allow_empty=getattr(args, "allow_empty", False),
        # Scripted creation must not silently change the active profile.
        activate=getattr(args, "activate", False),
    )
    result = uc.execute(request)
    render_config_create(result, as_json, out)
    return exit_code_from_issues(result.issues)


def _handle_config_list(
    args: Namespace, workspace: WorkspacePaths, as_json: bool, out: TextIO
) -> int:
    uc = ProfileListUseCase(workspace)
    result = uc.execute(ProfileListRequest())
    render_profile_list(result, as_json, out)
    return exit_code_from_issues(result.issues)


def _handle_config_activate(
    args: Namespace, workspace: WorkspacePaths, as_json: bool, out: TextIO
) -> int:
    uc = ProfileActivateUseCase(workspace)
    request = ProfileActivateRequest(profile_id=args.profile)
    result = uc.execute(request)
    render_profile_activate(result, as_json, out)
    return exit_code_from_issues(result.issues)


def _handle_config_import(
    args: Namespace, workspace: WorkspacePaths, as_json: bool, out: TextIO
) -> int:
    uc = ConfigImportUseCase(workspace)
    request = ConfigImportRequest(archive_path=args.archive)
    result = uc.execute(request)
    render_import(result, as_json, out)
    return exit_code_from_issues(result.issues)


def _handle_config_import_legacy(
    args: Namespace, workspace: WorkspacePaths, as_json: bool, out: TextIO
) -> int:
    uc = LegacyConfigImportUseCase(workspace)
    request = LegacyImportRequest(
        archive_path=args.archive,
        new_profile_id=getattr(args, "profile_id", None),
        activate=not getattr(args, "no_activate", False),
    )
    result = uc.execute(request)
    render_legacy_import(result, as_json, out)
    return exit_code_from_issues(result.issues)


def _handle_config_export(
    args: Namespace, workspace: WorkspacePaths, as_json: bool, out: TextIO
) -> int:
    uc = ConfigExportUseCase(workspace)
    request = ConfigExportRequest(
        profile_id=args.profile,
        output_path=getattr(args, "output", None),
    )
    result = uc.execute(request)
    render_export(result, as_json, out)
    return exit_code_from_issues(result.issues)


def _handle_config_migrate(
    args: Namespace, workspace: WorkspacePaths, as_json: bool, out: TextIO
) -> int:
    uc = ConfigMigrateUseCase(workspace)
    request = ConfigMigrateRequest(profile_id=getattr(args, "profile", "current"))
    result = uc.execute(request)
    render_config_migrate(result, as_json, out)
    return exit_code_from_issues(result.issues)


def _split_field_item(flag: str, item: str) -> tuple[str, str] | None:
    """Split a ``FIELD=ITEM`` argument, reporting malformed input on stderr."""
    field_name, separator, value = item.partition("=")
    field_name = field_name.strip()
    if not separator or not field_name:
        print(f"error: {flag} expects FIELD=ITEM, got {item!r}", file=sys.stderr)
        return None
    return field_name, value


def _handle_config_edit(
    args: Namespace, workspace: WorkspacePaths, as_json: bool, out: TextIO
) -> int:
    updates: dict[str, str] = {}
    for item in getattr(args, "updates", []):
        pair = _split_field_item("--set", item)
        if pair is None:
            return 2
        updates[pair[0]] = pair[1]

    unset: list[str] = []
    for item in getattr(args, "unsets", []):
        field_name = item.strip()
        if not field_name:
            print(f"error: --unset expects FIELD, got {item!r}", file=sys.stderr)
            return 2
        unset.append(field_name)

    appends: list[tuple[str, str]] = []
    for item in getattr(args, "appends", []):
        pair = _split_field_item("--append", item)
        if pair is None:
            return 2
        appends.append(pair)

    removes: list[tuple[str, str]] = []
    for item in getattr(args, "removes", []):
        pair = _split_field_item("--remove", item)
        if pair is None:
            return 2
        removes.append(pair)

    uc = ConfigEditUseCase(workspace)
    request = ConfigEditRequest(
        profile_id=getattr(args, "profile", "current"),
        partition_name=args.partition,
        updates=updates,
        unset=tuple(unset),
        appends=tuple(appends),
        removes=tuple(removes),
    )
    result = uc.execute(request)
    render_config_edit(result, as_json, out)
    return exit_code_from_issues(result.issues)


def _handle_config_rename(
    args: Namespace, workspace: WorkspacePaths, as_json: bool, out: TextIO
) -> int:
    uc = ProfileRenameUseCase(workspace)
    request = ProfileRenameRequest(
        profile_id=args.old_profile_id,
        new_profile_id=args.new_profile_id,
        new_name=getattr(args, "new_name", None),
    )
    result = uc.execute(request)
    # The active profile is read after the call so the text output can show
    # whether .active-profile followed the rename.
    render_config_rename(
        result,
        as_json,
        out,
        active_profile_id=ProfileRepository(workspace).get_active_profile_id(),
    )
    return exit_code_from_issues(result.issues)


def _handle_config_delete(
    args: Namespace, workspace: WorkspacePaths, as_json: bool, out: TextIO
) -> int:
    # Deleting a profile destroys its private keys, so --yes is a hard gate:
    # without it nothing is touched and no use case is even built.
    if not getattr(args, "yes", False):
        print(
            "This deletes the profile directory including its private keys. Use --yes to confirm.",
            file=sys.stderr,
        )
        return 1

    uc = ProfileDeleteUseCase(workspace)
    request = ProfileDeleteRequest(
        profile_id=args.profile,
        force=getattr(args, "force", False),
    )
    result = uc.execute(request)
    render_config_delete(result, as_json, out)
    return exit_code_from_issues(result.issues)


def _handle_config_check_chains(
    args: Namespace, workspace: WorkspacePaths, as_json: bool, out: TextIO
) -> int:
    uc = CheckChainsUseCase(workspace, _create_avb_tool(workspace))
    request = CheckChainsRequest(profile_id=getattr(args, "profile", "current"))
    result = uc.execute(request)
    render_config_check_chains(result, as_json, out)
    return exit_code_from_issues(result.issues)


def _handle_key_list(args: Namespace, workspace: WorkspacePaths, as_json: bool, out: TextIO) -> int:
    uc = KeyListUseCase(workspace)
    request = KeyListRequest(profile_id=getattr(args, "profile", "current"))
    result = uc.execute(request)
    render_key_list(result, as_json, out)
    return exit_code_from_issues(result.issues)


def _handle_key_discover(
    args: Namespace, workspace: WorkspacePaths, as_json: bool, out: TextIO
) -> int:
    uc = KeyDiscoveryUseCase(workspace)
    request = KeyDiscoveryRequest(
        profile_id=getattr(args, "profile", "current"),
        merge=getattr(args, "merge", True),
    )
    result = uc.execute(request)
    render_key_discovery(result, as_json, out)
    return exit_code_from_issues(result.issues)


def _handle_key_ensure_public(
    args: Namespace, workspace: WorkspacePaths, as_json: bool, out: TextIO
) -> int:
    uc = KeyEnsurePublicUseCase(workspace, _create_avb_tool(workspace))
    request = KeyEnsurePublicRequest(profile_id=getattr(args, "profile", "current"))
    result = uc.execute(request)
    render_key_ensure_public(result, as_json, out)
    return exit_code_from_issues(result.issues)


def _handle_key_add(args: Namespace, workspace: WorkspacePaths, as_json: bool, out: TextIO) -> int:
    uc = KeyAddUseCase(workspace)
    request = KeyAddRequest(
        profile_id=getattr(args, "profile", "current"),
        key_id=args.key_id,
        private_key_filename=args.private_key_filename,
    )
    result = uc.execute(request)
    render_key_add(result, as_json, out)
    return exit_code_from_issues(result.issues)


def _handle_key_remove(
    args: Namespace, workspace: WorkspacePaths, as_json: bool, out: TextIO
) -> int:
    uc = KeyRemoveUseCase(workspace)
    request = KeyRemoveRequest(
        profile_id=getattr(args, "profile", "current"),
        key_id=args.key_id,
    )
    result = uc.execute(request)
    render_key_remove(result, as_json, out)
    return exit_code_from_issues(result.issues)


# ---------------------------------------------------------------------------
# Plugins
# ---------------------------------------------------------------------------


def _handle_plugin_list(
    args: Namespace, workspace: WorkspacePaths, as_json: bool, out: TextIO
) -> int:
    # The language is injected, not looked up: the application layer never
    # imports the presentation layer.
    uc = PluginListUseCase(workspace, language=get_current_language())
    result = uc.execute(PluginListRequest())
    render_plugin_list(result, as_json, out)
    return exit_code_from_issues(result.issues)


def _handle_plugin_pack(
    args: Namespace, workspace: WorkspacePaths, as_json: bool, out: TextIO
) -> int:
    uc = PluginPackUseCase(workspace)
    request = PluginPackRequest(
        source=args.source,
        output_path=getattr(args, "output", None),
    )
    result = uc.execute(request)
    render_plugin_pack(result, as_json, out)
    return exit_code_from_issues(result.issues)


def _handle_plugin_install(
    args: Namespace, workspace: WorkspacePaths, as_json: bool, out: TextIO
) -> int:
    uc = PluginInstallUseCase(workspace)
    request = PluginInstallRequest(
        source_path=args.source,
        force=getattr(args, "force", False),
    )
    result = uc.execute(request)
    render_plugin_install(result, as_json, out)
    return exit_code_from_issues(result.issues)


def _handle_plugin_uninstall(
    args: Namespace, workspace: WorkspacePaths, as_json: bool, out: TextIO
) -> int:
    # A plugin directory can hold key material and other bundled files, so
    # --yes is a hard gate: without it nothing is touched and no use case is
    # even built (same shape as ``config delete``).
    if not getattr(args, "yes", False):
        print(
            "This deletes the plugin directory including any bundled files. Use --yes to confirm.",
            file=sys.stderr,
        )
        return 1

    uc = PluginUninstallUseCase(workspace)
    request = PluginUninstallRequest(plugin_id=args.plugin_id)
    result = uc.execute(request)
    render_plugin_uninstall(result, as_json, out)
    return exit_code_from_issues(result.issues)


def _handle_plugin_run(
    args: Namespace, workspace: WorkspacePaths, as_json: bool, out: TextIO
) -> int:
    uc = PluginRunUseCase(
        workspace,
        _create_plugin_runner(),
        language=get_current_language(),
    )
    request = PluginRunRequest(
        plugin_id=args.plugin_id,
        # main() filled this from everything after the first ``--``.
        args=tuple(getattr(args, "plugin_args", ()) or ()),
    )
    result = uc.execute(request)
    render_plugin_run(result, as_json, out)

    # A non-zero exit code is the plugin's own verdict and is passed through
    # untouched; only an issue means the plugin never ran, and then the
    # ``exit_code`` is the placeholder -1 that must not reach the shell.
    if result.issues:
        return exit_code_from_issues(result.issues)
    return result.exit_code
