"""Create Config wizard — guided profile creation with partitions."""

from __future__ import annotations

import contextlib
import curses
from dataclasses import replace
from pathlib import Path

from avbpowertool.application.commands import (
    ChainKeyResolution,
    ConfigCreateRequest,
)
from avbpowertool.application.ports import AvbToolPort
from avbpowertool.application.services.manage_configs import ConfigCreateUseCase
from avbpowertool.domain.models import (
    ChainDescriptor,
    DescriptorType,
    ImageInspection,
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

    from avbpowertool.application.commands import InspectImagesRequest
    from avbpowertool.application.services.inspect_images import InspectImagesUseCase

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

    # Build (image -> PartitionConfig) keyed by FILE so later images can
    # never overwrite an earlier partition's entry (a vbmeta image embeds
    # descriptors for other partitions and must not clobber their configs).
    by_image: dict[str, PartitionConfig] = {}
    included_by_image: dict[str, tuple[str, ...]] = {}
    chain_descriptors_by_image: dict[str, tuple[ChainDescriptor, ...]] = {}
    chain_issues: list[str] = []
    size_notes: list[str] = []
    meta_lines: list[str] = []
    for img in result.images:
        key_id = _key_for_algorithm(img.algorithm, available_keys, default_key_id)
        config = _build_auto_partition(img, image_dir, key_id=key_id)
        if config is None:
            continue
        by_image[config.image] = config
        included_by_image[config.image] = img.included_partitions
        if config.descriptor == DescriptorType.VBMETA and img.chain_descriptors:
            chain_descriptors_by_image[config.image] = img.chain_descriptors

        if config.partition_size > 0:
            size_notes.append(f"{config.partition_name}: {config.partition_size}")

        # Summary of the metadata read back from the image.
        meta = (
            f"{config.partition_name}: {config.descriptor.value} "
            f"alg={config.algorithm.value} rbi={config.rollback_index} "
            f"rbl={config.rollback_index_location} flags={config.flags} "
            f"props={len(config.props)} hash={config.hash_algorithm}"
        )
        meta_lines.append(meta)

    # Restore chain partitions read from the vbmeta images: resolve each
    # chain descriptor's public-key SHA1 to a key file in the key store.
    if chain_descriptors_by_image:
        from avbpowertool.application.commands import ResolveChainKeysRequest
        from avbpowertool.application.services.resolve_chains import (
            ResolveChainKeysUseCase,
        )

        all_chains = tuple(c for descs in chain_descriptors_by_image.values() for c in descs)
        chain_result = ResolveChainKeysUseCase(ws, avb).execute(
            ResolveChainKeysRequest(profile_id=profile_id, chains=all_chains)
        )
        by_image = _apply_chain_resolutions(
            by_image, chain_descriptors_by_image, chain_result.resolutions
        )
        chain_issues = [f"  [{iss.error_code}] {iss.message}" for iss in chain_result.issues]

    partitions = _finalize_vbmeta_includes(by_image, included_by_image)

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
    if chain_issues:
        result_lines.append("")
        result_lines.append(_("config.wizard.auto_chain_note"))
        result_lines.extend(chain_issues)

    message_screen(stdscr, _("config.wizard.auto_result_title"), result_lines)
    return partitions


_VALID_HASH_ALGORITHMS = ("sha1", "sha256", "sha512")


def _key_for_algorithm(algorithm: str | None, available: list[str], default: str) -> str:
    """Select an RSA key matching the inspected image algorithm size."""
    if algorithm:
        upper = algorithm.upper()
        size = "2048" if "2048" in upper else "4096" if "4096" in upper else ""
        if size:
            for key_id in available:
                if size in key_id:
                    return key_id
    return default


def _build_auto_partition(
    img: ImageInspection,
    image_dir: Path,
    key_id: str = "default",
) -> PartitionConfig | None:
    """Build a PartitionConfig from an ImageInspection (auto mode).

    Reads back the image's footer metadata — rollback index, rollback
    index location, salt, flags (incl. flag-bit shortcuts), props and
    hash algorithm — with safe defaults when the image has none.
    """
    if img.descriptor is None:
        return None

    descriptor = img.descriptor

    # Signing algorithm (vbmeta header ``Algorithm`` line, e.g. NONE or
    # SHA256_RSA4096); falls back to the default when unparseable.
    algorithm = SigningAlgorithm.SHA256_RSA4096
    if img.algorithm:
        with contextlib.suppress(ValueError):
            algorithm = SigningAlgorithm.from_str(img.algorithm)

    # Flags integer plus the two flag-bit shortcuts (VBMeta image flags:
    # 1 = HASHTREE_DISABLED, 2 = VERIFICATION_DISABLED).
    flags = 0
    if img.flags:
        with contextlib.suppress(ValueError):
            flags = int(img.flags)

    rollback_index = int(img.rollback_index) if img.rollback_index else 0
    rollback_index_location = 0
    if img.rollback_index_location:
        with contextlib.suppress(ValueError):
            rollback_index_location = int(img.rollback_index_location)

    hash_algorithm = "sha256"
    if descriptor != DescriptorType.VBMETA:
        candidate = (img.hash_algorithm or "sha256").strip().lower()
        if candidate in _VALID_HASH_ALGORITHMS:
            hash_algorithm = candidate

    # Hash footers require partition_size (or dynamic_partition_size):
    # default to the image file size rounded up to the 4096 block size,
    # which is the smallest valid value avbtool accepts.
    partition_size = 0
    if descriptor == DescriptorType.HASH:
        image_file = image_dir / f"{img.image_name}.img"
        with contextlib.suppress(OSError):
            if image_file.is_file():
                partition_size = (int(image_file.stat().st_size) + 4095) // 4096 * 4096

    return PartitionConfig(
        image=f"{img.image_name}.img",
        descriptor=descriptor,
        algorithm=algorithm,
        key_id=key_id,
        partition_name=img.partition_name or img.image_name,
        rollback_index=rollback_index,
        rollback_index_location=rollback_index_location,
        salt=img.salt or "",
        flags=flags,
        set_hashtree_disabled_flag=bool(flags & 1),
        set_verification_disabled_flag=bool(flags & 2),
        props=img.props if img.props else (),
        hash_algorithm=hash_algorithm,
        partition_size=partition_size,
    )


def _finalize_vbmeta_includes(
    by_image: dict[str, PartitionConfig],
    included_by_image: dict[str, tuple[str, ...]],
) -> list[PartitionConfig]:
    """Fill vbmeta ``included_partitions`` and return the final config list.

    Prefers the descriptors really embedded in the vbmeta image (limited
    to partitions present in the scan); falls back to every other scanned
    non-vbmeta partition when the image carries no descriptors.
    """
    scanned_names = {c.partition_name for c in by_image.values()}
    for image_name, config in by_image.items():
        if config.descriptor != DescriptorType.VBMETA:
            continue
        real = included_by_image.get(image_name, ())
        included = tuple(n for n in real if n in scanned_names)
        if not included:
            included = tuple(
                c.partition_name
                for c in by_image.values()
                if c.image != image_name and c.descriptor != DescriptorType.VBMETA
            )
        by_image[image_name] = replace(config, included_partitions=included)
    return list(by_image.values())


def _apply_chain_resolutions(
    by_image: dict[str, PartitionConfig],
    chain_descriptors: dict[str, tuple[ChainDescriptor, ...]],
    resolutions: tuple[ChainKeyResolution, ...],
) -> dict[str, PartitionConfig]:
    """Write resolved ``PART:SLOT:KEY_FILE`` entries into vbmeta configs.

    ``resolutions`` is parallel to the flattened chain descriptors (in
    the insertion order of ``chain_descriptors``); entries that were not
    resolved (empty) are skipped so the config stays signable.
    """
    idx = 0
    for image_name, descriptors in chain_descriptors.items():
        entries: list[str] = []
        for _descriptor in descriptors:
            if idx < len(resolutions) and resolutions[idx].entry:
                entries.append(resolutions[idx].entry)
            idx += 1
        by_image[image_name] = replace(by_image[image_name], chain_partitions=tuple(entries))
    return by_image


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
