"""Real PluginRunnerPort implementation via a subprocess."""

from __future__ import annotations

import logging
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from avbpowertool.application.ports import PluginRunOutcome

logger = logging.getLogger(__name__)

#: Interpreter per entry file extension.  ``.sh`` is only nominally
#: supported: the wrapper exists so a plugin can declare it, not because
#: every workspace has a POSIX shell.
_INTERPRETERS: dict[str, tuple[str, ...]] = {
    ".ps1": ("pwsh", "-NoProfile", "-File"),
    ".cmd": ("cmd", "/c"),
    ".bat": ("cmd", "/c"),
    ".sh": ("sh",),
}


def _interpreter_for(entry: Path) -> tuple[str, ...] | None:
    """Return the command prefix running *entry*, or None when unsupported.

    ``.py`` is resolved lazily so the running interpreter (virtualenv or
    not) is always the one that executes the plugin.
    """
    if entry.suffix.lower() == ".py":
        return (sys.executable,)
    return _INTERPRETERS.get(entry.suffix.lower())


class SubprocessPluginRunner:
    """Run a plugin entry script in a child process.

    The child inherits this process' stdio on purpose: plugins are
    interactive CLIs (they may prompt, print progress, or be driven by a
    TUI), so their output is never captured.  Only the exit status travels
    back through :class:`PluginRunOutcome`.
    """

    def run(
        self,
        entry: Path,
        *,
        cwd: Path,
        env: Mapping[str, str],
        args: Sequence[str],
    ) -> PluginRunOutcome:
        interpreter = _interpreter_for(entry)
        if interpreter is None:
            return PluginRunOutcome(
                exit_code=-1,
                error=f"unsupported entry type: {entry.suffix or entry.name}",
            )

        command = [*interpreter, str(entry), *args]
        # The summary is for audit logs only: the environment is injected
        # separately and never echoed into it.
        summary = subprocess.list2cmdline(command)

        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                env=dict(env),
                check=False,
            )
        except FileNotFoundError as exc:
            logger.error("Plugin interpreter not found for %s: %s", entry, exc)
            return PluginRunOutcome(
                exit_code=-1,
                command_summary=summary,
                error=f"Plugin interpreter not found: {exc}",
            )
        except OSError as exc:
            logger.error("Failed to start plugin %s: %s", entry, exc)
            return PluginRunOutcome(
                exit_code=-1,
                command_summary=summary,
                error=f"Failed to start plugin: {exc}",
            )

        logger.info("Plugin %s exited with %d", entry, completed.returncode)
        return PluginRunOutcome(exit_code=completed.returncode, command_summary=summary)
