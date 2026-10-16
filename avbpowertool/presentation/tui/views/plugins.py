"""Plugins view — list the installed plugins and run one of them.

The TUI covers ``plugin list`` and ``plugin run`` only: installing and
uninstalling stay in the CLI, where a source path and the explicit
``--yes`` confirmation gate can be expressed.

Running a plugin hands the terminal over to it (see
:func:`_run_with_terminal_handover`): plugins are interactive CLIs, the
subprocess runner inherits stdio, so curses has to be suspended for the
duration of the run.  The TUI never passes arguments to a plugin — use
``avbpowertool plugin run <id> -- …`` when arguments are needed.
"""

from __future__ import annotations

import contextlib
import curses
import logging
from collections.abc import Callable
from typing import TypeVar

from avbpowertool.application.commands import (
    PluginListItem,
    PluginListRequest,
    PluginRunRequest,
)
from avbpowertool.application.ports import AvbToolPort
from avbpowertool.application.services.manage_plugins import (
    PluginListUseCase,
    PluginRunUseCase,
)
from avbpowertool.domain.models import OperationIssue
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.plugins.runner import SubprocessPluginRunner
from avbpowertool.presentation import audit
from avbpowertool.presentation.i18n import _, get_current_language
from avbpowertool.presentation.tui.widgets import (
    SelectorWidget,
    confirm_dialog,
    message_screen,
)

logger = logging.getLogger(__name__)
audit_log = audit.audit_logger()

T = TypeVar("T")


def _plugin_label(plugin: PluginListItem) -> str:
    """``Name (plugin_id)`` — plugin data only, no translatable words."""
    return f"{plugin.name} ({plugin.plugin_id})"


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
    """Plugins view: pick an installed plugin and run it."""
    stdscr_c: curses.window = stdscr  # type: ignore[assignment]
    language = get_current_language()

    list_result = PluginListUseCase(ws, language=language).execute(PluginListRequest())
    manifest_issue_lines = _issue_lines(list_result.issues)

    if not list_result.plugins:
        audit_log.debug("tui message: Plugins (empty)")
        lines = [_("plugin.none"), _("plugin.none_hint")]
        if manifest_issue_lines:
            lines.append(_("plugin.manifest_issues"))
            lines.extend(manifest_issue_lines)
        message_screen(stdscr_c, _("plugin.title"), lines)
        return

    plugins = list(list_result.plugins)
    items = [_plugin_label(plugin) for plugin in plugins]
    if manifest_issue_lines:
        # A manifest that could not be parsed is reported here rather than
        # dropped; its rows are informational and never run anything.
        items.append(_("plugin.manifest_issues"))
        items.extend(manifest_issue_lines)

    sel = SelectorWidget(_("plugin.select"), items)
    choice = sel.run(stdscr_c)
    if not choice:
        audit_log.debug("tui select.cancel: Plugins")
        return

    index = choice[0]
    if index >= len(plugins):
        audit_log.debug("tui select.choose: Plugins -> manifest issues")
        message_screen(
            stdscr_c,
            _("plugin.title"),
            [_("plugin.manifest_issues"), *manifest_issue_lines],
        )
        return

    plugin = plugins[index]
    audit_log.debug("tui select.choose: Plugins -> %s", plugin.plugin_id)

    if not confirm_dialog(stdscr_c, _("plugin.confirm_run")):
        return

    audit.log_action_start("tui", "plugin.run", plugin.plugin_id)
    use_case = PluginRunUseCase(ws, SubprocessPluginRunner(), language=language)
    # The TUI never passes arguments: a plugin that needs them is run from
    # the CLI (``plugin run <id> -- …``).
    request = PluginRunRequest(plugin_id=plugin.plugin_id, args=())

    try:
        result = _run_with_terminal_handover(stdscr_c, lambda: use_case.execute(request))
    except KeyboardInterrupt:
        audit_log.warning("tui action.interrupted: plugin.run %s", plugin.plugin_id)
        audit.log_action_end("tui", "plugin.run", "interrupted")
        message_screen(stdscr_c, _("plugin.run_title"), [_("plugin.interrupted")])
        return
    except Exception as exc:
        logger.exception("Plugin %s could not be run", plugin.plugin_id)
        audit.log_action_end("tui", "plugin.run", f"error: {exc}")
        message_screen(
            stdscr_c,
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
    message_screen(stdscr_c, _("plugin.run_title"), lines)
