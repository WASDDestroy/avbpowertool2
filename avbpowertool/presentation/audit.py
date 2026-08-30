"""Audit logging helpers — user action trails for TUI and CLI.

All user-visible actions (navigation, menu choices, text input,
command invocations) are logged through a dedicated ``audit`` logger
namespace (``avbpowertool.audit``) so an operator can reconstruct a
user's session from its own per-session file under ``Logs/``
(``avbpowertool_<YYYYmmdd>_<HHMMSS>.log``) alone.

Levels:
  - DEBUG — TUI navigation trail and option selections (high volume).
  - INFO  — session start/end, CLI commands, destructive confirmations,
            and use-case outcomes surfaced to the user.

The public helpers below are intentionally trivial wrappers: call sites
read as ``audit.log_navigation(...)`` and the message prefix
(``tui``/``cli``) keeps the two interaction modes grep-able.
"""

from __future__ import annotations

import logging
import sys

AUDIT_LOGGER_NAME = "avbpowertool.audit"

_audit_logger = logging.getLogger(AUDIT_LOGGER_NAME)


def audit_logger() -> logging.Logger:
    """Return the shared audit logger."""
    return _audit_logger


def _msg(interface: str, event: str, detail: str) -> str:
    return f"{interface} {event}: {detail}" if detail else f"{interface} {event}"


def log_session_start(interface: str, detail: str) -> None:
    """Log a session boundary (TUI launch / CLI invocation)."""
    _audit_logger.info(_msg(interface, "session.start", detail))


def log_session_end(interface: str, detail: str) -> None:
    """Log session termination (TUI exit / CLI exit code)."""
    _audit_logger.info(_msg(interface, "session.end", detail))


def log_navigation(event: str, detail: str) -> None:
    """Log a TUI navigation step (route enter, back, exit) at DEBUG."""
    _audit_logger.debug(_msg("tui", f"nav.{event}", detail))


def log_selection(title: str, items: list[str], chosen: list[int]) -> None:
    """Log a TUI selector/confirm choice (DEBUG).

    ``chosen`` holds the selected indices; an empty list means the user
    cancelled (Esc).
    """
    if not chosen:
        _audit_logger.debug("tui select.cancel: %s", title)
        return
    for idx in chosen:
        item = items[idx] if 0 <= idx < len(items) else f"<index {idx}>"
        _audit_logger.debug("tui select.choose: %s -> [%d] %s", title, idx, item)


def log_input(prompt: str, value: str, cancelled: bool) -> None:
    """Log the outcome of a TUI input prompt (DEBUG).

    The *value* is the user's typed answer and may contain key material
    references, paths, or identifiers; it is audited verbatim because
    this log already records private-key filenames and profile IDs.
    ``cancelled`` marks an Esc abort (logged without a value).
    """
    if cancelled:
        _audit_logger.debug("tui input.cancel: %s", prompt)
        return
    _audit_logger.debug("tui input.submit: %s -> %r", prompt, value)


def log_confirmation(prompt: str, confirmed: bool) -> None:
    """Log a TUI yes/no confirmation (DEBUG)."""
    _audit_logger.debug("tui confirm: %s -> %s", prompt, "yes" if confirmed else "no")


def log_message_screen(title: str) -> None:
    """Log a TUI message/result screen the user was shown (DEBUG)."""
    _audit_logger.debug("tui message: %s", title)


def log_action_start(interface: str, action_id: str, detail: str = "") -> None:
    """Log the start of a dispatched action (INFO)."""
    _audit_logger.info(_msg(interface, f"action.start {action_id}", detail))


def log_action_end(interface: str, action_id: str, outcome: str) -> None:
    """Log the end of a dispatched action, e.g. exit code or error (INFO)."""
    _audit_logger.info(_msg(interface, f"action.end {action_id}", outcome))


def log_cli_command(argv: list[str]) -> None:
    """Log the raw CLI argument vector at session start (INFO)."""
    try:
        rendered = " ".join(a if " " not in a else repr(a) for a in argv)
    except TypeError:  # pragma: no cover - defensive, argv is always str
        rendered = repr(argv)
    _audit_logger.info("cli session.start: argv %s", rendered)


def current_interface() -> str:
    """Return ``tui`` or ``cli`` depending on how the process was invoked.

    Used to attribute audit records when the entry path is ambiguous.
    """
    return "tui" if sys.stdin.isatty() and not sys.argv[1:] else "cli"
