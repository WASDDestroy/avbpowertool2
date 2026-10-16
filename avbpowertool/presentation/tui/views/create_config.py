"""Create Config wizard — guided profile creation with partitions."""

from __future__ import annotations

import contextlib
import curses
from pathlib import Path

from avbpowertool.application.commands import (
    ConfigAutoCreateRequest,
    ConfigCreateRequest,
)
from avbpowertool.application.ports import AvbToolPort
from avbpowertool.application.services.config_auto_create import (
    ConfigAutoCreateUseCase,
)
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

    # Step 4: Prepare the key store BEFORE collecting partitions, so the
    # manual mode can offer real key_ids and auto mode's chain-partition
    # resolution has a populated manifest to match against.
    available_keys = _prepare_keys(stdscr_c, ws, avb, profile_id)

    if mode_result[0] == 0:
        partitions = _collect_partitions_manual(stdscr_c, ws, avb, profile_id, available_keys)
    else:
        partitions = _collect_partitions_auto(stdscr_c, ws, avb, profile_id, available_keys)

    if partitions is None:
        return

    # Step 5: Confirm
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


def _prepare_keys(
    stdscr: curses.window, ws: WorkspacePaths, avb: AvbToolPort, profile_id: str
) -> list[str]:
    """Ensure the key store exists and run key discovery.

    Runs BEFORE any image is scanned or any partition is collected, so
    manual mode can offer the real key_ids and auto mode's chain
    resolution has a populated manifest to match public keys against.
    Returns the discovered key_ids.
    """
    from avbpowertool.application.commands import KeyDiscoveryRequest
    from avbpowertool.application.services.manage_keys import KeyDiscoveryUseCase

    key_dir = ws.resolve_key_dir(profile_id)
    try:
        key_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        message_screen(stdscr, _("config.wizard.key_prepare_title"), [str(exc)])
        return []

    message_screen(
        stdscr,
        _("config.wizard.key_prepare_title"),
        [
            _("config.wizard.key_prepare_msg", path=str(key_dir)),
            "",
            _("config.wizard.key_prepare_continue"),
        ],
    )

    result = KeyDiscoveryUseCase(ws).execute(KeyDiscoveryRequest(profile_id=profile_id))
    from avbpowertool.application.services.manage_keys import ensure_public_keys

    public_key_issues = ensure_public_keys(ws, avb, profile_id)

    lines = [_("config.wizard.key_discovered", count=result.discovered_count)]
    for key_id, filename in result.manifest_entries:
        lines.append(f"  {key_id} -> {filename}")
    if not result.manifest_entries:
        lines.append(_("config.wizard.key_none"))
    for iss in result.issues:
        lines.append(f"  [{iss.error_code}] {iss.message}")
    for iss in public_key_issues:
        lines.append(f"  [{iss.error_code}] {iss.message}")

    message_screen(stdscr, _("keys.discover_title"), lines)
    return [key_id for key_id, _filename in result.manifest_entries]


