"""Key management use cases."""

from __future__ import annotations

import logging

from avbpowertool.application.commands import (
    KeyDiscoveryRequest,
    KeyDiscoveryResult,
)
from avbpowertool.domain.models import OperationIssue
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.persistence.key_repository import KeyRepository

logger = logging.getLogger(__name__)


class KeyDiscoveryUseCase:
    """Discover .pem files and update the key manifest."""

    def __init__(self, workspace: WorkspacePaths) -> None:
        self._ws = workspace

    def execute(self, request: KeyDiscoveryRequest) -> KeyDiscoveryResult:
        issues: list[OperationIssue] = []
        key_dir = self._ws.resolve_key_dir(request.profile_id)

        if not key_dir.exists():
            issues.append(
                OperationIssue(
                    "keys.directory_not_found",
                    f"Key directory not found: {key_dir}",
                )
            )
            return KeyDiscoveryResult(
                discovered_count=0,
                manifest_entries=(),
                issues=tuple(issues),
            )

        repo = KeyRepository(key_dir)
        discovered = repo.discover_keys()

        # Build manifest entries from discovered PEM files
        manifest: dict[str, dict[str, str]] = {}
        entries: list[tuple[str, str]] = []

        for filename, _path in discovered:
            # Use filename without extension as key_id
            key_id = filename.removesuffix(".pem")
            manifest[key_id] = {"private_key": filename}
            entries.append((key_id, filename))

        if manifest:
            repo.save_manifest(manifest)
            logger.info("Discovered %d keys in %s", len(manifest), key_dir)

        return KeyDiscoveryResult(
            discovered_count=len(discovered),
            manifest_entries=tuple(entries),
            issues=tuple(issues),
        )
