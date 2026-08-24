"""Create Config wizard — guided profile creation with partitions."""

from __future__ import annotations

import contextlib
import curses
from pathlib import Path

from avbpowertool.application.commands import ConfigCreateRequest
from avbpowertool.application.ports import AvbToolPort
from avbpowertool.application.services.manage_configs import ConfigCreateUseCase
from avbpowertool.domain.models import (
    DescriptorType,
    PartitionConfig,
    SigningAlgorithm,
)
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.presentation.i18n import _
from avbpowertool.presentation.tui.widgets import (
    SelectorWidget,
    confirm_dialog,
    input_prompt,
    message_screen,
)


def show(stdscr: object, ws: WorkspacePaths, avb: AvbToolPort) -> None:
    """Config creation wizard."""
    stdscr_c: curses.window = stdscr  # type: ignore[assignment]

    # Step 1: Profile ID
    profile_id = input_prompt(stdscr_c, _("config.wizard.enter_id"))
    if not profile_id or not profile_id.strip():
        return
    profile_id = profile_id.strip()

    # Step 2: Profile name
    profile_name = input_prompt(stdscr_c, _("config.wizard.enter_name"))
    if not profile_name or not profile_name.strip():
        profile_name = profile_id

    # Step 3: Choose creation mode
    mode_options = [
        _("config.wizard.mode_manual"),
        _("config.wizard.mode_auto"),
    ]
    mode_sel = SelectorWidget(_("config.wizard.choose_mode"), mode_options)
    mode_result = mode_sel.run(stdscr_c)
    if not mode_result:
        return

    if mode_result[0] == 0:
        partitions = _collect_partitions_manual(stdscr_c, ws, avb, profile_id)
    else:
        partitions = _collect_partitions_auto(stdscr_c, ws, avb, profile_id)

    if partitions is None:
        return

    # Step 4: Confirm
    if not partitions:
        message_screen(
            stdscr_c,
            _("config.wizard.no_partitions_title"),
            [_("config.wizard.no_partitions_msg")],
        )
        return

    summary = [
        f"{_('config.wizard.summary_id')}: {profile_id}",
        f"{_('config.wizard.summary_name')}: {profile_name}",
        f"{_('config.wizard.summary_partitions')}: {len(partitions)}",
        "",
    ]
    for p in partitions:
        summary.append(f"  - {p.partition_name}: {p.descriptor.value}, {p.algorithm.value}")

    message_screen(stdscr_c, _("config.wizard.step_confirm"), summary)
    if not confirm_dialog(stdscr_c, _("config.wizard.confirm_create")):
        return

    # Step 5: Create
    uc = ConfigCreateUseCase(ws)
    result = uc.execute(
        ConfigCreateRequest(
            profile_id=profile_id,
            profile_name=profile_name,
            partitions=tuple(partitions),
            activate=True,
        )
    )

    lines: list[str] = []
    if not result.issues:
        lines.append(_("config.wizard.created", profile=profile_id))
    for iss in result.issues:
        lines.append(f"  [{iss.error_code}] {iss.message}")

    message_screen(stdscr_c, _("config.wizard.result_title"), lines)


def _collect_partitions_manual(
    stdscr: curses.window,
    ws: WorkspacePaths,
    avb: AvbToolPort,
    profile_id: str,
) -> list[PartitionConfig] | None:
    """Collect partitions interactively."""
    partitions: list[PartitionConfig] = []

    while True:
        lines = [_("config.wizard.current_partitions")]
        if not partitions:
            lines.append(f"  ({_('config.wizard.no_partitions')})")
        for i, p in enumerate(partitions):
            lines.append(
                f"  {i + 1}. {p.partition_name} ({p.descriptor.value}, {p.algorithm.value})"
            )
        lines.append("")
        lines.append(_("config.wizard.add_partition_hint"))

        message_screen(stdscr, _("config.wizard.step_partitions"), lines)

        if not confirm_dialog(stdscr, _("config.wizard.add_partition_confirm")):
            break

        partition = _collect_partition(stdscr)
        if partition is not None:
            partitions.append(partition)

    return partitions