def _collect_partitions_manual(
    stdscr: curses.window,
    ws: WorkspacePaths,
    avb: AvbToolPort,
    profile_id: str,
    available_keys: list[str],
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

        partition = _collect_partition(stdscr, available_keys)
        if partition is not None:
            partitions.append(partition)

    return partitions


def _auto_dir_default(ws: WorkspacePaths) -> tuple[Path, str]:
    """Return the default auto-mode scan directory and its display form.

    The workspace-level ``Images/`` directory is the project-wide
    default (aligned with the legacy implementation's ``./Images``).
    The display form stays relative to the current working directory
    whenever possible so prompts remain short.
    """
    default_dir = ws.images
    try:
        return default_dir, f"./{default_dir.relative_to(Path.cwd())}"
    except ValueError:
        return default_dir, str(default_dir)


def _collect_partitions_auto(
    stdscr: curses.window,
    ws: WorkspacePaths,
    avb: AvbToolPort,
    profile_id: str,
    available_keys: list[str],
) -> list[PartitionConfig] | None:
    """Auto-generate config from images in a directory."""

    # When keys were prepared, pick the default key_id for the generated
    # partitions (single key -> use it; several -> let the user choose).
    default_key_id = "default"
    if len(available_keys) == 1:
        default_key_id = available_keys[0]
    elif len(available_keys) > 1:
        key_options = available_keys + [_("config.wizard.key_custom")]
        key_sel = SelectorWidget(_("config.wizard.select_default_key"), key_options)
        key_choice = key_sel.run(stdscr)
        if key_choice and key_choice[0] < len(available_keys):
            default_key_id = available_keys[key_choice[0]]
        elif not key_choice:
            return None

    # Ask for image directory; pressing Enter accepts the workspace
    # default (./Images) so an empty answer no longer aborts the wizard.
    default_dir, default_display = _auto_dir_default(ws)
    dir_path = input_prompt(stdscr, _("config.wizard.auto_dir", default=default_display))
    raw = dir_path.strip() if dir_path else ""
    image_dir = Path(raw) if raw else default_dir
    if not image_dir.is_dir():
        message_screen(stdscr, _("app.error_title"), [_("config.wizard.auto_dir_not_found")])
        return None

    # Scan, inspect and turn every image into a partition config.  The
    # default key is only a fallback for the per-image key selection, so
    # ``key_id`` stays unset here.
    result = ConfigAutoCreateUseCase(ws, avb).execute(
        ConfigAutoCreateRequest(
            image_dir=image_dir,
            available_keys=tuple(available_keys),
            default_key_id=default_key_id,
            profile_id=profile_id,
        )
    )

    if not result.scanned_images:
        message_screen(stdscr, _("app.error_title"), [_("config.wizard.auto_no_images")])
        return None

    # Show found images
    found_lines = [_("config.wizard.auto_found", count=len(result.scanned_images))]
    for name in result.scanned_images:
        found_lines.append(f"  - {name}")
    message_screen(stdscr, _("config.wizard.auto_scanning"), found_lines)

    partitions = list(result.partitions)

    # Metadata read back from the images, in scan order.
    meta_lines = [
        f"{p.partition_name}: {p.descriptor.value} "
        f"alg={p.algorithm.value} rbi={p.rollback_index} "
        f"rbl={p.rollback_index_location} flags={p.flags} "
        f"props={len(p.props)} hash={p.hash_algorithm}"
        for p in partitions
    ]
    size_notes = [
        f"{p.partition_name}: {p.partition_size}" for p in partitions if p.partition_size > 0
    ]

    # Show results
    result_lines = [_("config.wizard.auto_result", count=len(partitions))]
    for p in partitions:
        result_lines.append(f"  - {p.partition_name}: {p.descriptor.value}, {p.algorithm.value}")
    if meta_lines:
        result_lines.append("")
        result_lines.append(_("config.wizard.auto_meta_note"))
        for line in meta_lines:
            result_lines.append(f"    {line}")
    if size_notes:
        result_lines.append("")
        result_lines.append(_("config.wizard.auto_size_note"))
        for note in size_notes:
            result_lines.append(f"    {note}")
    for iss in result.issues:
        result_lines.append(f"  [{iss.error_code}] {iss.message}")
    if result.chain_issues:
        result_lines.append("")
        result_lines.append(_("config.wizard.auto_chain_note"))
        for iss in result.chain_issues:
            result_lines.append(f"  [{iss.error_code}] {iss.message}")

    message_screen(stdscr, _("config.wizard.auto_result_title"), result_lines)
    return partitions


def _collect_partition(stdscr: curses.window, available_keys: list[str]) -> PartitionConfig | None:
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

    # Key ID — offered from the prepared key store when available
    key_id = ""
    if available_keys:
        key_options = available_keys + [_("config.wizard.key_custom")]
        key_sel = SelectorWidget(_("config.wizard.select_key"), key_options)
        key_result = key_sel.run(stdscr)
        if not key_result:
            return None
        if key_result[0] < len(available_keys):
            key_id = available_keys[key_result[0]]
    if not key_id:
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

    # --- Descriptor-specific v3 fields ---
    partition_size = 0
    dynamic_partition_size = False
    block_size = 4096
    fec_num_roots = 2
    do_not_generate_fec = False
    padding_size = 0
    kernel_cmdlines: tuple[str, ...] = ()
    chain_partitions_do_not_use_ab: tuple[str, ...] = ()
    props: tuple[tuple[str, str], ...] = ()

    if descriptor == DescriptorType.HASH:
        if confirm_dialog(stdscr, _("config.wizard.dynamic_partition_size")):
            dynamic_partition_size = True
        else:
            size_str = input_prompt(stdscr, _("config.wizard.partition_size"))
            with contextlib.suppress(ValueError):
                partition_size = int(size_str) if size_str.strip() else 0
    elif descriptor == DescriptorType.HASHTREE:
        bs_str = input_prompt(stdscr, _("config.wizard.block_size"))
        with contextlib.suppress(ValueError):
            block_size = int(bs_str) if bs_str.strip() else 4096
        fec_str = input_prompt(stdscr, _("config.wizard.fec_num_roots"))
        with contextlib.suppress(ValueError):
            fec_num_roots = int(fec_str) if fec_str.strip() else 2
        if confirm_dialog(stdscr, _("config.wizard.do_not_generate_fec")):
            do_not_generate_fec = True
    elif descriptor == DescriptorType.VBMETA:
        pad_str = input_prompt(stdscr, _("config.wizard.padding_size"))
        with contextlib.suppress(ValueError):
            padding_size = int(pad_str) if pad_str.strip() else 0
        if confirm_dialog(stdscr, _("config.wizard.chain_do_not_use_ab")):
            chains = input_prompt(stdscr, _("config.wizard.chain_do_not_use_ab_list"))
            chain_partitions_do_not_use_ab = tuple(
                c.strip() for c in chains.split(",") if c.strip()
            )
        cmdlines = input_prompt(stdscr, _("config.wizard.kernel_cmdlines"))
        kernel_cmdlines = tuple(c.strip() for c in cmdlines.split(",") if c.strip())
        # Manual props: comma-separated key:value pairs (optional).
        props_str = input_prompt(stdscr, _("config.wizard.props"))
        props = tuple(
            (k.strip(), v.strip())
            for entry in props_str.split(",")
            if ":" in entry
            for k, v in [entry.split(":", 1)]
        )

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
        partition_size=partition_size,
        dynamic_partition_size=dynamic_partition_size,
        block_size=block_size,
        fec_num_roots=fec_num_roots,
        do_not_generate_fec=do_not_generate_fec,
        padding_size=padding_size,
        kernel_cmdlines=kernel_cmdlines,
        chain_partitions_do_not_use_ab=chain_partitions_do_not_use_ab,
        props=props,
    )
