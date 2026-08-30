"""Composition root — wire all dependencies at startup."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.persistence.settings_repository import SettingsRepository
from avbpowertool.presentation.i18n import init_i18n

# Every TUI/CLI session opens its own log file named by its start time:
# Logs/avbpowertool_<YYYYmmdd>_<HHMMSS>.log.  A numeric suffix (_2, _3,
# ...) disambiguates sessions that start within the same second.
LOG_FILE_STAMP_FORMAT = "%Y%m%d_%H%M%S"

# The audit namespace records the user's TUI/CLI action trail at DEBUG;
# it must never be silently swallowed even when the root level is INFO,
# so it gets an explicit (optionally overridden) level below.
AUDIT_LOGGER_NAME = "avbpowertool.audit"

# File handler of the log opened for the current session.  A process
# normally opens exactly one; when setup runs again (re-bootstrap,
# tests) the previous file is closed and replaced.
_session_handler: logging.FileHandler | None = None


def _configure_audit_logger(level: int) -> None:
    """Pin the audit logger to its own level, independent of the root level.

    DEBUG audit detail (navigation trail, selections) is only emitted
    when the effective level allows it; INFO audit records (session
    boundaries, CLI commands) always pass through unless the user chose
    WARNING or ERROR.
    """
    logging.getLogger(AUDIT_LOGGER_NAME).setLevel(level)


def session_log_path(logs_dir: Path) -> Path:
    """Return a fresh per-session log path named by the current time.

    The name is guaranteed not to collide with an existing file: when
    this second's name is taken (two sessions started within one
    second), a numeric suffix is appended.
    """
    stamp = datetime.now().strftime(LOG_FILE_STAMP_FORMAT)
    path = logs_dir / f"avbpowertool_{stamp}.log"
    suffix = 2
    while path.exists():
        path = logs_dir / f"avbpowertool_{stamp}_{suffix}.log"
        suffix += 1
    return path


def setup_logging(ws: WorkspacePaths, level_name: str) -> Path:
    """Open this session's log file and apply the effective log level.

    Every call creates a new timestamped file — one per TUI launch or
    CLI invocation — and closes the previous session's handler when
    setup runs twice within the same process.  Returns the log path.
    """
    global _session_handler
    log_path = session_log_path(ws.logs)
    root_logger = logging.getLogger()

    if _session_handler is not None:
        root_logger.removeHandler(_session_handler)
        _session_handler.close()
        _session_handler = None

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root_logger.addHandler(handler)
    _session_handler = handler

    # The root logger captures DEBUG from all modules so nothing is lost
    # before filtering; the audit logger applies the user-chosen level.
    root_logger.setLevel(logging.DEBUG)
    _configure_audit_logger(_level_from_name(level_name))
    return log_path


def _level_from_name(level_name: str) -> int:
    """Map a settings.json log_level name to a logging level.

    Unknown names fall back to INFO rather than raising: a typo in the
    settings file must not make the tool unusable.
    """
    return logging.getLevelNamesMapping().get((level_name or "INFO").upper(), logging.INFO)


def bootstrap(root: Path | None = None, language: str | None = None) -> WorkspacePaths:
    """Initialize the application and return workspace paths.

    Args:
        root: Project root directory. Defaults to cwd.
        language: Language code for i18n. When None (default), the
            persisted ``language`` setting from ``settings.json`` is used,
            falling back to 'en' when no setting exists.

    Returns:
        Initialized WorkspacePaths.
    """
    # Discover workspace
    ws = WorkspacePaths.discover(root)
    ws.ensure_dirs()

    settings = SettingsRepository(ws.root).load()

    # Resolve language: explicit argument wins, otherwise use the persisted
    # setting saved by the TUI settings view (e.g. user selected Chinese).
    if language is None:
        language = settings.language

    # Initialize i18n
    init_i18n(language=language)

    # Logging: each session opens its own timestamped log file with the
    # persisted log_level applied (default INFO).
    log_path = setup_logging(ws, settings.log_level)
    logging.getLogger(__name__).debug(
        "session started: root=%s language=%s log=%s", ws.root, language, log_path
    )

    return ws
