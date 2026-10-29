"""Sign Images view — select images and sign them."""

from __future__ import annotations

import curses
from dataclasses import dataclass
from pathlib import Path

from avbpowertool.application.commands import SignImagesRequest
from avbpowertool.application.ports import AvbToolPort
from avbpowertool.application.services.sign_images import SignImagesUseCase
from avbpowertool.domain.models import AvbProfile, DescriptorType
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.presentation.i18n import _
from avbpowertool.presentation.tui.widgets import (
    SelectorWidget,
    confirm_dialog,
    message_screen,
)


@dataclass(frozen=True)
class VbmetaGenerationTarget:
    """A vbmeta partition whose image does not exist yet.

    ``missing_inputs`` lists the image files the generated vbmeta would
    need but that are absent from the workspace.  An empty tuple means the
    target is ready to be generated.
    """

    partition: str
    image: str
    missing_inputs: tuple[str, ...]


def show(stdscr: object, ws: WorkspacePaths, avb: AvbToolPort) -> None:
    """Sign images view."""
    stdscr_c: curses.window = stdscr  # type: ignore[assignment]

    active_id = _get_active_profile(ws)
    profile = _load_profile(ws, active_id)

    if not ws.images.exists():
        message_screen(stdscr_c, _("sign.title"), [_("sign.no_images_dir")])
        return

    images = _existing_image_names(ws)
    targets = _vbmeta_generation_targets(profile, ws.images)
    blocked = [target for target in targets if target.missing_inputs]
    ready = [target for target in targets if not target.missing_inputs]

    if blocked:
        _show_missing_inputs(stdscr_c, blocked)

    # Existing images stay selectable as before; a missing vbmeta image is
    # offered as a generation target only when every image it needs is
    # already present (otherwise the prompt above explains what is missing).
    entries: list[tuple[str, str]] = [(name, name) for name in images]
    entries.extend(
        (target.partition, _("sign.generate_option", image=target.image)) for target in ready
    )

    if not entries:
        if not blocked:
            message_screen(stdscr_c, _("sign.title"), [_("sign.no_images")])
        return

    # Confirm
    if not confirm_dialog(stdscr_c, _("sign.confirm")):
        return

    # Multi-select
    sel = SelectorWidget(
        _("sign.select_title"), [label for _name, label in entries], multi_select=True
    )
    chosen = sel.run(stdscr_c)
    if not chosen:
        return

    selected_names = _expand_with_included_partitions(profile, [entries[i][0] for i in chosen])

    # If a vbmeta partition is being generated, ask whether the config's
    # props should be attached to the new vbmeta image (default: No —
    # props read back from images are usually duplicates of build info).
    include_vbmeta_props = False
    if _has_vbmeta_partition(profile, selected_names):
        props_sel = SelectorWidget(
            _("sign.vbmeta.props_prompt"), [_("widget.choice.no"), _("widget.choice.yes")]
        )
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
        lines.append(_("sign.summary", success=result.success_count, failed=result.fail_count))
    else:
        lines.append(_("sign.dry_run_done"))
        lines.append(_("sign.steps_planned", count=len(result.plan.steps)))

    for step in result.plan.steps:
        lines.append(f"  [{step.order}] {step.operation} {step.partition_name}")

    for iss in result.issues:
        lines.append(f"  [{iss.error_code}] {iss.message}")

    message_screen(stdscr_c, _("sign.results_title"), lines)


def _get_active_profile(ws: WorkspacePaths) -> str:
    from avbpowertool.infrastructure.persistence.profile_repository import ProfileRepository

    repo = ProfileRepository(ws)
    return repo.get_active_profile_id() or "current"


def _load_profile(ws: WorkspacePaths, profile_id: str) -> AvbProfile | None:
    """Load the active profile, or None when it cannot be read."""
    from avbpowertool.infrastructure.persistence.profile_repository import ProfileRepository

    try:
        return ProfileRepository(ws).load(profile_id)
    except Exception:
        return None


def _existing_image_names(ws: WorkspacePaths) -> list[str]:
    """Return the sorted stems of the ``*.img`` files in ``Images/``."""
    return [f.stem for f in sorted(ws.images.iterdir()) if f.suffix == ".img" and f.is_file()]


def _image_exists(image_dir: Path, filename: str) -> bool:
    """True when ``filename`` (optionally without ``.img``) exists."""
    if (image_dir / filename).is_file():
        return True
    if not filename.endswith(".img"):
        return (image_dir / f"{filename}.img").is_file()
    return False


