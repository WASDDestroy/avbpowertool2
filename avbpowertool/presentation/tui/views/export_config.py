"""Export Config view — export a profile as ZIP archive."""

from __future__ import annotations

import curses

from avbpowertool.application.commands import ConfigExportRequest
from avbpowertool.application.ports import AvbToolPort
from avbpowertool.application.services.manage_configs import ConfigExportUseCase
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.presentation.i18n import _
from avbpowertool.presentation.tui.widgets import (
    SelectorWidget,
    message_screen,
)


def show(stdscr: object, ws: WorkspacePaths, avb: AvbToolPort) -> None:
    """Export config view."""
    stdscr_c: curses.window = stdscr  # type: ignore[assignment]

    from avbpowertool.infrastructure.persistence.profile_repository import ProfileRepository

    repo = ProfileRepository(ws)
    profile_ids = repo.list_profiles()

    if not profile_ids:
        message_screen(stdscr_c, _("export.title"), [_("library.no_profiles")])
        return

    sel = SelectorWidget(_("export.select_profile"), list(profile_ids))
    chosen = sel.run(stdscr_c)
    if not chosen:
        return

    profile_id = profile_ids[chosen[0]]
    output_path = str(ws.root / f"{profile_id}.zip")

    uc = ConfigExportUseCase(ws)
    request = ConfigExportRequest(profile_id=profile_id, output_path=output_path)
    result = uc.execute(request)

    lines: list[str] = []
    if not any(i.error_code.startswith("config.export") for i in result.issues):
        lines.append(_("export.success", path=result.output_path))
    for iss in result.issues:
        lines.append(f"  [{iss.error_code}] {iss.message}")

    message_screen(stdscr_c, _("export.result_title"), lines)
