"""Plugins view — list, run, install, and uninstall plugins.

The page is a single selector: one runnable row per installed plugin,
followed by the ``install`` and ``uninstall`` entries.  Installing asks for
a path (the TUI has no file browser), uninstalling picks from a second
selector and asks for a confirmation; both are plain use-case calls, so
curses stays in charge for their whole duration.

Running a plugin hands the terminal over to it (see
:func:`_run_with_terminal_handover`): plugins are interactive CLIs, the
subprocess runner inherits stdio, so curses has to be suspended for the
duration of the run.  The TUI never passes arguments to a plugin — use
``avbpowertool plugin run <id> -- …`` when arguments are needed.

A downgrade install is never silent: the use case refuses it with
``plugin.downgrade``, the page shows both versions, and only an explicit
confirmation retries the install with ``force``.  Declining writes nothing.
The CLI's ``plugin install --force`` is the equivalent for scripted use.
"""

from __future__ import annotations

import contextlib
import curses
import logging
from collections.abc import Callable, Sequence
from typing import Literal, NamedTuple, TypeVar

from avbpowertool.application.commands import (
    PluginInstallRequest,
    PluginInstallResult,
    PluginListItem,
    PluginListRequest,
    PluginRunRequest,
    PluginUninstallRequest,
    PluginUninstallResult,
)
from avbpowertool.application.ports import AvbToolPort
from avbpowertool.application.services.manage_plugins import (
    PluginInstallUseCase,
    PluginListUseCase,
    PluginRunUseCase,
    PluginUninstallUseCase,
)
from avbpowertool.domain.models import OperationIssue
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.plugins.runner import SubprocessPluginRunner
from avbpowertool.presentation import audit
from avbpowertool.presentation.i18n import _, get_current_language
from avbpowertool.presentation.tui.widgets import (
    SelectorWidget,
    confirm_dialog,
    input_prompt,
    message_screen,
)

logger = logging.getLogger(__name__)
audit_log = audit.audit_logger()

T = TypeVar("T")

#: What choosing a selector row does.
_RowKind = Literal["plugin", "install", "uninstall", "issues"]

#: The error code the install use case answers a downgrade with.
DOWNGRADE_CODE = "plugin.downgrade"


class _Row(NamedTuple):
    """One selector row: the label to draw plus what choosing it does."""

    label: str
    kind: _RowKind
    plugin: PluginListItem | None = None


def _plugin_label(plugin: PluginListItem) -> str:
    """``Name (plugin_id) v<version>`` — plugin data only, no translatable words."""
    label = f"{plugin.name} ({plugin.plugin_id}) v{plugin.version}"
    if plugin.version_name:
        label += f" ({plugin.version_name})"
    return label


def _version_label(result: PluginInstallResult) -> str:
    """``2 (2.1.0)`` — the installed version, with its name when it declares one."""
    if result.version_name:
        return f"{result.version} ({result.version_name})"
    return str(result.version)


def _issue_lines(issues: tuple[OperationIssue, ...]) -> list[str]:
    """One ``[error_code] message`` line per issue (data, not UI text)."""
    return [f"  [{issue.error_code}] {issue.message}" for issue in issues]


def _run_with_terminal_handover(stdscr: object, action: Callable[[], T]) -> T:
    """Run *action* with curses suspended so the plugin owns the terminal.

    ``def_prog_mode`` saves the curses state, ``endwin`` restores the
    terminal to its pre-curses mode, and the ``finally`` block puts the
    screen back the way curses left it — so an interactive plugin can
    read from and write to the terminal while it runs.

    Every curses call here is best effort: on a terminal that cannot be
    handed over (no TTY, a curses build without program modes) the action
    still runs, and only a failure *inside* the action reaches the caller.
    """
    window: curses.window = stdscr  # type: ignore[assignment]
    with contextlib.suppress(curses.error):
        curses.def_prog_mode()
    with contextlib.suppress(curses.error):
        curses.endwin()
    try:
        return action()
    finally:
        with contextlib.suppress(curses.error):
            curses.reset_prog_mode()
        with contextlib.suppress(curses.error):
            window.refresh()


