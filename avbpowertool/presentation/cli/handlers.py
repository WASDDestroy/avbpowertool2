"""CLI handlers — build requests, call use cases, render results."""

from __future__ import annotations

import sys
from argparse import Namespace
from typing import TextIO

from avbpowertool.application.commands import (
    ConfigExportRequest,
    ConfigImportRequest,
    ConfigShowRequest,
    ConfigValidateRequest,
    InspectImagesRequest,
    LegacyImportRequest,
    ProfileActivateRequest,
    ProfileListRequest,
    SignImagesRequest,
)
from avbpowertool.application.services.inspect_images import InspectImagesUseCase
from avbpowertool.application.services.manage_configs import (
    ConfigExportUseCase,
    ConfigImportUseCase,
    ConfigShowUseCase,
    ConfigValidateUseCase,
    LegacyConfigImportUseCase,
)
from avbpowertool.application.services.manage_profiles import (
    ProfileActivateUseCase,
    ProfileListUseCase,
)
from avbpowertool.application.services.sign_images import SignImagesUseCase
from avbpowertool.infrastructure.avbtool.runner import SubprocessAvbTool
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.presentation.actions import ActionId
from avbpowertool.presentation.cli.renderer import (
    exit_code_from_issues,
    render_config_show,
    render_config_validate,
    render_export,
    render_import,
    render_inspect,
    render_legacy_import,
    render_profile_activate,
    render_profile_list,
    render_sign,
)


def _create_workspace() -> WorkspacePaths:
    return WorkspacePaths.discover()


def _create_avb_tool(workspace: WorkspacePaths) -> SubprocessAvbTool:
    return SubprocessAvbTool(workspace.avbtool_script)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def dispatch(args: Namespace, out: TextIO = sys.stdout) -> int:
    """Dispatch parsed CLI args to the appropriate handler. Returns exit code."""
    action_id = getattr(args, "action_id", None)
    if action_id is None:
        return 2

    as_json = getattr(args, "json", False)
    workspace = _create_workspace()

    handler_map = {
        ActionId.IMAGE_INSPECT: _handle_inspect,
        ActionId.IMAGE_SIGN: _handle_sign,
        ActionId.CONFIG_SHOW: _handle_config_show,
        ActionId.CONFIG_VALIDATE: _handle_config_validate,
        ActionId.CONFIG_LIST: _handle_config_list,
        ActionId.CONFIG_ACTIVATE: _handle_config_activate,
        ActionId.CONFIG_IMPORT: _handle_config_import,
        ActionId.CONFIG_IMPORT_LEGACY: _handle_config_import_legacy,
        ActionId.CONFIG_EXPORT: _handle_config_export,
    }

    handler = handler_map.get(action_id)
    if handler is None:
        print(f"error: unsupported action {action_id}", file=sys.stderr)
        return 2

    return handler(args, workspace, as_json, out)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _handle_inspect(args: Namespace, workspace: WorkspacePaths, as_json: bool, out: TextIO) -> int:
    uc = InspectImagesUseCase(workspace, _create_avb_tool(workspace))
    request = InspectImagesRequest(image_names=tuple(args.images))
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
    request = ConfigShowRequest()
    result = uc.execute(request)
    render_config_show(result, as_json, out)
    return exit_code_from_issues(result.issues)


def _handle_config_validate(
    args: Namespace, workspace: WorkspacePaths, as_json: bool, out: TextIO
) -> int:
    uc = ConfigValidateUseCase(workspace)
    request = ConfigValidateRequest()
    result = uc.execute(request)
    render_config_validate(result, as_json, out)
    if result.missing_images:
        return 2
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
