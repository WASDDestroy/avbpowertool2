"""Miscellaneous features view — legacy (v1) config import."""

from __future__ import annotations

import curses

from avbpowertool.application.commands import LegacyImportRequest
from avbpowertool.application.ports import AvbToolPort
from avbpowertool.application.services.manage_configs import LegacyConfigImportUseCase
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.presentation.i18n import _
from avbpowertool.presentation.tui.widgets import (
    SelectorWidget,
    message_screen,
)


def show_import_legacy(stdscr: object, ws: WorkspacePaths, avb: AvbToolPort) -> None:
    """Import a legacy (v1) config archive, converting it to v2."""
    stdscr_c: curses.window = stdscr  # type: ignore[assignment]

    # Find ZIP files in project root
    zip_files: list[str] = []
    for f in sorted(ws.root.iterdir()):
        if f.suffix == ".zip" and f.is_file():
            zip_files.append(f.name)

    if not zip_files:
        message_screen(stdscr_c, _("legacy.import.title"), [_("legacy.import.no_archives")])
        return

    sel = SelectorWidget(_("legacy.import.select_archive"), zip_files)
    chosen = sel.run(stdscr_c)
    if not chosen:
        return

    archive_name = zip_files[chosen[0]]
    archive_path = str(ws.root / archive_name)

    uc = LegacyConfigImportUseCase(ws)
    request = LegacyImportRequest(archive_path=archive_path)
    result = uc.execute(request)

    lines: list[str] = []
    if result.profile_id:
        lines.append(
            _(
                "legacy.import.success",
                profile=result.profile_id,
                partitions=result.partition_count,
                keys=result.key_count,
            )
        )
    for iss in result.issues:
        lines.append(f"  [{iss.error_code}] {iss.message}")

    message_screen(stdscr_c, _("legacy.import.title"), lines)
