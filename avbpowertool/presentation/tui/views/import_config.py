"""Import Config view — select and import a ZIP archive."""

from __future__ import annotations

import curses

from avbpowertool.application.commands import ConfigImportRequest
from avbpowertool.application.ports import AvbToolPort
from avbpowertool.application.services.manage_configs import ConfigImportUseCase
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.presentation.tui.widgets import (
    SelectorWidget,
    message_screen,
)


def show(stdscr: object, ws: WorkspacePaths, avb: AvbToolPort) -> None:
    """Import config view."""
    stdscr_c: curses.window = stdscr  # type: ignore[assignment]

    # Find ZIP files in project root
    zip_files: list[str] = []
    for f in sorted(ws.root.iterdir()):
        if f.suffix == ".zip" and f.is_file():
            zip_files.append(f.name)

    if not zip_files:
        message_screen(stdscr_c, "Import Config", ["No .zip files found in project root."])
        return

    sel = SelectorWidget("Select Archive to Import", zip_files)
    chosen = sel.run(stdscr_c)
    if not chosen:
        return

    archive_name = zip_files[chosen[0]]
    archive_path = str(ws.root / archive_name)

    uc = ConfigImportUseCase(ws)
    request = ConfigImportRequest(archive_path=archive_path)
    result = uc.execute(request)

    lines: list[str] = []
    if result.profile_id:
        lines.append(f"Imported profile: {result.profile_id}")
    for iss in result.issues:
        lines.append(f"  [{iss.error_code}] {iss.message}")

    message_screen(stdscr_c, "Import Result", lines)
