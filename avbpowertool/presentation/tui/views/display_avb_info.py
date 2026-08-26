"""Display AVB Info view — show current config information."""

from __future__ import annotations

import curses

from avbpowertool.application.commands import ConfigShowRequest
from avbpowertool.application.ports import AvbToolPort
from avbpowertool.application.services.manage_configs import ConfigShowUseCase
from avbpowertool.domain.models import DescriptorType, PartitionConfig
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
            lines.extend(partition_config_lines(p))
            lines.append("")

    for iss in result.issues:
        lines.append(f"  [{iss.error_code}] {iss.message}")

    message_screen(stdscr_c, "Current Config Info", lines)


def partition_config_lines(pc: PartitionConfig) -> list[str]:
    """Render one partition config into display lines.

    Mirrors exactly what the profile codec persists: the core fields
    (image, descriptor, algorithm, key id, partition name) are always
    shown; every other field only when it carries a non-default value,
    so the TUI faithfully reflects the on-disk config file.
    """
    lines: list[str] = [f"[{pc.partition_name}]"]
    lines.append(f"  Image: {pc.image}")
    lines.append(f"  Descriptor: {pc.descriptor.value}")
    lines.append(f"  Algorithm: {pc.algorithm.value}")
    lines.append(f"  Key ID: {pc.key_id}")

    # partition size
    if pc.partition_size > 0:
        lines.append(f"  Partition Size: {pc.partition_size}")
    if pc.dynamic_partition_size:
        lines.append("  Dynamic Partition Size: true")
    # rollback / digest
    if pc.rollback_index != 0:
        lines.append(f"  Rollback Index: {pc.rollback_index}")
    if pc.rollback_index_location != 0:
        lines.append(f"  Rollback Index Location: {pc.rollback_index_location}")
    if pc.salt:
        lines.append(f"  Salt: {pc.salt}")
    if pc.hash_algorithm != "sha256":
        lines.append(f"  Hash Algorithm: {pc.hash_algorithm}")
    # descriptor properties
    if pc.flags:
        lines.append(f"  Flags: {pc.flags}")
    if pc.props:
        lines.append("  Props:")
        for key, value in pc.props:
            lines.append(f"    {key} = {value}")
    if pc.prop_from_file:
        lines.append("  Prop From File:")
        for key, value in pc.prop_from_file:
            lines.append(f"    {key} = {value}")
    if pc.set_hashtree_disabled_flag:
        lines.append("  Set Hashtree Disabled: true")
    if pc.set_verification_disabled_flag:
        lines.append("  Set Verification Disabled: true")
    # hashtree-specific
    if pc.descriptor == DescriptorType.HASHTREE:
        if pc.block_size != 4096:
            lines.append(f"  Block Size: {pc.block_size}")
        if pc.do_not_generate_fec:
            lines.append("  Do Not Generate FEC: true")
        if pc.fec_num_roots != 2:
            lines.append(f"  FEC Num Roots: {pc.fec_num_roots}")
        if pc.no_hashtree:
            lines.append("  No Hashtree: true")
        if pc.check_at_most_once:
            lines.append("  Check At Most Once: true")
        if pc.setup_as_rootfs_from_kernel:
            lines.append("  Setup As Rootfs From Kernel: true")
    # vbmeta / footer common
    if pc.included_partitions:
        lines.append(f"  Included Partitions: {', '.join(pc.included_partitions)}")
    if pc.include_descriptors_from_image:
        lines.append(
            f"  Include Descriptors From Image: {', '.join(pc.include_descriptors_from_image)}"
        )
    if pc.chain_partitions:
        lines.append(f"  Chain Partitions: {', '.join(pc.chain_partitions)}")
    if pc.chain_partitions_do_not_use_ab:
        lines.append(f"  Chain Partitions (no AB): {', '.join(pc.chain_partitions_do_not_use_ab)}")
    if pc.kernel_cmdlines:
        lines.append(f"  Kernel Cmdlines: {', '.join(pc.kernel_cmdlines)}")
    if pc.setup_rootfs_from_kernel:
        lines.append(f"  Setup Rootfs From Kernel: {pc.setup_rootfs_from_kernel}")
    if pc.padding_size:
        lines.append(f"  Padding Size: {pc.padding_size}")
    if pc.output_vbmeta_image:
        lines.append(f"  Output Vbmeta Image: {pc.output_vbmeta_image}")
    # behavior switches
    if pc.calc_max_image_size:
        lines.append("  Calc Max Image Size: true")
    if pc.do_not_append_vbmeta_image:
        lines.append("  Do Not Append Vbmeta Image: true")
    if pc.print_required_libavb_version:
        lines.append("  Print Required Libavb Version: true")
    if pc.use_persistent_digest:
        lines.append("  Use Persistent Digest: true")
    if pc.do_not_use_ab:
        lines.append("  Do Not Use AB: true")
    # signing helper
    if pc.signing_helper:
        lines.append(f"  Signing Helper: {pc.signing_helper}")
    if pc.signing_helper_with_files:
        lines.append(f"  Signing Helper With Files: {pc.signing_helper_with_files}")
    if pc.public_key_metadata:
        lines.append(f"  Public Key Metadata: {pc.public_key_metadata}")
    if pc.append_to_release_string:
        lines.append(f"  Append To Release String: {pc.append_to_release_string}")

    return lines
