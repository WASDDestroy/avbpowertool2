"""Tests for the TUI plugins view.

Curses is never started here: the widgets, the terminal handover and the
plugin runner are all replaced by fakes, and ``stdscr`` is a plain
``object()``.  The list/run paths drive the real use cases against a
``tmp_path`` workspace, so the plugin id, manifest and entry resolution are
exercised for real without a plugin process ever being spawned.  The
install/uninstall paths mostly script the use cases (so every issue code is
reachable), plus one end-to-end pair that drives the real ones against
``tmp_path`` — never against the real workspace.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TypeVar

import pytest

import avbpowertool.presentation.tui.views.plugins as plugins_view
from avbpowertool.application.commands import (
    PluginInstallRequest,
    PluginInstallResult,
    PluginUninstallRequest,
    PluginUninstallResult,
)
from avbpowertool.application.ports import PluginRunOutcome
from avbpowertool.domain.models import OperationIssue
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


def _manifest_xml(
    plugin_id: str,
    *,
    name: str,
    entry: str,
    version: int,
    version_name: str,
) -> str:
    """A well-formed plugin manifest (version / version_name optional in effect)."""
    version_name_xml = f"<version_name>{version_name}</version_name>" if version_name else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<avbpowertool_plugin schema_version="1">'
        f"<id>{plugin_id}</id><entry>{entry}</entry>"
        f"<version>{version}</version>{version_name_xml}"
        f'<names><name lang="en">{name}</name></names>'
        "</avbpowertool_plugin>"
    )


def _add_plugin(
    ws: WorkspacePaths,
    plugin_id: str,
    *,
    name: str | None = None,
    entry: str = "run.cmd",
    version: int = 1,
    version_name: str = "",
) -> Path:
    """Create an installed-looking plugin directory under ``plugins/``."""
    plugin_dir = ws.plugins / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest = _manifest_xml(
        plugin_id,
        name=name or plugin_id,
        entry=entry,
        version=version,
        version_name=version_name,
    )
    (plugin_dir / PLUGIN_MANIFEST_NAME).write_text(manifest, encoding="utf-8")
    (plugin_dir / entry).write_text("@echo off\n", encoding="utf-8")
    return plugin_dir


def _add_source_package(
    tmp_path: Path, plugin_id: str, *, version: int, version_name: str = ""
) -> Path:
    """Create an installable plugin package (a source directory) outside plugins/."""
    source = tmp_path / "src" / plugin_id
    source.mkdir(parents=True, exist_ok=True)
    manifest = _manifest_xml(
        plugin_id,
        name=plugin_id,
        entry="run.cmd",
        version=version,
        version_name=version_name,
    )
    (source / PLUGIN_MANIFEST_NAME).write_text(manifest, encoding="utf-8")
    (source / "run.cmd").write_text("@echo off\n", encoding="utf-8")
    return source


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


class _FakeInstallUseCase:
    """Records install requests and answers with scripted results."""

    def __init__(self, results: Sequence[PluginInstallResult]) -> None:
        self.results = list(results)
        self.requests: list[PluginInstallRequest] = []

    def execute(self, request: PluginInstallRequest) -> PluginInstallResult:
        self.requests.append(request)
        if not self.results:
            raise AssertionError("the view called the install use case more often than scripted")
        return self.results.pop(0)


class _FakeUninstallUseCase:
    """Records uninstall requests and answers with scripted results."""

    def __init__(self, results: Sequence[PluginUninstallResult]) -> None:
        self.results = list(results)
        self.requests: list[PluginUninstallRequest] = []

    def execute(self, request: PluginUninstallRequest) -> PluginUninstallResult:
        self.requests.append(request)
        if not self.results:
            raise AssertionError("the view called the uninstall use case more often than scripted")
        return self.results.pop(0)


def _install_use_case(
    monkeypatch: pytest.MonkeyPatch, *results: PluginInstallResult
) -> _FakeInstallUseCase:
    """Replace the install use case the view builds for itself."""
    fake = _FakeInstallUseCase(results)
    monkeypatch.setattr(plugins_view, "PluginInstallUseCase", lambda ws: fake)
    return fake


def _uninstall_use_case(
    monkeypatch: pytest.MonkeyPatch, *results: PluginUninstallResult
) -> _FakeUninstallUseCase:
    """Replace the uninstall use case the view builds for itself."""
    fake = _FakeUninstallUseCase(results)
    monkeypatch.setattr(plugins_view, "PluginUninstallUseCase", lambda ws: fake)
    return fake


def _installed_ok(
    plugin_id: str = "alpha", *, version: int = 2, version_name: str = "", files: int = 3
) -> PluginInstallResult:
    return PluginInstallResult(
        plugin_id=plugin_id,
        installed=True,
        file_count=files,
        version=version,
        version_name=version_name,
    )


def _install_failed(code: str, message: str = "boom") -> PluginInstallResult:
    return PluginInstallResult(issues=(OperationIssue(code, message),))


def _uninstalled_ok(
    plugin_id: str = "beta", *, files: int = 2, total_bytes: int = 64
) -> PluginUninstallResult:
    return PluginUninstallResult(
        plugin_id,
        removed=True,
        removed_files=files,
        removed_bytes=total_bytes,
    )


class _RecordingUI:
    """Fake widgets: capture what the view drew, script what it answers."""

    def __init__(
        self,
        *,
        selections: list[list[int]] | None = None,
        confirm: bool = True,
        inputs: list[str | None] | None = None,
    ) -> None:
        self.selections = list(selections if selections is not None else [[0]])
        self.confirm = confirm
        self.inputs = list(inputs if inputs is not None else [])
        self.selector_titles: list[str] = []
        self.selector_items: list[list[str]] = []
        self.messages: list[tuple[str, list[str]]] = []
        self.confirm_prompts: list[str] = []
        self.input_prompts: list[str] = []
        self.handovers = 0

    # -- replacements for the widget layer --------------------------------
    def message_screen(self, stdscr: object, title: str, lines: list[str]) -> None:
        self.messages.append((title, list(lines)))

    def confirm_dialog(self, stdscr: object, prompt: str) -> bool:
        self.confirm_prompts.append(prompt)
        return self.confirm

    def input_prompt(self, stdscr: object, prompt: str) -> str:
        self.input_prompts.append(prompt)
        if not self.inputs:
            raise AssertionError("the view asked for input but none was scripted")
        value = self.inputs.pop(0)
        return "" if value is None else value

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
        monkeypatch.setattr(plugins_view, "input_prompt", self.input_prompt)
        monkeypatch.setattr(plugins_view, "_run_with_terminal_handover", self.handover)
        monkeypatch.setattr(plugins_view, "SelectorWidget", self.selector_class())

    # -- assertions helpers ------------------------------------------------
    @property
    def last_lines(self) -> list[str]:
        assert self.messages, "the view showed no message screen"
        return self.messages[-1][1]

    @property
    def last_title(self) -> str:
        assert self.messages, "the view showed no message screen"
        return self.messages[-1][0]


def _show(ws: WorkspacePaths) -> None:
    """Call the view the way ``app.py`` does (``stdscr`` is never a window)."""
    plugins_view.show(object(), ws, FakeAvbTool())


#: The action rows every selector ends with, in order.
_ACTION_ROWS = (_("plugin.install"), _("plugin.uninstall"))


# ---------------------------------------------------------------------------
# Empty / cancel / refusal
# ---------------------------------------------------------------------------


class TestNoPlugins:
    def test_empty_plugins_dir_shows_the_hint_and_still_offers_install(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ws = _workspace(tmp_path)
        ui = _RecordingUI(selections=[[]])  # cancel the selector
        ui.install(monkeypatch)
        runner = _install_runner(monkeypatch)

        _show(ws)

        assert ui.messages == [(_("plugin.title"), [_("plugin.none"), _("plugin.none_hint")])]
        # The install entry must stay reachable with no plugins installed.
        assert ui.selector_items == [list(_ACTION_ROWS)]
        assert ui.selector_titles == [_("plugin.select")]
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

        assert ui.selector_items == [["alpha (alpha) v1", *_ACTION_ROWS]]
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

        # The list is sorted by plugin id and shows "Name (plugin_id) v<version>".
        assert ui.selector_titles == [_("plugin.select")]
        assert ui.selector_items == [
            ["Alpha Plugin (alpha) v1", "Beta Plugin (beta) v1", *_ACTION_ROWS]
        ]
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
        assert "Beta Plugin (beta) v1" in lines
        assert _("plugin.exit_code", code=7) in lines

    def test_plugin_row_shows_the_version_name_when_declared(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ws = _workspace(tmp_path)
        _add_plugin(ws, "alpha", name="Alpha Plugin", version=2, version_name="2.1.0")
        _install_runner(monkeypatch, PluginRunOutcome(exit_code=0))
        ui = _RecordingUI(selections=[[0]])
        ui.install(monkeypatch)

        _show(ws)

        assert ui.selector_items == [["Alpha Plugin (alpha) v2 (2.1.0)", *_ACTION_ROWS]]

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
# Installing a plugin
# ---------------------------------------------------------------------------


class TestInstallEntry:
    def test_install_asks_for_a_path_and_calls_without_force(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ws = _workspace(tmp_path)
        source = str(tmp_path / "somewhere" / "alpha")
        use_case = _install_use_case(monkeypatch, _installed_ok(version=2, version_name="2.0.0"))
        ui = _RecordingUI(selections=[[0]], inputs=[source])  # index 0 is "install"
        ui.install(monkeypatch)

        _show(ws)

        assert ui.input_prompts == [_("plugin.install_path")]
        assert use_case.requests == [PluginInstallRequest(source_path=source)]
        assert use_case.requests[0].force is False
        assert ui.messages[-1] == (
            _("plugin.install_title"),
            [_("plugin.installed_ok", id="alpha", version="2 (2.0.0)", files=3)],
        )
        # The install path never suspends curses: it is a plain use-case call.
        assert ui.handovers == 0

    def test_install_result_without_a_version_name_shows_the_number_only(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ws = _workspace(tmp_path)
        _install_use_case(monkeypatch, _installed_ok(version=4, files=7))
        ui = _RecordingUI(selections=[[0]], inputs=["D:\\plugins\\alpha.zip"])
        ui.install(monkeypatch)

        _show(ws)

        assert ui.last_lines == [_("plugin.installed_ok", id="alpha", version="4", files=7)]

    def test_downgrade_is_shown_then_retried_with_force(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ws = _workspace(tmp_path)
        _add_plugin(ws, "alpha", version=2)
        source = str(tmp_path / "src" / "alpha")
        downgrade_message = (
            "Refusing to downgrade plugin 'alpha': installed version 2 is newer "
            "than the incoming version 1 (use --force to downgrade)"
        )
        use_case = _install_use_case(
            monkeypatch,
            _install_failed("plugin.downgrade", downgrade_message),
            _installed_ok(version=1, files=2),
        )
        ui = _RecordingUI(selections=[[1]], inputs=[source], confirm=True)  # index 1 = install
        ui.install(monkeypatch)

        _show(ws)

        # 1. The version information is shown before anything is asked.
        assert ui.messages[0] == (_("plugin.downgrade_title"), [downgrade_message])
        # 2. Exactly one question, and the retry carries force=True.
        assert ui.confirm_prompts == [_("plugin.downgrade_confirm")]
        assert use_case.requests == [
            PluginInstallRequest(source_path=source),
            PluginInstallRequest(source_path=source, force=True),
        ]
        # 3. The result screen says the downgrade was confirmed.
        assert ui.last_title == _("plugin.install_title")
        assert ui.last_lines == [
            _("plugin.installed_ok", id="alpha", version="1", files=2),
            _("plugin.downgrade_installed"),
        ]

    def test_declining_the_downgrade_writes_nothing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ws = _workspace(tmp_path)
        _add_plugin(ws, "alpha", version=2)
        source = str(tmp_path / "src" / "alpha")
        use_case = _install_use_case(
            monkeypatch, _install_failed("plugin.downgrade", "installed 2 > incoming 1")
        )
        ui = _RecordingUI(selections=[[1]], inputs=[source], confirm=False)
        ui.install(monkeypatch)

        _show(ws)

        assert ui.messages[0] == (_("plugin.downgrade_title"), ["installed 2 > incoming 1"])
        assert ui.confirm_prompts == [_("plugin.downgrade_confirm")]
        assert len(use_case.requests) == 1  # no forced retry
        assert ui.last_lines == [_("plugin.cancelled")]

    def test_other_failures_are_reported_without_a_downgrade_prompt(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ws = _workspace(tmp_path)
        _install_use_case(
            monkeypatch,
            _install_failed("plugin.manifest_invalid", "Malformed plugin manifest XML"),
        )
        ui = _RecordingUI(selections=[[0]], inputs=["broken"])
        ui.install(monkeypatch)

        _show(ws)

        assert ui.confirm_prompts == []
        assert ui.last_title == _("plugin.install_title")
        assert ui.last_lines == ["  [plugin.manifest_invalid] Malformed plugin manifest XML"]

    @pytest.mark.parametrize("answer", ["", None])
    def test_an_empty_path_does_nothing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, answer: str | None
    ) -> None:
        ws = _workspace(tmp_path)
        _add_plugin(ws, "alpha")
        use_case = _install_use_case(monkeypatch, _installed_ok())
        ui = _RecordingUI(selections=[[1]], inputs=[answer])
        ui.install(monkeypatch)

        _show(ws)

        assert ui.input_prompts == [_("plugin.install_path")]
        assert use_case.requests == []
        assert ui.messages == []


class TestInstallAgainstTheRealUseCase:
    """The downgrade gate driven end to end against ``tmp_path``."""

    def test_confirming_installs_the_older_version(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ws = _workspace(tmp_path)
        installed_dir = _add_plugin(ws, "alpha", version=2)
        source = _add_source_package(tmp_path, "alpha", version=1)
        ui = _RecordingUI(selections=[[1]], inputs=[str(source)], confirm=True)
        ui.install(monkeypatch)

        _show(ws)

        # Both versions are shown before anything is asked.
        assert ui.messages[0][0] == _("plugin.downgrade_title")
        warning = " ".join(ui.messages[0][1])
        assert "version 2" in warning
        assert "version 1" in warning
        assert ui.confirm_prompts == [_("plugin.downgrade_confirm")]
        assert ui.last_lines == [
            _("plugin.installed_ok", id="alpha", version="1", files=2),
            _("plugin.downgrade_installed"),
        ]
        manifest = (installed_dir / PLUGIN_MANIFEST_NAME).read_text(encoding="utf-8")
        assert "<version>1</version>" in manifest

    def test_declining_leaves_the_installed_version_alone(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ws = _workspace(tmp_path)
        installed_dir = _add_plugin(ws, "alpha", version=2)
        source = _add_source_package(tmp_path, "alpha", version=1)
        ui = _RecordingUI(selections=[[1]], inputs=[str(source)], confirm=False)
        ui.install(monkeypatch)

        _show(ws)

        assert ui.last_lines == [_("plugin.cancelled")]
        manifest = (installed_dir / PLUGIN_MANIFEST_NAME).read_text(encoding="utf-8")
        assert "<version>2</version>" in manifest


# ---------------------------------------------------------------------------
# Uninstalling a plugin
# ---------------------------------------------------------------------------


class TestUninstallEntry:
    def test_uninstall_lists_the_plugins_and_removes_the_chosen_one(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ws = _workspace(tmp_path)
        _add_plugin(ws, "alpha", name="Alpha Plugin")
        _add_plugin(ws, "beta", name="Beta Plugin")
        use_case = _uninstall_use_case(
            monkeypatch, _uninstalled_ok("beta", files=2, total_bytes=64)
        )
        # 1st selector: index 2 is "uninstall"; 2nd selector: index 1 is "beta".
        ui = _RecordingUI(selections=[[3], [1]], confirm=True)
        ui.install(monkeypatch)

        _show(ws)

        assert ui.selector_titles == [_("plugin.select"), _("plugin.uninstall")]
        assert ui.selector_items[1] == [
            "Alpha Plugin (alpha) v1",
            "Beta Plugin (beta) v1",
        ]
        assert ui.confirm_prompts == [_("plugin.uninstall_confirm", id="beta")]
        assert use_case.requests == [PluginUninstallRequest(plugin_id="beta")]
        assert ui.messages[-1] == (
            _("plugin.uninstall_title"),
            [_("plugin.uninstalled_ok", id="beta", files=2, bytes=64)],
        )
        assert ui.handovers == 0

    def test_refusing_the_uninstall_confirmation_removes_nothing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ws = _workspace(tmp_path)
        _add_plugin(ws, "alpha")
        use_case = _uninstall_use_case(monkeypatch, _uninstalled_ok("alpha"))
        ui = _RecordingUI(selections=[[2], [0]], confirm=False)
        ui.install(monkeypatch)

        _show(ws)

        assert use_case.requests == []
        assert ui.messages == []

    def test_cancelling_the_plugin_selector_removes_nothing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ws = _workspace(tmp_path)
        _add_plugin(ws, "alpha")
        use_case = _uninstall_use_case(monkeypatch, _uninstalled_ok("alpha"))
        ui = _RecordingUI(selections=[[2], []], confirm=True)
        ui.install(monkeypatch)

        _show(ws)

        assert use_case.requests == []
        assert ui.confirm_prompts == []
        assert ui.messages == []

    def test_uninstall_without_plugins_explains_and_returns(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ws = _workspace(tmp_path)
        use_case = _uninstall_use_case(monkeypatch, _uninstalled_ok("alpha"))
        # With no plugins the selector is [install, uninstall]: index 1.
        ui = _RecordingUI(selections=[[1]])
        ui.install(monkeypatch)

        _show(ws)

        assert ui.messages[-1] == (_("plugin.uninstall_title"), [_("plugin.none")])
        assert use_case.requests == []
        assert ui.confirm_prompts == []

    def test_uninstall_removes_the_directory_for_real(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ws = _workspace(tmp_path)
        plugin_dir = _add_plugin(ws, "alpha")
        expected_bytes = sum(
            path.stat().st_size for path in plugin_dir.rglob("*") if path.is_file()
        )
        ui = _RecordingUI(selections=[[2], [0]], confirm=True)  # uninstall, then alpha
        ui.install(monkeypatch)

        _show(ws)

        assert not plugin_dir.exists()
        assert ui.last_title == _("plugin.uninstall_title")
        assert ui.last_lines == [
            _("plugin.uninstalled_ok", id="alpha", files=2, bytes=expected_bytes)
        ]


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
        assert items[0] == "Alpha Plugin (alpha) v1"
        assert _("plugin.manifest_issues") in items
        assert any("plugin.manifest_invalid" in item for item in items)
        # ...and the run screen repeats them, so they are never dropped.
        assert any("plugin.manifest_invalid" in line for line in ui.last_lines)

    def test_selecting_an_issue_row_acts_on_nothing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ws = _workspace(tmp_path)
        _add_plugin(ws, "alpha", name="Alpha Plugin")
        _add_broken_plugin(ws, "broken")
        runner = _install_runner(monkeypatch)
        install_use_case = _install_use_case(monkeypatch, _installed_ok())
        ui = _RecordingUI(selections=[[3]])  # index 3 is the issue block header
        ui.install(monkeypatch)

        _show(ws)

        assert runner.calls == []
        assert install_use_case.requests == []
        assert ui.confirm_prompts == []
        assert any("plugin.manifest_invalid" in line for line in ui.last_lines)

    def test_no_plugins_but_a_broken_manifest_still_reports_it(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ws = _workspace(tmp_path)
        _add_broken_plugin(ws, "broken")
        ui = _RecordingUI(selections=[[]])
        ui.install(monkeypatch)
        runner = _install_runner(monkeypatch)

        _show(ws)

        assert runner.calls == []
        lines = ui.messages[0][1]
        assert _("plugin.none") in lines
        assert _("plugin.manifest_issues") in lines
        assert any("plugin.manifest_invalid" in line for line in lines)
        # The install entry is still offered next to the issues.
        assert ui.selector_items[0][:2] == list(_ACTION_ROWS)
        assert any("plugin.manifest_invalid" in item for item in ui.selector_items[0])


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
