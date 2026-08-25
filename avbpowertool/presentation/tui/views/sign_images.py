"""Sign Images view — select images and sign them."""

from __future__ import annotations

import curses

from avbpowertool.application.commands import SignImagesRequest
from avbpowertool.application.ports import AvbToolPort
from avbpowertool.application.services.sign_images import SignImagesUseCase
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.presentation.i18n import _
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

    # If a vbmeta partition is being generated, ask whether the config's
    # props should be attached to the new vbmeta image (default: No —
    # props read back from images are usually duplicates of build info).
    include_vbmeta_props = False
    if _has_vbmeta_partition(ws, active_id, selected_names):
        props_sel = SelectorWidget(_("sign.vbmeta.props_prompt"), ["No", "Yes"])
        props_choice = props_sel.run(stdscr_c)
        if props_choice and props_choice[0] == 1:
            include_vbmeta_props = True

    # Execute signing
    uc = SignImagesUseCase(ws, avb)
    request = SignImagesRequest(
        image_names=tuple(selected_names),
        profile_id=active_id,
        dry_run=False,
        include_vbmeta_props=include_vbmeta_props,
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


def _has_vbmeta_partition(ws: WorkspacePaths, profile_id: str, selected_names: list[str]) -> bool:
    """True if any selected image is a vbmeta partition in the profile."""
    from avbpowertool.domain.models import DescriptorType
    from avbpowertool.infrastructure.persistence.profile_repository import (
        ProfileRepository,
    )

    wanted = {f"{name}.img" for name in selected_names}
    try:
        profile = ProfileRepository(ws).load(profile_id)
    except Exception:
        return False
    return any(
        config.descriptor == DescriptorType.VBMETA and config.image in wanted
        for config in profile.partitions.values()
    )
