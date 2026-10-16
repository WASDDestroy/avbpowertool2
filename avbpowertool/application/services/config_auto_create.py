"""ConfigAutoCreateUseCase — generate partition configs from images.

This module owns the non-interactive half of the create-config wizard's
auto mode: scanning a directory for ``*.img`` files, inspecting them,
turning each inspection into a :class:`PartitionConfig`, resolving the
chain-partition keys read from vbmeta images, and finalizing the vbmeta
``included_partitions``.  The TUI keeps only its prompts and screens; the
CLI reuses the same use case.
"""

from __future__ import annotations

import contextlib
from dataclasses import replace
from pathlib import Path

from avbpowertool.application.commands import (
    ChainKeyResolution,
    ConfigAutoCreateRequest,
    ConfigAutoCreateResult,
    InspectImagesRequest,
    ResolveChainKeysRequest,
)
from avbpowertool.application.ports import AvbToolPort
from avbpowertool.application.services.inspect_images import InspectImagesUseCase
from avbpowertool.application.services.resolve_chains import ResolveChainKeysUseCase
from avbpowertool.domain.models import (
    ChainDescriptor,
    DescriptorType,
    ImageInspection,
    OperationIssue,
    PartitionConfig,
    SigningAlgorithm,
)
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths

_VALID_HASH_ALGORITHMS = ("sha1", "sha256", "sha512")


class ConfigAutoCreateUseCase:
    """Build a profile's partition configs from the images on disk."""

    def __init__(self, workspace: WorkspacePaths, avb_tool: AvbToolPort) -> None:
        self._ws = workspace
        self._avb = avb_tool

    def execute(self, request: ConfigAutoCreateRequest) -> ConfigAutoCreateResult:
        if not request.image_dir.is_dir():
            return ConfigAutoCreateResult(
                issues=(
                    OperationIssue(
                        "config.auto_dir_not_found",
                        f"Image directory does not exist: {request.image_dir}",
                    ),
                )
            )

        scanned = _scan_images(request.image_dir, request.image_names)
        if not scanned:
            return ConfigAutoCreateResult()

        inspect_result = InspectImagesUseCase(self._ws, self._avb).execute(
            InspectImagesRequest(image_names=scanned)
        )

        # Build (image -> PartitionConfig) keyed by FILE so later images can
        # never overwrite an earlier partition's entry (a vbmeta image embeds
        # descriptors for other partitions and must not clobber their configs).
        by_image: dict[str, PartitionConfig] = {}
        included_by_image: dict[str, tuple[str, ...]] = {}
        chain_descriptors_by_image: dict[str, tuple[ChainDescriptor, ...]] = {}
        skipped_images: list[str] = []
        for img in inspect_result.images:
            key_id = request.key_id or select_key_for_algorithm(
                img.algorithm, list(request.available_keys), request.default_key_id
            )
            config = build_auto_partition(img, request.image_dir, key_id=key_id)
            if config is None:
                skipped_images.append(img.image_name)
                continue
            by_image[config.image] = config
            included_by_image[config.image] = img.included_partitions
            if config.descriptor == DescriptorType.VBMETA and img.chain_descriptors:
                chain_descriptors_by_image[config.image] = img.chain_descriptors

        # Restore chain partitions read from the vbmeta images: resolve each
        # chain descriptor's public-key SHA1 to a key file in the key store.
        chain_issues: tuple[OperationIssue, ...] = ()
        if request.resolve_chains and chain_descriptors_by_image:
            all_chains = tuple(c for descs in chain_descriptors_by_image.values() for c in descs)
            chain_result = ResolveChainKeysUseCase(self._ws, self._avb).execute(
                ResolveChainKeysRequest(profile_id=request.profile_id, chains=all_chains)
            )
            by_image = apply_chain_resolutions(
                by_image, chain_descriptors_by_image, chain_result.resolutions
            )
            chain_issues = chain_result.issues

        partitions = finalize_vbmeta_includes(
            by_image, included_by_image, allow_fallback=request.allow_fallback
        )

        return ConfigAutoCreateResult(
            partitions=tuple(partitions),
            scanned_images=scanned,
            skipped_images=tuple(skipped_images),
            chain_issues=chain_issues,
            issues=inspect_result.issues,
        )


def _scan_images(image_dir: Path, image_names: tuple[str, ...]) -> tuple[str, ...]:
    """Return the sorted ``*.img`` stems to inspect.

    ``image_names`` (when non-empty) restricts the scan to those stems,
    keeping the directory's sorted order.
    """
    scanned = [f.stem for f in sorted(image_dir.iterdir()) if f.suffix == ".img" and f.is_file()]
    if not image_names:
        return tuple(scanned)
    wanted = set(image_names)
    return tuple(name for name in scanned if name in wanted)


def select_key_for_algorithm(algorithm: str | None, available: list[str], default: str) -> str:
    """Select an RSA key matching the inspected image algorithm size."""
    if algorithm:
        upper = algorithm.upper()
        size = "2048" if "2048" in upper else "4096" if "4096" in upper else ""
        if size:
            for key_id in available:
                if size in key_id:
                    return key_id
    return default


def build_auto_partition(
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


def finalize_vbmeta_includes(
    by_image: dict[str, PartitionConfig],
    included_by_image: dict[str, tuple[str, ...]],
    *,
    allow_fallback: bool = True,
) -> list[PartitionConfig]:
    """Fill vbmeta ``included_partitions`` and return the final config list.

    Prefers the descriptors really embedded in the vbmeta image (limited
    to partitions present in the scan).  With ``allow_fallback`` (the
    wizard's historical behaviour) an image whose embedded descriptors
    were all pruned falls back to every other scanned non-vbmeta
    partition; without it the filtered — possibly empty — tuple is kept.
    """
    scanned_names = {c.partition_name for c in by_image.values()}
    for image_name, config in by_image.items():
        if config.descriptor != DescriptorType.VBMETA:
            continue
        real = included_by_image.get(image_name, ())
        included = tuple(n for n in real if n in scanned_names)
        if not included and allow_fallback:
            included = tuple(
                c.partition_name
                for c in by_image.values()
                if c.image != image_name and c.descriptor != DescriptorType.VBMETA
            )
        by_image[image_name] = replace(config, included_partitions=included)
    return list(by_image.values())


def apply_chain_resolutions(
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
