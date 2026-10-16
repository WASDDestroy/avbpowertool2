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
    ConfigCreateFromImagesRequest,
    ConfigCreateFromImagesResult,
    ConfigCreateRequest,
    ConfigValidateRequest,
    InspectImagesRequest,
    ResolveChainKeysRequest,
)
from avbpowertool.application.ports import AvbToolPort
from avbpowertool.application.services.inspect_images import InspectImagesUseCase
from avbpowertool.application.services.manage_configs import (
    ConfigCreateUseCase,
    ConfigValidateUseCase,
    sanitize_profile_id,
)
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
from avbpowertool.infrastructure.persistence.key_repository import KeyRepository

_VALID_HASH_ALGORITHMS = ("sha1", "sha256", "sha512")

#: issue code reported for an image that carries no AVB structure at all
NO_VBMETA_STRUCTURE = "image.no_vbmeta_structure"


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


class ConfigCreateFromImagesUseCase:
    """Create a profile from the AVB metadata of the images on disk.

    This is the scripted counterpart of the create wizard's auto mode: it
    scans a directory, builds the partition configs, writes the profile and
    then reports what is still missing (keys).  The execution order is
    fixed and every early return leaves the workspace untouched:

    1. the requested id must already be a valid profile id;
    2. an existing ``profiles/<id>/`` is a conflict unless ``overwrite``;
    3. every explicitly requested image must exist;
    4. the images are scanned and inspected;
    5. an image without AVB structure is fatal unless ``skip_non_avb``;
    6. an empty partition set is ``config.no_partitions``;
    7. the profile is written (an overwrite keeps the existing ``keys/``);
    8. the new profile is validated for information (``missing_keys``).
    """

    def __init__(self, workspace: WorkspacePaths, avb_tool: AvbToolPort) -> None:
        self._ws = workspace
        self._avb = avb_tool

    def execute(self, request: ConfigCreateFromImagesRequest) -> ConfigCreateFromImagesResult:
        # 1. The requested id must be usable as a directory name as-is;
        # silently rewriting it would create a profile under another id.
        profile_id = sanitize_profile_id(request.profile_id)
        if profile_id != request.profile_id:
            return ConfigCreateFromImagesResult(
                profile_id=request.profile_id,
                issues=(
                    OperationIssue(
                        "config.invalid_profile_id",
                        f"Invalid profile id: {request.profile_id!r} "
                        "(use letters, digits, '_', '-', '.' only)",
                    ),
                ),
            )

        # 2. Conflict check: an existing directory is reused on overwrite
        # (its keys/ content is kept, the partitions are replaced).
        if self._ws.resolve_profile_dir(profile_id).exists() and not request.overwrite:
            return ConfigCreateFromImagesResult(
                profile_id=profile_id,
                issues=(
                    OperationIssue(
                        "config.profile_exists",
                        f"Profile already exists: {profile_id}",
                    ),
                ),
            )

        image_dir = request.image_dir if request.image_dir is not None else self._ws.images

        # 3. Every explicitly requested image must exist; a wrapper script
        # computes the image set, so a typo must fail loudly and early.
        missing = [
            name for name in request.image_names if not (image_dir / f"{name}.img").is_file()
        ]
        if missing:
            return ConfigCreateFromImagesResult(
                profile_id=profile_id,
                issues=tuple(
                    OperationIssue(
                        "image.not_found",
                        f"Image file does not exist: {image_dir / f'{name}.img'}",
                    )
                    for name in missing
                ),
            )

        # 4. Scan, inspect and turn every image into a partition config.
        # The scan directory also drives image resolution: --from-images
        # points the inspection at the requested directory instead of the
        # workspace default.
        available_keys, default_key_id = self._key_candidates(profile_id)
        scan_ws = self._ws if image_dir == self._ws.images else replace(self._ws, images=image_dir)
        auto = ConfigAutoCreateUseCase(scan_ws, self._avb).execute(
            ConfigAutoCreateRequest(
                image_dir=image_dir,
                image_names=request.image_names,
                key_id=request.key_id,
                available_keys=available_keys,
                default_key_id=default_key_id,
                profile_id=profile_id,
                resolve_chains=request.resolve_chains,
                allow_fallback=request.allow_fallback,
            )
        )

        issues: list[OperationIssue] = [
            issue
            for issue in auto.issues
            if not (request.skip_non_avb and issue.error_code == NO_VBMETA_STRUCTURE)
        ]
        skipped_images = auto.skipped_images

        # 5. An image without AVB structure is a fatal error by default:
        # silently dropping its partitions is the one failure mode scripts
        # must never miss.
        if any(issue.error_code == NO_VBMETA_STRUCTURE for issue in issues):
            return ConfigCreateFromImagesResult(
                profile_id=profile_id,
                scanned_images=auto.scanned_images,
                skipped_images=skipped_images,
                issues=tuple(issues),
                chain_issues=auto.chain_issues,
            )

        # 6. Nothing usable was scanned: never create an empty profile here
        # (that is what the explicit --allow-empty path is for).
        if not auto.partitions:
            issues.append(
                OperationIssue(
                    "config.no_partitions",
                    "No partitions could be generated from the scanned images",
                )
            )
            return ConfigCreateFromImagesResult(
                profile_id=profile_id,
                scanned_images=auto.scanned_images,
                skipped_images=skipped_images,
                issues=tuple(issues),
                chain_issues=auto.chain_issues,
            )

        # 7. Write the profile.  Chain-resolution problems do not block
        # creation (the chains can be hardcoded later), so they are **not**
        # merged into ``issues``: ``chain.*`` maps to exit code 1 and would
        # turn an informational note into a failure.  They travel in their
        # own ``chain_issues`` field instead and stay fully visible in the
        # JSON and text output.
        create_result = ConfigCreateUseCase(self._ws).execute(
            ConfigCreateRequest(
                profile_id=profile_id,
                profile_name=request.profile_name or profile_id,
                partitions=auto.partitions,
                activate=request.activate,
                allow_empty=False,
                overwrite=request.overwrite,
            )
        )
        # A partition whose key is not in the store yet does not fail the
        # creation either: ``missing_keys`` below reports it, exactly as
        # ``allow_empty`` keeps ``config.no_partitions`` out of the result.
        # (Without this filter a keyless store would surface the domain
        # validator's ``config.key_missing`` and flip the exit code to 1.)
        issues.extend(
            issue for issue in create_result.issues if issue.error_code != "config.key_missing"
        )

        chain_count = sum(len(partition.chain_partitions) for partition in auto.partitions)

        # 8. Informational: the keys the new profile still needs.  Missing
        # keys never fail the command — they can be added afterwards.
        missing_keys: tuple[str, ...] = ()
        if create_result.created:
            validation = ConfigValidateUseCase(self._ws).execute(
                ConfigValidateRequest(profile_id=profile_id)
            )
            missing_keys = validation.missing_keys

        return ConfigCreateFromImagesResult(
            profile_id=profile_id,
            created=create_result.created,
            partition_count=len(auto.partitions) if create_result.created else 0,
            chain_count=chain_count if create_result.created else 0,
            scanned_images=auto.scanned_images,
            skipped_images=skipped_images,
            missing_keys=missing_keys,
            issues=tuple(issues),
            chain_issues=auto.chain_issues,
        )

    def _key_candidates(self, profile_id: str) -> tuple[tuple[str, ...], str]:
        """Return ``(available key ids, default key id)`` for the profile.

        The key store is read as-is: a brand-new profile has none, while an
        overwrite reuses the keys already sitting next to the old profile.

        The default is only ever a key that really exists in the manifest:
        with exactly one candidate it is that key, otherwise it is empty.
        Several keys give no principled way to pick one, and inventing an
        id (the historical ``"default"``) wrote a key_id no store holds.
        An empty default is harmless: it is legal for unsigned partitions,
        and signed ones still get their key from the size match in
        :func:`select_key_for_algorithm`.
        """
        manifest = KeyRepository(self._ws.resolve_key_dir(profile_id)).load_manifest()
        keys = tuple(manifest)
        return keys, keys[0] if len(keys) == 1 else ""


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
