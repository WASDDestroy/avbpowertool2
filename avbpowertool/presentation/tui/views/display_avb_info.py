"""Display AVB Info view — show current config information."""

from __future__ import annotations

import curses

from avbpowertool.application.commands import ConfigShowRequest
from avbpowertool.application.ports import AvbToolPort
from avbpowertool.application.services.manage_configs import ConfigShowUseCase
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.presentation.tui.widgets import message_screen


def show(stdscr: object, ws: WorkspacePaths, avb: AvbToolPort) -> None:
    """Display current config info."""
    stdscr_c: curses.window = stdscr  # type: ignore[assignment]

    from avbpowertool.infrastructure.persistence.profile_repository import ProfileRepository

    repo = ProfileRepository(ws)
    active_id = repo.get_active_profile_id() or "current"

    uc = ConfigShowUseCase(ws)
    result = uc.execute(ConfigShowRequest(profile_id=active_id))

    lines: list[str] = []
    lines.append(f"Profile: {result.config_name}")
    lines.append("")

    if not result.partitions:
        lines.append("No partitions configured.")
    else:
        for p in result.partitions:
            lines.append(f"[{p.partition_name}]")
            lines.append(f"  Image: {p.image}")
            lines.append(f"  Descriptor: {p.descriptor.value}")
            lines.append(f"  Algorithm: {p.algorithm.value}")
            lines.append(f"  Key ID: {p.key_id}")
            lines.append("")

    for iss in result.issues:
        lines.append(f"  [{iss.error_code}] {iss.message}")

    message_screen(stdscr_c, "Current Config Info", lines)
