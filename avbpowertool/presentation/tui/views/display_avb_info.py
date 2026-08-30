"""Display AVB Info view — show current config information."""

from __future__ import annotations

import curses

from avbpowertool.application.commands import ConfigShowRequest
from avbpowertool.application.ports import AvbToolPort
from avbpowertool.application.services.manage_configs import ConfigShowUseCase
from avbpowertool.domain.models import DescriptorType, PartitionConfig
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.presentation.i18n import _
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
    lines.append(_("config.field.profile", value=result.config_name))
    lines.append("")

    if not result.partitions:
        lines.append(_("config.no_partitions"))
    else:
        for p in result.partitions:
            lines.extend(partition_config_lines(p))
            lines.append("")

    for iss in result.issues:
        lines.append(f"  [{iss.error_code}] {iss.message}")

    message_screen(stdscr_c, _("config.show_title"), lines)


def partition_config_lines(pc: PartitionConfig) -> list[str]:
    """Render one partition config into display lines.

    Mirrors exactly what the profile codec persists: the core fields
    (image, descriptor, algorithm, key id, partition name) are always
    shown; every other field only when it carries a non-default value,
    so the TUI faithfully reflects the on-disk config file.
    """
    lines: list[str] = [f"[{pc.partition_name}]"]
    lines.append(_("config.field.image", value=pc.image))
    lines.append(_("config.field.descriptor", value=pc.descriptor.value))
    lines.append(_("config.field.algorithm", value=pc.algorithm.value))
    lines.append(_("config.field.key_id", value=pc.key_id))

    # partition size
    if pc.partition_size > 0:
        lines.append(_("config.field.partition_size", value=pc.partition_size))
    if pc.dynamic_partition_size:
        lines.append(_("config.field.dynamic_partition_size"))
    # rollback / digest
    if pc.rollback_index != 0:
        lines.append(_("config.field.rollback_index", value=pc.rollback_index))
    if pc.rollback_index_location != 0:
        lines.append(_("config.field.rollback_index_location", value=pc.rollback_index_location))
    if pc.salt:
        lines.append(_("config.field.salt", value=pc.salt))
    if pc.hash_algorithm != "sha256":
        lines.append(_("config.field.hash_algorithm", value=pc.hash_algorithm))
    # descriptor properties
    if pc.flags:
        lines.append(_("config.field.flags", value=pc.flags))
    if pc.props:
        lines.append(_("config.field.props_header"))
        for key, value in pc.props:
            lines.append(f"    {key} = {value}")
    if pc.prop_from_file:
        lines.append(_("config.field.prop_from_file_header"))
        for key, value in pc.prop_from_file:
            lines.append(f"    {key} = {value}")
    if pc.set_hashtree_disabled_flag:
        lines.append(_("config.field.set_hashtree_disabled"))
    if pc.set_verification_disabled_flag:
        lines.append(_("config.field.set_verification_disabled"))
    # hashtree-specific
    if pc.descriptor == DescriptorType.HASHTREE:
        if pc.block_size != 4096:
            lines.append(_("config.field.block_size", value=pc.block_size))
        if pc.do_not_generate_fec:
            lines.append(_("config.field.do_not_generate_fec"))
        if pc.fec_num_roots != 2:
            lines.append(_("config.field.fec_num_roots", value=pc.fec_num_roots))
        if pc.no_hashtree:
            lines.append(_("config.field.no_hashtree"))
        if pc.check_at_most_once:
            lines.append(_("config.field.check_at_most_once"))
        if pc.setup_as_rootfs_from_kernel:
            lines.append(_("config.field.setup_as_rootfs_from_kernel"))
    # vbmeta / footer common
    if pc.included_partitions:
        lines.append(_("config.field.included_partitions", value=", ".join(pc.included_partitions)))
    if pc.include_descriptors_from_image:
        lines.append(
            _(
                "config.field.include_descriptors_from_image",
                value=", ".join(pc.include_descriptors_from_image),
            )
        )
    if pc.chain_partitions:
        lines.append(_("config.field.chain_partitions", value=", ".join(pc.chain_partitions)))
    if pc.chain_partitions_do_not_use_ab:
        lines.append(
            _(
                "config.field.chain_partitions_no_ab",
                value=", ".join(pc.chain_partitions_do_not_use_ab),
            )
        )
    if pc.kernel_cmdlines:
        lines.append(_("config.field.kernel_cmdlines", value=", ".join(pc.kernel_cmdlines)))
    if pc.setup_rootfs_from_kernel:
        lines.append(_("config.field.setup_rootfs_from_kernel", value=pc.setup_rootfs_from_kernel))
    if pc.padding_size:
        lines.append(_("config.field.padding_size", value=pc.padding_size))
    if pc.output_vbmeta_image:
        lines.append(_("config.field.output_vbmeta_image", value=pc.output_vbmeta_image))
    # behavior switches
    if pc.calc_max_image_size:
        lines.append(_("config.field.calc_max_image_size"))
    if pc.do_not_append_vbmeta_image:
        lines.append(_("config.field.do_not_append_vbmeta_image"))
    if pc.print_required_libavb_version:
        lines.append(_("config.field.print_required_libavb_version"))
    if pc.use_persistent_digest:
        lines.append(_("config.field.use_persistent_digest"))
    if pc.do_not_use_ab:
        lines.append(_("config.field.do_not_use_ab"))
    # signing helper
    if pc.signing_helper:
        lines.append(_("config.field.signing_helper", value=pc.signing_helper))
    if pc.signing_helper_with_files:
        lines.append(
            _("config.field.signing_helper_with_files", value=pc.signing_helper_with_files)
        )
    if pc.public_key_metadata:
        lines.append(_("config.field.public_key_metadata", value=pc.public_key_metadata))
    if pc.append_to_release_string:
        lines.append(_("config.field.append_to_release_string", value=pc.append_to_release_string))

    return lines
