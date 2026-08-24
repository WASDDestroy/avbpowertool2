"""Composition root — wire all dependencies at startup."""

from __future__ import annotations

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

    return ws
