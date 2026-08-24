"""InspectImagesUseCase — read AVB metadata from image files."""

from __future__ import annotations

import logging
from pathlib import Path

from avbpowertool.application.commands import (
    InspectImagesRequest,
    InspectImagesResult,
)
from avbpowertool.application.ports import AvbToolPort, AvbToolResult
from avbpowertool.domain.models import (
    DescriptorType,
    ImageInspection,
    OperationIssue,
)
from avbpowertool.infrastructure.avbtool.output_parser import parse_info_image
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths

logger = logging.getLogger(__name__)


class InspectImagesUseCase:
    """Read AVB footer metadata for one or more images."""

    def __init__(self, workspace: WorkspacePaths, avb_tool: AvbToolPort) -> None:
        self._ws = workspace
        self._avb = avb_tool

    def execute(self, request: InspectImagesRequest) -> InspectImagesResult:
        images: list[ImageInspection] = []
        issues: list[OperationIssue] = []

        for name in request.image_names:
            image_path = self._resolve_image(name, request.profile_id)
            if image_path is None:
                issues.append(
                    OperationIssue(
                        "image.not_found",
                        f"Image file does not exist: {name}",
                    )
                )
                continue

            result = self._avb.inspect_image(image_path)
            inspection = self._process_result(name, str(image_path), result, issues)
            if inspection is not None:
                images.append(inspection)

        return InspectImagesResult(images=tuple(images), issues=tuple(issues))

    def _resolve_image(self, name: str, _profile_id: str) -> Path | None:
        """Resolve image path. Returns None if not found."""
        try:
            path = self._ws.resolve_image_path(name)
            if path.exists():
                return path
        except Exception:
            pass
        return None

    def _process_result(
        self,
        name: str,
        image_path: str,
        result: AvbToolResult,
        issues: list[OperationIssue],
    ) -> ImageInspection | None:
        """Process avbtool result and build ImageInspection."""
        if result.returncode != 0:
            stderr = result.stderr or ""
            if "does not look like" in stderr:
                issues.append(
                    OperationIssue(
                        "image.no_vbmeta_structure",
                        f"Image has no vbmeta structure: {name}",
                    )
                )
                return ImageInspection(
                    image_name=name,
                    image_path=image_path,
                    descriptor=None,
                )
            issues.append(
                OperationIssue(
                    "tool.execution_failed",
                    f"avbtool failed for {name}: {stderr.strip()}",
                )
            )
            return None

        parsed = parse_info_image(result.stdout)
        return _build_inspection(name, image_path, parsed)


def _build_inspection(
    image_name: str,
    image_path: str,
    parsed: dict[str, object],
) -> ImageInspection:
    """Build ImageInspection from parsed avbtool output."""
    header = parsed["header"]
    descs = parsed["descriptors"]
    props = parsed["props"]

    descriptor: DescriptorType | None = None
    partition_name: str | None = None
    algorithm: str | None = None
    public_key_sha1: str | None = None
    rollback_index: str | None = None
    salt: str | None = None
    digest: str | None = None
    flags: str | None = None
    raw_extensions: list[tuple[str, str]] = []

    if descs:
        block = descs[0]
        descriptor = _map_descriptor_type(block["type"])
        fields = block["fields"]
        partition_name = fields.get("Partition Name")
        algorithm = fields.get("Hash Algorithm") or fields.get("Algorithm")
        salt = fields.get("Salt")
        digest = fields.get("Digest") or fields.get("Root Digest")
        flags = fields.get("Flags")
        known_fields = {
            "Partition Name",
            "Hash Algorithm",
            "Algorithm",
            "Salt",
            "Digest",
            "Root Digest",
            "Flags",
            "Image Size",
            "Image size",
            "Tree Offset",
            "Tree Size",
            "Data Block Size",
            "Hash Block Size",
            "FEC num roots",
            "FEC offset",
            "FEC size",
            "Version of dm-verity",
            "Rollback Index Location",
            "Public key (sha1)",
            "Kernel Cmdline",
        }
        for k, v in fields.items():
            if k not in known_fields:
                raw_extensions.append((k, v))

    public_key_sha1 = header.get("Public key (sha1)")
    rollback_index = header.get("Rollback Index")
    if descriptor is None and header.get("Algorithm"):
        descriptor = DescriptorType.VBMETA

    return ImageInspection(
        image_name=image_name,
        image_path=image_path,
        descriptor=descriptor,
        algorithm=algorithm or header.get("Algorithm"),
        partition_name=partition_name,
        public_key_sha1=public_key_sha1,
        rollback_index=rollback_index,
        salt=salt,
        digest=digest,
        flags=flags or header.get("Flags"),
        props=tuple(props),
        raw_extensions=tuple(raw_extensions),
    )


def _map_descriptor_type(label: str) -> DescriptorType | None:
    """Map avbtool descriptor label to DescriptorType."""
    try:
        return DescriptorType.from_avbtool_label(label)
    except ValueError:
        return None