def show(stdscr: object, ws: WorkspacePaths, avb: AvbToolPort) -> None:
    """Plugins view: run, install, or uninstall a plugin."""
    stdscr_c: curses.window = stdscr  # type: ignore[assignment]
    language = get_current_language()

    list_result = PluginListUseCase(ws, language=language).execute(PluginListRequest())
    manifest_issue_lines = _issue_lines(list_result.issues)
    plugins = list(list_result.plugins)

    if not plugins:
        # Nothing to run — but installing has to stay reachable, so the page
        # only shows the hint and then offers the install/uninstall entries.
        audit_log.debug("tui message: Plugins (empty)")
        lines = [_("plugin.none"), _("plugin.none_hint")]
        if manifest_issue_lines:
            lines.append(_("plugin.manifest_issues"))
            lines.extend(manifest_issue_lines)
        message_screen(stdscr_c, _("plugin.title"), lines)

    rows = [_Row(_plugin_label(plugin), "plugin", plugin) for plugin in plugins]
    rows.append(_Row(_("plugin.install"), "install"))
    rows.append(_Row(_("plugin.uninstall"), "uninstall"))
    if manifest_issue_lines:
        # A manifest that could not be parsed is reported here rather than
        # dropped; its rows are informational and never act on anything.
        rows.append(_Row(_("plugin.manifest_issues"), "issues"))
        rows.extend(_Row(line, "issues") for line in manifest_issue_lines)

    sel = SelectorWidget(_("plugin.select"), [row.label for row in rows])
    choice = sel.run(stdscr_c)
    if not choice:
        audit_log.debug("tui select.cancel: Plugins")
        return

    index = choice[0]
    if not 0 <= index < len(rows):
        return
    row = rows[index]
    audit_log.debug("tui select.choose: Plugins -> %s", row.label)

    match row.kind:
        case "plugin":
            if row.plugin is not None:
                _run_plugin(stdscr_c, ws, row.plugin, language, manifest_issue_lines)
        case "install":
            _install(stdscr_c, ws)
        case "uninstall":
            _uninstall(stdscr_c, ws, plugins)
        case "issues":
            message_screen(
                stdscr_c,
                _("plugin.title"),
                [_("plugin.manifest_issues"), *manifest_issue_lines],
            )


def _run_plugin(
    stdscr: curses.window,
    ws: WorkspacePaths,
    plugin: PluginListItem,
    language: str,
    manifest_issue_lines: Sequence[str],
) -> None:
    """Confirm and run one installed plugin (the terminal is handed over)."""
    if not confirm_dialog(stdscr, _("plugin.confirm_run")):
        return

    audit.log_action_start("tui", "plugin.run", plugin.plugin_id)
    use_case = PluginRunUseCase(ws, SubprocessPluginRunner(), language=language)
    # The TUI never passes arguments: a plugin that needs them is run from
    # the CLI (``plugin run <id> -- …``).
    request = PluginRunRequest(plugin_id=plugin.plugin_id, args=())

    try:
        result = _run_with_terminal_handover(stdscr, lambda: use_case.execute(request))
    except KeyboardInterrupt:
        audit_log.warning("tui action.interrupted: plugin.run %s", plugin.plugin_id)
        audit.log_action_end("tui", "plugin.run", "interrupted")
        message_screen(stdscr, _("plugin.run_title"), [_("plugin.interrupted")])
        return
    except Exception as exc:
        logger.exception("Plugin %s could not be run", plugin.plugin_id)
        audit.log_action_end("tui", "plugin.run", f"error: {exc}")
        message_screen(
            stdscr,
            _("plugin.run_title"),
            [_("plugin.run_failed"), str(exc)],
        )
        return

    lines = [_plugin_label(plugin), _("plugin.exit_code", code=result.exit_code)]
    if result.issues:
        lines.append(_("plugin.run_failed"))
        lines.extend(_issue_lines(result.issues))
    if manifest_issue_lines:
        lines.append(_("plugin.manifest_issues"))
        lines.extend(manifest_issue_lines)

    audit.log_action_end("tui", "plugin.run", f"exit_code={result.exit_code}")
    message_screen(stdscr, _("plugin.run_title"), lines)


