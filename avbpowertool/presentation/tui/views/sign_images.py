"""Sign Images view — select images and sign them."""

from __future__ import annotations

import curses

from avbpowertool.application.commands import SignImagesRequest
from avbpowertool.application.ports import AvbToolPort
from avbpowertool.application.services.sign_images import SignImagesUseCase
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.presentation.tui.widgets import (
    SelectorWidget,
    confirm_dialog,
    message_screen,
)


def show(stdscr: object, ws: WorkspacePaths, avb: AvbToolPort) -> None:
    """Sign images view."""
    stdscr_c: curses.window = stdscr  # type: ignore[assignment]

    active_id = _get_active_profile(ws)

    if not ws.images.exists():
        message_screen(stdscr_c, "Sign Images", ["No Images/ directory found."])
        return

    images: list[str] = []
    for f in sorted(ws.images.iterdir()):
        if f.suffix == ".img" and f.is_file():
            images.append(f.stem)

    if not images:
        message_screen(stdscr_c, "Sign Images", ["No .img files found in Images/ directory."])
        return

    # Confirm
    if not confirm_dialog(stdscr_c, "Sign images? This will modify image files."):
        return

    # Multi-select
    sel = SelectorWidget("Select Images to Sign", images, multi_select=True)
    chosen = sel.run(stdscr_c)
    if not chosen:
        return

    selected_names = [images[i] for i in chosen]

    # Execute signing
    uc = SignImagesUseCase(ws, avb)
    request = SignImagesRequest(
        image_names=tuple(selected_names),
        profile_id=active_id,
        dry_run=False,
    )
    result = uc.execute(request)

    # Display results
    lines: list[str] = []
    if result.executed:
        lines.append(f"Success: {result.success_count}, Failed: {result.fail_count}")
    else:
        lines.append("Dry run completed.")
        lines.append(f"Steps planned: {len(result.plan.steps)}")

    for step in result.plan.steps:
        lines.append(f"  [{step.order}] {step.operation} {step.partition_name}")

    for iss in result.issues:
        lines.append(f"  [{iss.error_code}] {iss.message}")

    message_screen(stdscr_c, "Signing Results", lines)


def _get_active_profile(ws: WorkspacePaths) -> str:
    from avbpowertool.infrastructure.persistence.profile_repository import ProfileRepository

    repo = ProfileRepository(ws)
    return repo.get_active_profile_id() or "current"
