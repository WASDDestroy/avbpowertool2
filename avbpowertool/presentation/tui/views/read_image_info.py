"""Read Image Info view — select and inspect images."""

from __future__ import annotations

from avbpowertool.application.commands import InspectImagesRequest
from avbpowertool.application.ports import AvbToolPort
from avbpowertool.application.services.inspect_images import InspectImagesUseCase
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.presentation.tui.widgets import (
    SelectorWidget,
    message_screen,
)


def show(stdscr: object, ws: WorkspacePaths, avb: AvbToolPort) -> None:
    """Read image info view."""
    import curses

    stdscr_c: curses.window = stdscr  # type: ignore[assignment]

    # Find images in profile directory
    active_id = _get_active_profile(ws)
    profile_dir = ws.resolve_profile_dir(active_id)

    if not profile_dir.exists():
        message_screen(stdscr_c, "Read Image Info", ["No active profile found."])
        return

    # Scan for .img files
    images: list[str] = []
    for f in sorted(profile_dir.iterdir()):
        if f.suffix == ".img" and f.is_file():
            images.append(f.stem)

    if not images:
        message_screen(stdscr_c, "Read Image Info", ["No .img files found in profile directory."])
        return

    # Multi-select
    sel = SelectorWidget("Select Images to Read", images, multi_select=True)
    chosen = sel.run(stdscr_c)
    if not chosen:
        return

    selected_names = [images[i] for i in chosen]

    # Inspect
    uc = InspectImagesUseCase(ws, avb)
    request = InspectImagesRequest(image_names=tuple(selected_names), profile_id=active_id)
    result = uc.execute(request)

    # Display results
    lines: list[str] = []
    for img in result.images:
        lines.append(f"[{img.image_name}]")
        lines.append(f"  Path: {img.image_path}")
        lines.append(f"  Descriptor: {img.descriptor.value if img.descriptor else 'N/A'}")
        if img.algorithm:
            lines.append(f"  Algorithm: {img.algorithm}")
        if img.partition_name:
            lines.append(f"  Partition: {img.partition_name}")
        lines.append("")

    for iss in result.issues:
        lines.append(f"  [{iss.error_code}] {iss.message}")

    message_screen(stdscr_c, "Image Info Results", lines)


def _get_active_profile(ws: WorkspacePaths) -> str:
    """Get active profile ID or default to 'current'."""
    from avbpowertool.infrastructure.persistence.profile_repository import ProfileRepository

    repo = ProfileRepository(ws)
    return repo.get_active_profile_id() or "current"