def _install(stdscr: curses.window, ws: WorkspacePaths) -> None:
    """Ask for a directory/zip path, install it, and confirm a downgrade.

    The TUI has no file browser, so the source path is typed into an input
    prompt.  A refused downgrade is shown with both versions and only
    retried (with ``force``) after an explicit confirmation; declining
    leaves the workspace untouched.
    """
    source_path = input_prompt(stdscr, _("plugin.install_path"))
    if not source_path:
        audit_log.debug("tui input.cancel: plugin.install")
        return

    audit.log_action_start("tui", "plugin.install", source_path)
    use_case = PluginInstallUseCase(ws)
    result = use_case.execute(PluginInstallRequest(source_path=source_path))

    if result.installed:
        audit.log_action_end("tui", "plugin.install", f"installed {result.plugin_id}")
        _show_install_result(stdscr, result, downgraded=False)
        return

    downgrade = next((issue for issue in result.issues if issue.error_code == DOWNGRADE_CODE), None)
    if downgrade is None:
        audit.log_action_end("tui", "plugin.install", "failed")
        _show_install_result(stdscr, result, downgraded=False)
        return

    # A downgrade is never silent: show the versions first, then ask.
    message_screen(
        stdscr,
        _("plugin.downgrade_title"),
        [downgrade.message, *_issue_lines(tuple(i for i in result.issues if i is not downgrade))],
    )
    if not confirm_dialog(stdscr, _("plugin.downgrade_confirm")):
        audit.log_action_end("tui", "plugin.install", "downgrade declined")
        message_screen(stdscr, _("plugin.install_title"), [_("plugin.cancelled")])
        return

    forced = use_case.execute(PluginInstallRequest(source_path=source_path, force=True))
    audit.log_action_end(
        "tui",
        "plugin.install",
        f"downgraded {forced.plugin_id}" if forced.installed else "failed",
    )
    _show_install_result(stdscr, forced, downgraded=True)


def _show_install_result(
    stdscr: curses.window, result: PluginInstallResult, *, downgraded: bool
) -> None:
    """Show what an install attempt produced (success or ``[code] message``)."""
    lines: list[str] = []
    if result.installed:
        lines.append(
            _(
                "plugin.installed_ok",
                id=result.plugin_id,
                version=_version_label(result),
                files=result.file_count,
            )
        )
        if downgraded:
            lines.append(_("plugin.downgrade_installed"))
    else:
        lines.extend(_issue_lines(result.issues))
    message_screen(stdscr, _("plugin.install_title"), lines)


def _uninstall(
    stdscr: curses.window, ws: WorkspacePaths, plugins: Sequence[PluginListItem]
) -> None:
    """Pick an installed plugin from a second selector, confirm, then remove it."""
    if not plugins:
        message_screen(stdscr, _("plugin.uninstall_title"), [_("plugin.none")])
        return

    sel = SelectorWidget(_("plugin.uninstall"), [_plugin_label(plugin) for plugin in plugins])
    choice = sel.run(stdscr)
    if not choice:
        audit_log.debug("tui select.cancel: Plugins (uninstall)")
        return

    index = choice[0]
    if not 0 <= index < len(plugins):
        return
    plugin = plugins[index]
    audit_log.debug("tui select.choose: Plugins (uninstall) -> %s", plugin.plugin_id)

    if not confirm_dialog(stdscr, _("plugin.uninstall_confirm", id=plugin.plugin_id)):
        return

    audit.log_action_start("tui", "plugin.uninstall", plugin.plugin_id)
    result = PluginUninstallUseCase(ws).execute(PluginUninstallRequest(plugin_id=plugin.plugin_id))
    audit.log_action_end(
        "tui", "plugin.uninstall", f"removed {plugin.plugin_id}" if result.removed else "failed"
    )
    _show_uninstall_result(stdscr, result)


def _show_uninstall_result(stdscr: curses.window, result: PluginUninstallResult) -> None:
    """Show what an uninstall attempt produced (success or ``[code] message``)."""
    lines: list[str] = []
    if result.removed:
        lines.append(
            _(
                "plugin.uninstalled_ok",
                id=result.plugin_id,
                files=result.removed_files,
                bytes=result.removed_bytes,
            )
        )
    else:
        lines.extend(_issue_lines(result.issues))
    message_screen(stdscr, _("plugin.uninstall_title"), lines)
