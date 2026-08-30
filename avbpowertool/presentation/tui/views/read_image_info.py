"""Read Image Info view — select and inspect images."""

from __future__ import annotations

from avbpowertool.application.commands import InspectImagesRequest
from avbpowertool.application.ports import AvbToolPort
from avbpowertool.application.services.inspect_images import InspectImagesUseCase
from avbpowertool.domain.models import ImageInspection
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.presentation.i18n import _
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
        message_screen(stdscr_c, _("read_image_info.title"), [_("read_image_info.no_images_dir")])
        return

    images: list[str] = []
    for f in sorted(ws.images.iterdir()):
        if f.suffix == ".img" and f.is_file():
            images.append(f.stem)

    if not images:
        message_screen(stdscr_c, _("read_image_info.title"), [_("read_image_info.no_images")])
        return

    # Multi-select
    sel = SelectorWidget(_("read_image_info.select_title"), images, multi_select=True)
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

    message_screen(stdscr_c, _("read_image_info.results_title"), lines)


def image_inspection_lines(img: ImageInspection) -> list[str]:
    """Render one image inspection into display lines (all metadata).

    Unlike the config page, which only reports the fields it persists,
    the read-image-info page inspects images in isolation, so every
    field parsed from the AVB metadata is shown.
    """
    lines: list[str] = [f"[{img.image_name}]"]
    lines.append(_("read_image_info.field.path", value=img.image_path))
    lines.append(
        _(
            "read_image_info.field.descriptor",
            value=img.descriptor.value if img.descriptor else _("common.not_available"),
        )
    )
    if img.algorithm:
        lines.append(_("read_image_info.field.algorithm", value=img.algorithm))
    if img.partition_name:
        lines.append(_("read_image_info.field.partition_name", value=img.partition_name))
    if img.public_key_sha1:
        lines.append(_("read_image_info.field.public_key_sha1", value=img.public_key_sha1))
    if img.rollback_index is not None:
        lines.append(_("read_image_info.field.rollback_index", value=img.rollback_index))
    if img.rollback_index_location is not None:
        lines.append(
            _("read_image_info.field.rollback_index_location", value=img.rollback_index_location)
        )
    if img.hash_algorithm:
        lines.append(_("read_image_info.field.hash_algorithm", value=img.hash_algorithm))
    if img.salt:
        lines.append(_("read_image_info.field.salt", value=img.salt))
    if img.digest:
        lines.append(_("read_image_info.field.digest", value=img.digest))
    if img.flags:
        lines.append(_("read_image_info.field.flags", value=img.flags))
    for key, value in img.props:
        lines.append(_("read_image_info.field.prop", key=key, value=value))
    if img.included_partitions:
        lines.append(
            _("read_image_info.field.included_partitions", value=", ".join(img.included_partitions))
        )
    for chain in img.chain_descriptors:
        lines.append(
            _(
                "read_image_info.field.chain",
                name=chain.partition_name,
                slot=chain.rollback_index_location,
                pubkey=chain.public_key_sha1 or _("common.not_available"),
            )
        )
    for key, value in img.raw_extensions:
        lines.append(f"  {key}: {value}")

    return lines


def _get_active_profile(ws: WorkspacePaths) -> str:
    """Get active profile ID or default to 'current'."""
    from avbpowertool.infrastructure.persistence.profile_repository import ProfileRepository

    repo = ProfileRepository(ws)
    return repo.get_active_profile_id() or "current"