def _vbmeta_generation_targets(
    profile: AvbProfile | None, image_dir: Path
) -> list[VbmetaGenerationTarget]:
    """Describe every profile vbmeta whose image file is missing.

    Targets are returned for both ready and blocked vbmeta partitions;
    callers split them by ``missing_inputs``.  Without a readable profile
    there is nothing to generate, so the list stays empty.
    """
    if profile is None:
        return []

    targets: list[VbmetaGenerationTarget] = []
    for name, config in sorted(profile.partitions.items()):
        if config.descriptor != DescriptorType.VBMETA:
            continue
        if _image_exists(image_dir, config.image):
            continue
        targets.append(
            VbmetaGenerationTarget(
                partition=name,
                image=config.image,
                missing_inputs=_missing_inputs(profile, name, image_dir),
            )
        )
    return targets


def _missing_inputs(profile: AvbProfile, target: str, image_dir: Path) -> tuple[str, ...]:
    """Return image files needed to generate vbmeta ``target`` but absent.

    Only image inputs are considered: keys and chain-partition public key
    files are checked by the signing plan itself.  A missing nested vbmeta
    is treated as generatable in the same batch, so its own inputs are
    checked recursively.
    """
    missing: set[str] = set()
    image_to_partition = {config.image: name for name, config in profile.partitions.items()}

    def walk(name: str, seen: frozenset[str]) -> None:
        config = profile.partitions.get(name)
        if config is None:
            missing.add(name)
            return

        for included in config.included_partitions:
            included_config = profile.partitions.get(included)
            if included_config is None:
                missing.add(included)
                continue
            if _image_exists(image_dir, included_config.image):
                continue
            if included_config.descriptor == DescriptorType.VBMETA and included not in seen:
                walk(included, seen | {included})
            else:
                # A regular image, or a cycle that can never be produced.
                missing.add(included_config.image)

        for extra in config.include_descriptors_from_image:
            if _image_exists(image_dir, extra):
                continue
            extra_partition = image_to_partition.get(extra)
            if extra_partition is None and not extra.endswith(".img"):
                extra_partition = image_to_partition.get(f"{extra}.img")
            if extra_partition is not None and extra_partition not in seen:
                extra_config = profile.partitions[extra_partition]
                if extra_config.descriptor == DescriptorType.VBMETA:
                    walk(extra_partition, seen | {extra_partition})
                    continue
            missing.add(extra)

    walk(target, frozenset({target}))
    return tuple(sorted(missing))


def _expand_with_included_partitions(
    profile: AvbProfile | None, selected_names: list[str]
) -> list[str]:
    """Add the partitions a selected vbmeta embeds descriptors for.

    ``make_vbmeta_image`` consumes the staged copies of ``included_partitions``,
    so those partitions must be part of the same signing run; otherwise the
    generated vbmeta would reference files that were never produced.
    """
    expanded = list(dict.fromkeys(selected_names))
    if profile is None:
        return expanded

    seen = set(expanded)
    queue = list(expanded)
    while queue:
        name = queue.pop(0)
        config = profile.partitions.get(name)
        if config is None or config.descriptor != DescriptorType.VBMETA:
            continue
        for included in config.included_partitions:
            if included in profile.partitions and included not in seen:
                seen.add(included)
                expanded.append(included)
                queue.append(included)
    return expanded


def _show_missing_inputs(stdscr: curses.window, targets: list[VbmetaGenerationTarget]) -> None:
    """Tell the user which images block the missing vbmeta generation."""
    lines: list[str] = [_("sign.vbmeta.missing_intro"), ""]
    for target in targets:
        lines.append(
            _(
                "sign.vbmeta.missing_line",
                image=target.image,
                missing=", ".join(target.missing_inputs),
            )
        )
    lines.extend(["", _("sign.vbmeta.missing_hint")])
    message_screen(stdscr, _("sign.vbmeta.missing_title"), lines)


def _has_vbmeta_partition(profile: AvbProfile | None, selected_names: list[str]) -> bool:
    """True if any selected name maps to a vbmeta partition in the profile."""
    if profile is None:
        return False

    selected = set(selected_names)
    for name in selected:
        config = profile.partitions.get(name)
        if config is not None and config.descriptor == DescriptorType.VBMETA:
            return True
    vbmeta_images = {
        config.image
        for config in profile.partitions.values()
        if config.descriptor == DescriptorType.VBMETA
    }
    return any(name in vbmeta_images or f"{name}.img" in vbmeta_images for name in selected)
