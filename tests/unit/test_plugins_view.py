"""Tests for the TUI plugins view.

Curses is never started here: the widgets, the terminal handover and the
plugin runner are all replaced by fakes, and ``stdscr`` is a plain
``object()``.  The real use cases run against a ``tmp_path`` workspace, so
the plugin id, manifest and entry resolution are exercised for real
without a plugin process ever being spawned.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TypeVar

import pytest

import avbpowertool.presentation.tui.views.plugins as plugins_view
from avbpowertool.application.ports import PluginRunOutcome
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.persistence.plugin_repository import (
    PLUGIN_MANIFEST_NAME,
)
from avbpowertool.presentation.i18n import _, init_i18n
from tests.conftest import FakeAvbTool

init_i18n("en")

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Fixtures and fakes
# ---------------------------------------------------------------------------


def _workspace(tmp_path: Path) -> WorkspacePaths:
    """A workspace whose ``plugins/`` directory exists."""
    ws = WorkspacePaths.discover(tmp_path)
    ws.plugins.mkdir(parents=True, exist_ok=True)
    return ws


def _add_plugin(
    ws: WorkspacePaths,
    plugin_id: str,
    *,
    name: str | None = None,
    entry: str = "run.cmd",
) -> Path:
    """Create an installed-looking plugin directory under ``plugins/``."""
    plugin_dir = ws.plugins / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    display = name or plugin_id
    manifest = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<avbpowertool_plugin schema_version="1">'
        f"<id>{plugin_id}</id><entry>{entry}</entry>"
        f'<names><name lang="en">{display}</name></names>'
        "</avbpowertool_plugin>"
    )
    (plugin_dir / PLUGIN_MANIFEST_NAME).write_text(manifest, encoding="utf-8")
    (plugin_dir / entry).write_text("@echo off\n", encoding="utf-8")
    return plugin_dir


def _add_broken_plugin(ws: WorkspacePaths, plugin_id: str) -> Path:
    """Create a plugin directory whose manifest cannot be parsed."""
    plugin_dir = ws.plugins / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / PLUGIN_MANIFEST_NAME).write_text("<not-a-plugin/>", encoding="utf-8")
    return plugin_dir


class _FakeRunner:
    """Records every run and answers with a scripted outcome."""

    def __init__(self, outcome: PluginRunOutcome | None = None) -> None:
        self.outcome = outcome if outcome is not None else PluginRunOutcome(exit_code=0)
        self.calls: list[tuple[Path, Path, dict[str, str], tuple[str, ...]]] = []

    def run(
        self,
        entry: Path,
        *,
        cwd: Path,
        env: dict[str, str],
        args: Sequence[str],
    ) -> PluginRunOutcome:
        self.calls.append((entry, cwd, dict(env), tuple(args)))
        return self.outcome


def _install_runner(
    monkeypatch: pytest.MonkeyPatch, outcome: PluginRunOutcome | None = None
) -> _FakeRunner:
    """Replace the subprocess runner the view builds for itself."""
    runner = _FakeRunner(outcome)
    monkeypatch.setattr(plugins_view, "SubprocessPluginRunner", lambda: runner)
    return runner


class _RecordingUI:
    """Fake widgets: capture what the view drew, script what it answers."""

    def __init__(self, *, selections: list[list[int]] | None = None, confirm: bool = True) -> None:
        self.selections = list(selections if selections is not None else [[0]])
        self.confirm = confirm
        self.selector_titles: list[str] = []
        self.selector_items: list[list[str]] = []
        self.messages: list[tuple[str, list[str]]] = []
        self.confirm_prompts: list[str] = []
        self.handovers = 0

    # -- replacements for the widget layer --------------------------------
    def message_screen(self, stdscr: object, title: str, lines: list[str]) -> None:
        self.messages.append((title, list(lines)))

    def confirm_dialog(self, stdscr: object, prompt: str) -> bool:
        self.confirm_prompts.append(prompt)
        return self.confirm

    def handover(self, stdscr: object, action: Callable[[], T]) -> T:
        self.handovers += 1
        return action()

    def selector_class(self) -> type:
        ui = self

        class _Selector:
            def __init__(
                self, title: str, items: Sequence[str], multi_select: bool = False
            ) -> None:
                ui.selector_titles.append(title)
                ui.selector_items.append(list(items))

            def run(self, stdscr: object) -> list[int]:
                if not ui.selections:
                    return []
                return ui.selections.pop(0)

        return _Selector

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(plugins_view, "message_screen", self.message_screen)
        monkeypatch.setattr(plugins_view, "confirm_dialog", self.confirm_dialog)
        monkeypatch.setattr(plugins_view, "_run_with_terminal_handover", self.handover)
        monkeypatch.setattr(plugins_view, "SelectorWidget", self.selector_class())

    # -- assertions helpers ------------------------------------------------
    @property
    def last_lines(self) -> list[str]:
        assert self.messages, "the view showed no message screen"
        return self.messages[-1][1]


def _show(ws: WorkspacePaths) -> None:
    """Call the view the way ``app.py`` does (``stdscr`` is never a window)."""
    plugins_view.show(object(), ws, FakeAvbTool())


# ---------------------------------------------------------------------------
# Empty / cancel / refusal
# ---------------------------------------------------------------------------


class TestNoPlugins:
    def test_empty_plugins_dir_shows_the_cli_install_hint(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ws = _workspace(tmp_path)
        ui = _RecordingUI()
        ui.install(monkeypatch)
        runner = _install_runner(monkeypatch)

        _show(ws)

        assert ui.messages == [(_("plugin.title"), [_("plugin.none"), _("plugin.none_hint")])]
        assert ui.selector_items == []  # no selector at all
        assert runner.calls == []


class TestCancel:
    def test_selector_cancel_does_not_run_anything(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ws = _workspace(tmp_path)
        _add_plugin(ws, "alpha")
        ui = _RecordingUI(selections=[[]])
        ui.install(monkeypatch)
        runner = _install_runner(monkeypatch)

        _show(ws)

        assert ui.selector_items == [["alpha (alpha)"]]
        assert runner.calls == []
        assert ui.confirm_prompts == []
        assert ui.messages == []

    def test_refusing_the_confirmation_does_not_run_anything(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ws = _workspace(tmp_path)
        _add_plugin(ws, "alpha")
        ui = _RecordingUI(selections=[[0]], confirm=False)
        ui.install(monkeypatch)
        runner = _install_runner(monkeypatch)

        _show(ws)

        assert ui.confirm_prompts == [_("plugin.confirm_run")]
        assert runner.calls == []
        assert ui.handovers == 0
        assert ui.messages == []


# ---------------------------------------------------------------------------
# Running a plugin
# ---------------------------------------------------------------------------


class TestRunSelectedPlugin:
    def test_runs_the_selected_plugin_id_without_arguments(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ws = _workspace(tmp_path)
        _add_plugin(ws, "alpha", name="Alpha Plugin")
        beta_dir = _add_plugin(ws, "beta", name="Beta Plugin")
        runner = _install_runner(monkeypatch, PluginRunOutcome(exit_code=7))
        ui = _RecordingUI(selections=[[1]])
        ui.install(monkeypatch)

        _show(ws)

        # The list is sorted by plugin id and shows "Name (plugin_id)".
        assert ui.selector_titles == [_("plugin.select")]
        assert ui.selector_items == [["Alpha Plugin (alpha)", "Beta Plugin (beta)"]]
        assert ui.confirm_prompts == [_("plugin.confirm_run")]
        assert ui.handovers == 1

        assert len(runner.calls) == 1
        entry, cwd, env, args = runner.calls[0]
        assert entry == beta_dir / "run.cmd"
        assert cwd == ws.root
        assert args == ()  # the TUI never passes arguments
        assert env["AVBPOWERTOOL_PLUGIN_ID"] == "beta"
        assert env["AVBPOWERTOOL_PLUGIN_DIR"] == str(beta_dir)

        title, lines = ui.messages[-1]
        assert title == _("plugin.run_title")
        assert "Beta Plugin (beta)" in lines
        assert _("plugin.exit_code", code=7) in lines

    def test_zero_exit_code_is_reported_too(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ws = _workspace(tmp_path)
        _add_plugin(ws, "alpha")
        _install_runner(monkeypatch, PluginRunOutcome(exit_code=0))
        ui = _RecordingUI(selections=[[0]])
        ui.install(monkeypatch)

        _show(ws)

        assert _("plugin.exit_code", code=0) in ui.last_lines
        assert _("plugin.run_failed") not in ui.last_lines


class TestRunIssues:
    def test_run_issues_are_listed_with_their_error_code(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ws = _workspace(tmp_path)
        _add_plugin(ws, "alpha", name="Alpha Plugin")
        _install_runner(monkeypatch, PluginRunOutcome(exit_code=-1, error="interpreter exploded"))
        ui = _RecordingUI(selections=[[0]])
        ui.install(monkeypatch)

        _show(ws)

        lines = ui.last_lines
        assert _("plugin.run_failed") in lines
        assert "  [plugin.run_failed] interpreter exploded" in lines
        assert _("plugin.exit_code", code=-1) in lines


class TestHandoverFailures:
    def test_handover_failure_is_reported_instead_of_raising(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ws = _workspace(tmp_path)
        _add_plugin(ws, "alpha", name="Alpha Plugin")
        ui = _RecordingUI(selections=[[0]])
        ui.install(monkeypatch)
        runner = _install_runner(monkeypatch)

        def exploding_handover(stdscr: object, action: Callable[[], object]) -> object:
            raise RuntimeError("no tty available")

        monkeypatch.setattr(plugins_view, "_run_with_terminal_handover", exploding_handover)

        _show(ws)  # must not raise

        assert runner.calls == []
        title, lines = ui.messages[-1]
        assert title == _("plugin.run_title")
        assert _("plugin.run_failed") in lines
        assert "no tty available" in lines

    def test_keyboard_interrupt_is_reported_as_interrupted(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ws = _workspace(tmp_path)
        _add_plugin(ws, "alpha", name="Alpha Plugin")
        ui = _RecordingUI(selections=[[0]])
        ui.install(monkeypatch)
        _install_runner(monkeypatch)

        def interrupted_handover(stdscr: object, action: Callable[[], object]) -> object:
            raise KeyboardInterrupt

        monkeypatch.setattr(plugins_view, "_run_with_terminal_handover", interrupted_handover)

        _show(ws)  # must not raise

        assert ui.messages[-1] == (_("plugin.run_title"), [_("plugin.interrupted")])


# ---------------------------------------------------------------------------
# Broken manifests
# ---------------------------------------------------------------------------


class TestManifestIssues:
    def test_broken_manifest_is_listed_and_reported(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ws = _workspace(tmp_path)
        _add_plugin(ws, "alpha", name="Alpha Plugin")
        _add_broken_plugin(ws, "broken")
        _install_runner(monkeypatch, PluginRunOutcome(exit_code=0))
        ui = _RecordingUI(selections=[[0]])
        ui.install(monkeypatch)

        _show(ws)

        items = ui.selector_items[0]
        assert items[0] == "Alpha Plugin (alpha)"
        assert _("plugin.manifest_issues") in items
        assert any("plugin.manifest_invalid" in item for item in items)
        # ...and the run screen repeats them, so they are never dropped.
        assert any("plugin.manifest_invalid" in line for line in ui.last_lines)

    def test_selecting_an_issue_row_runs_nothing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ws = _workspace(tmp_path)
        _add_plugin(ws, "alpha", name="Alpha Plugin")
        _add_broken_plugin(ws, "broken")
        runner = _install_runner(monkeypatch)
        ui = _RecordingUI(selections=[[1]])  # index 1 is the issue row
        ui.install(monkeypatch)

        _show(ws)

        assert runner.calls == []
        assert ui.confirm_prompts == []
        assert any("plugin.manifest_invalid" in line for line in ui.last_lines)

    def test_no_plugins_but_a_broken_manifest_still_reports_it(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ws = _workspace(tmp_path)
        _add_broken_plugin(ws, "broken")
        ui = _RecordingUI()
        ui.install(monkeypatch)
        runner = _install_runner(monkeypatch)

        _show(ws)

        assert runner.calls == []
        lines = ui.last_lines
        assert _("plugin.none") in lines
        assert _("plugin.manifest_issues") in lines
        assert any("plugin.manifest_invalid" in line for line in lines)


# ---------------------------------------------------------------------------
# The terminal handover helper itself (curses is stubbed, never started)
# ---------------------------------------------------------------------------


class _FakeWindow:
    """Stands in for ``curses.window``: counts the post-run refresh."""

    def __init__(self) -> None:
        self.refreshed = 0

    def refresh(self) -> None:
        self.refreshed += 1


class TestTerminalHandover:
    def _stub_curses(self, monkeypatch: pytest.MonkeyPatch, events: list[str]) -> None:
        monkeypatch.setattr(plugins_view.curses, "def_prog_mode", lambda: events.append("save"))
        monkeypatch.setattr(plugins_view.curses, "endwin", lambda: events.append("endwin"))
        monkeypatch.setattr(
            plugins_view.curses, "reset_prog_mode", lambda: events.append("restore")
        )

    def test_saves_and_restores_the_terminal_around_the_action(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        events: list[str] = []
        self._stub_curses(monkeypatch, events)
        window = _FakeWindow()

        def action() -> int:
            events.append("run")
            return 42

        assert plugins_view._run_with_terminal_handover(window, action) == 42
        assert events == ["save", "endwin", "run", "restore"]
        assert window.refreshed == 1

    def test_restores_the_terminal_when_the_action_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        events: list[str] = []
        self._stub_curses(monkeypatch, events)
        window = _FakeWindow()

        def action() -> int:
            events.append("run")
            raise RuntimeError("plugin exploded")

        with pytest.raises(RuntimeError):
            plugins_view._run_with_terminal_handover(window, action)

        assert events == ["save", "endwin", "run", "restore"]
        assert window.refreshed == 1

    def test_curses_failures_never_stop_the_action(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A terminal that cannot be handed over must not block the plugin."""

        def failing() -> None:
            raise plugins_view.curses.error("must call initscr() first")

        monkeypatch.setattr(plugins_view.curses, "def_prog_mode", failing)
        monkeypatch.setattr(plugins_view.curses, "endwin", failing)
        monkeypatch.setattr(plugins_view.curses, "reset_prog_mode", failing)

        class _FailingWindow:
            def refresh(self) -> None:
                raise plugins_view.curses.error("no window")

        assert plugins_view._run_with_terminal_handover(_FailingWindow(), lambda: "ran") == "ran"
