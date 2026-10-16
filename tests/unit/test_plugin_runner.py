"""Tests for SubprocessPluginRunner (interpreter dispatch and failure modes).

No ``.sh`` case is exercised: the runner nominally supports it, but the
project does not test it (a POSIX shell is not guaranteed to exist).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from avbpowertool.infrastructure.plugins import runner as runner_module
from avbpowertool.infrastructure.plugins.runner import SubprocessPluginRunner


class RecordingRun:
    """Stand-in for ``subprocess.run`` that records its arguments."""

    def __init__(self, returncode: int = 0, raises: BaseException | None = None) -> None:
        self.returncode = returncode
        self.raises = raises
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        self.calls.append((list(command), kwargs))
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(command, self.returncode)


@pytest.fixture
def fake_run(monkeypatch: pytest.MonkeyPatch) -> RecordingRun:
    recorder = RecordingRun()
    monkeypatch.setattr(runner_module.subprocess, "run", recorder)
    return recorder


class TestInterpreterDispatch:
    def test_python_entry_uses_the_running_interpreter(self, fake_run: RecordingRun) -> None:
        outcome = SubprocessPluginRunner().run(
            Path("demo.py"), cwd=Path("ws"), env={}, args=("--x",)
        )

        command, kwargs = fake_run.calls[0]
        assert command == [sys.executable, str(Path("demo.py")), "--x"]
        assert kwargs["cwd"] == Path("ws")
        assert kwargs["env"] == {}
        assert kwargs["check"] is False
        assert outcome.exit_code == 0
        assert outcome.error == ""
        assert sys.executable in outcome.command_summary

    def test_powershell_entry(self, fake_run: RecordingRun) -> None:
        SubprocessPluginRunner().run(Path("demo.ps1"), cwd=Path("ws"), env={}, args=())

        assert fake_run.calls[0][0] == ["pwsh", "-NoProfile", "-File", str(Path("demo.ps1"))]

    def test_cmd_entry(self, fake_run: RecordingRun) -> None:
        SubprocessPluginRunner().run(Path("demo.cmd"), cwd=Path("ws"), env={}, args=())

        assert fake_run.calls[0][0] == ["cmd", "/c", str(Path("demo.cmd"))]

    def test_bat_entry(self, fake_run: RecordingRun) -> None:
        SubprocessPluginRunner().run(Path("demo.BAT"), cwd=Path("ws"), env={}, args=())

        assert fake_run.calls[0][0] == ["cmd", "/c", str(Path("demo.BAT"))]

    def test_unsupported_entry_never_spawns_a_process(self, fake_run: RecordingRun) -> None:
        outcome = SubprocessPluginRunner().run(Path("demo.txt"), cwd=Path("ws"), env={}, args=())

        assert fake_run.calls == []
        assert outcome.exit_code == -1
        assert outcome.error == "unsupported entry type: .txt"

    def test_extensionless_entry_is_reported_by_name(self, fake_run: RecordingRun) -> None:
        outcome = SubprocessPluginRunner().run(Path("demo"), cwd=Path("ws"), env={}, args=())

        assert outcome.exit_code == -1
        assert outcome.error == "unsupported entry type: demo"


class TestStdioInheritance:
    def test_output_is_never_captured(self, fake_run: RecordingRun) -> None:
        """Plugins may be interactive: stdio must be inherited, not piped."""
        SubprocessPluginRunner().run(Path("demo.py"), cwd=Path("ws"), env={}, args=())

        _command, kwargs = fake_run.calls[0]
        for forbidden in ("capture_output", "stdout", "stderr", "stdin", "input"):
            assert forbidden not in kwargs


class TestExitCodes:
    def test_non_zero_exit_is_returned_as_is(self, fake_run: RecordingRun) -> None:
        fake_run.returncode = 4

        outcome = SubprocessPluginRunner().run(Path("demo.py"), cwd=Path("ws"), env={}, args=())

        assert outcome.exit_code == 4
        assert outcome.error == ""

    def test_missing_interpreter_is_an_error_outcome(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*_args: Any, **_kwargs: Any) -> Any:
            raise FileNotFoundError(2, "The system cannot find the file specified")

        monkeypatch.setattr(runner_module.subprocess, "run", _raise)

        outcome = SubprocessPluginRunner().run(Path("demo.ps1"), cwd=Path("ws"), env={}, args=())

        assert outcome.exit_code == -1
        assert "not found" in outcome.error
        assert outcome.command_summary.startswith("pwsh")

    def test_os_error_is_an_error_outcome(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*_args: Any, **_kwargs: Any) -> Any:
            raise PermissionError(13, "Access is denied")

        monkeypatch.setattr(runner_module.subprocess, "run", _raise)

        outcome = SubprocessPluginRunner().run(Path("demo.py"), cwd=Path("ws"), env={}, args=())

        assert outcome.exit_code == -1
        assert "Failed to start plugin" in outcome.error

    def test_environment_is_forwarded_verbatim(self, fake_run: RecordingRun) -> None:
        SubprocessPluginRunner().run(
            Path("demo.py"), cwd=Path("ws"), env={"AVBPOWERTOOL_ROOT": "F:/ws"}, args=()
        )

        assert fake_run.calls[0][1]["env"] == {"AVBPOWERTOOL_ROOT": "F:/ws"}
