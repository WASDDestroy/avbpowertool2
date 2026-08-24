"""Create Config wizard — guided profile creation with partitions."""

from __future__ import annotations

import curses

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

    # Step 3: Add partitions
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

        message_screen(stdscr_c, _("config.wizard.step_partitions"), lines)

        if not confirm_dialog(stdscr_c, _("config.wizard.add_partition_confirm")):
            break

        partition = _collect_partition(stdscr_c)
        if partition is not None:
            partitions.append(partition)

    # Step 4: Confirm
    if not partitions:
        message_screen(
            stdscr_c, _("config.wizard.no_partitions_title"), [_("config.wizard.no_partitions_msg")]
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

    if not confirm_dialog(
        stdscr_c, "\n".join(summary) + "\n\n" + _("config.wizard.confirm_create")
    ):
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

    # Salt (optional)
    salt = input_prompt(stdscr, _("config.wizard.salt"))
    salt = salt.strip() if salt else ""

    return PartitionConfig(
        image=image,
        descriptor=descriptor,
        algorithm=algorithm,
        key_id=key_id,
        partition_name=name,
        rollback_index=rollback_index,
        salt=salt,
    )
