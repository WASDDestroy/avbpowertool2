"""Composition root — wire all dependencies at startup."""

from __future__ import annotations

import logging
from pathlib import Path

from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.presentation.i18n import init_i18n


def bootstrap(root: Path | None = None, language: str = "en") -> WorkspacePaths:
    """Initialize the application and return workspace paths.

    Args:
        root: Project root directory. Defaults to cwd.
        language: Language code for i18n.

    Returns:
        Initialized WorkspacePaths.
    """
    # Initialize i18n
    init_i18n(language=language)

    # Discover workspace
    ws = WorkspacePaths.discover(root)
    ws.ensure_dirs()

    log_path = ws.logs / "avbpowertool.log"
    root_logger = logging.getLogger()
    if not any(
        isinstance(h, logging.FileHandler)
        and getattr(h, "baseFilename", "") == str(log_path.resolve())
        for h in root_logger.handlers
    ):
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.INFO)

    return ws