def _collect_partitions_auto(
    stdscr: curses.window,
    ws: WorkspacePaths,
    avb: AvbToolPort,
    profile_id: str,
) -> list[PartitionConfig] | None:
    """Auto-generate config from images in a directory."""

    from avbpowertool.application.commands import InspectImagesRequest
    from avbpowertool.application.services.inspect_images import InspectImagesUseCase

    # Ask for image directory
    dir_path = input_prompt(stdscr, _("config.wizard.auto_dir"))
    if not dir_path or not dir_path.strip():
        return None

    image_dir = Path(dir_path.strip())
    if not image_dir.is_dir():
        message_screen(stdscr, "Error", [_("config.wizard.auto_dir_not_found")])
        return None

    # Scan for .img files
    image_names: list[str] = []
    for f in sorted(image_dir.iterdir()):
        if f.suffix == ".img" and f.is_file():
            image_names.append(f.stem)

    if not image_names:
        message_screen(stdscr, "Error", [_("config.wizard.auto_no_images")])
        return None

    # Show found images
    found_lines = [_("config.wizard.auto_found", count=len(image_names))]
    for name in image_names:
        found_lines.append(f"  - {name}")
    message_screen(stdscr, _("config.wizard.auto_scanning"), found_lines)

    # Inspect images
    uc = InspectImagesUseCase(ws, avb)
    result = uc.execute(InspectImagesRequest(image_names=tuple(image_names)))

    partitions: list[PartitionConfig] = []
    for img in result.images:
        if img.descriptor is None:
            continue

        # Determine key_id from public_key_sha1 or default
        key_id = "default"

        # Map descriptor type
        descriptor = img.descriptor
        algorithm = SigningAlgorithm.SHA256_RSA4096
        if img.algorithm:
            with contextlib.suppress(ValueError):
                algorithm = SigningAlgorithm.from_str(img.algorithm)

        # Build props from inspection
        props = img.props if img.props else ()

        # Determine flags from inspection
        flags = 0
        if img.flags:
            with contextlib.suppress(ValueError):
                flags = int(img.flags)

        partitions.append(
            PartitionConfig(
                image=f"{img.image_name}.img",
                descriptor=descriptor,
                algorithm=algorithm,
                key_id=key_id,
                partition_name=img.partition_name or img.image_name,
                rollback_index=int(img.rollback_index) if img.rollback_index else 0,
                salt=img.salt or "",
                flags=flags,
                props=props,
            )
        )

    # Show results
    result_lines = [_("config.wizard.auto_result", count=len(partitions))]
    for p in partitions:
        result_lines.append(f"  - {p.partition_name}: {p.descriptor.value}, {p.algorithm.value}")
    for iss in result.issues:
        result_lines.append(f"  [{iss.error_code}] {iss.message}")

    message_screen(stdscr, _("config.wizard.auto_result_title"), result_lines)
    return partitions


def _collect_partition(stdscr: curses.window) -> PartitionConfig | None:
    """Collect a single partition config interactively."""
    # Partition name
    name = input_prompt(stdscr, _("config.wizard.partition_name"))
    if not name or not name.strip():
        return None
    name = name.strip()

    # Image filename
    image = input_prompt(stdscr, _("config.wizard.partition_image"))
    if not image or not image.strip():
        image = f"{name}.img"
    image = image.strip()

    # Descriptor type
    desc_options = ["hash", "hashtree", "vbmeta"]
    desc_sel = SelectorWidget(_("config.wizard.descriptor_type"), desc_options)
    desc_result = desc_sel.run(stdscr)
    if not desc_result:
        return None
    descriptor = DescriptorType(desc_options[desc_result[0]])

    # Algorithm
    alg_options = [a.value for a in SigningAlgorithm if a != SigningAlgorithm.NONE]
    alg_sel = SelectorWidget(_("config.wizard.algorithm"), alg_options)
    alg_result = alg_sel.run(stdscr)
    if not alg_result:
        return None
    algorithm = SigningAlgorithm(alg_options[alg_result[0]])

    # Key ID
    key_id = input_prompt(stdscr, _("config.wizard.key_id"))
    if not key_id or not key_id.strip():
        key_id = "default"
    key_id = key_id.strip()

    # Rollback index
    rb_str = input_prompt(stdscr, _("config.wizard.rollback_index"))
    try:
        rollback_index = int(rb_str) if rb_str.strip() else 0
    except ValueError:
        rollback_index = 0

    # Rollback index location
    rbl_str = input_prompt(stdscr, _("config.wizard.rollback_index_location"))
    try:
        rollback_index_location = int(rbl_str) if rbl_str.strip() else 0
    except ValueError:
        rollback_index_location = 0

    # Salt (optional)
    salt = input_prompt(stdscr, _("config.wizard.salt"))
    salt = salt.strip() if salt else ""

    # Flags
    flags_str = input_prompt(stdscr, _("config.wizard.flags"))
    try:
        flags = int(flags_str) if flags_str.strip() else 0
    except ValueError:
        flags = 0

    # Flag shortcuts
    set_ht_disabled = False
    set_vb_disabled = False
    if confirm_dialog(stdscr, _("config.wizard.set_ht_disabled")):
        set_ht_disabled = True
    if confirm_dialog(stdscr, _("config.wizard.set_vb_disabled")):
        set_vb_disabled = True

    return PartitionConfig(
        image=image,
        descriptor=descriptor,
        algorithm=algorithm,
        key_id=key_id,
        partition_name=name,
        rollback_index=rollback_index,
        rollback_index_location=rollback_index_location,
        salt=salt,
        flags=flags,
        set_hashtree_disabled_flag=set_ht_disabled,
        set_verification_disabled_flag=set_vb_disabled,
    )
