"""Read Image Info view — select and inspect images."""

from __future__ import annotations

from avbpowertool.application.commands import InspectImagesRequest
from avbpowertool.application.ports import AvbToolPort
from avbpowertool.application.services.inspect_images import InspectImagesUseCase
from avbpowertool.domain.models import ImageInspection
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.presentation.tui.widgets import (
    SelectorWidget,
    message_screen,
)


def show(stdscr: object, ws: WorkspacePaths, avb: AvbToolPort) -> None:
    """Read image info view."""
    import curses

    stdscr_c: curses.window = stdscr  # type: ignore[assignment]

    # Find images in workspace Images/ directory
    active_id = _get_active_profile(ws)

    if not ws.images.exists():
        message_screen(stdscr_c, "Read Image Info", ["No Images/ directory found."])
        return

    images: list[str] = []
    for f in sorted(ws.images.iterdir()):
        if f.suffix == ".img" and f.is_file():
            images.append(f.stem)

    if not images:
        message_screen(stdscr_c, "Read Image Info", ["No .img files found in Images/ directory."])
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

    # Display results — this page never persists to a config file, so it
    # reports every piece of metadata read back from the images.
    lines: list[str] = []
    for img in result.images:
        lines.extend(image_inspection_lines(img))
        lines.append("")

    for iss in result.issues:
        lines.append(f"  [{iss.error_code}] {iss.message}")

    message_screen(stdscr_c, "Image Info Results", lines)


def image_inspection_lines(img: ImageInspection) -> list[str]:
    """Render one image inspection into display lines (all metadata).

    Unlike the config page, which only reports the fields it persists,
    the read-image-info page inspects images in isolation, so every
    field parsed from the AVB metadata is shown.
    """
    lines: list[str] = [f"[{img.image_name}]"]
    lines.append(f"  Path: {img.image_path}")
    lines.append(f"  Descriptor: {img.descriptor.value if img.descriptor else 'N/A'}")
    if img.algorithm:
        lines.append(f"  Algorithm: {img.algorithm}")
    if img.partition_name:
        lines.append(f"  Partition Name: {img.partition_name}")
    if img.public_key_sha1:
        lines.append(f"  Public Key SHA1: {img.public_key_sha1}")
    if img.rollback_index is not None:
        lines.append(f"  Rollback Index: {img.rollback_index}")
    if img.rollback_index_location is not None:
        lines.append(f"  Rollback Index Location: {img.rollback_index_location}")
    if img.hash_algorithm:
        lines.append(f"  Hash Algorithm: {img.hash_algorithm}")
    if img.salt:
        lines.append(f"  Salt: {img.salt}")
    if img.digest:
        lines.append(f"  Digest: {img.digest}")
    if img.flags:
        lines.append(f"  Flags: {img.flags}")
    for key, value in img.props:
        lines.append(f"  Prop: {key} = {value}")
    if img.included_partitions:
        lines.append(f"  Included Partitions: {', '.join(img.included_partitions)}")
    for chain in img.chain_descriptors:
        lines.append(
            f"  Chain: {chain.partition_name} "
            f"slot={chain.rollback_index_location} "
            f"pubkey={chain.public_key_sha1 or 'N/A'}"
        )
    for key, value in img.raw_extensions:
        lines.append(f"  {key}: {value}")

    return lines


def _get_active_profile(ws: WorkspacePaths) -> str:
    """Get active profile ID or default to 'current'."""
    from avbpowertool.infrastructure.persistence.profile_repository import ProfileRepository

    repo = ProfileRepository(ws)
    return repo.get_active_profile_id() or "current"
