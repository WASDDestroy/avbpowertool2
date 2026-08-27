"""Key management use cases."""

from __future__ import annotations

import logging

from avbpowertool.application.commands import (
    KeyAddRequest,
    KeyAddResult,
    KeyDiscoveryRequest,
    KeyDiscoveryResult,
    KeyListRequest,
    KeyListResult,
    KeyRemoveRequest,
    KeyRemoveResult,
)
from avbpowertool.application.ports import AvbToolPort
from avbpowertool.domain.models import OperationIssue
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.persistence.key_repository import KeyRepository

logger = logging.getLogger(__name__)

def ensure_public_keys(workspace: WorkspacePaths, avb_tool: AvbToolPort, profile_id: str) -> tuple[OperationIssue, ...]:
    key_dir = workspace.resolve_key_dir(profile_id)
    repo = KeyRepository(key_dir)
    manifest = repo.load_manifest(); issues: list[OperationIssue] = []; changed = False
    for key_id, entry in manifest.items():
        private_name = entry.get("private_key", "")
        private = key_dir / private_name
        if not private_name or not private.is_file(): continue
        public_name = entry.get("public_key") or f"{private_name}.bin"
        public = key_dir / public_name
        if not public.is_file():
            result = avb_tool.extract_public_key(private, public)
            if result.returncode != 0 or not public.is_file():
                issues.append(OperationIssue("keys.public_key_extract_failed", f"Failed to extract public key for {key_id!r}")); continue
        if entry.get("public_key") != public_name: entry["public_key"] = public_name; changed = True
    if changed: repo.save_manifest(manifest)
    return tuple(issues)


class KeyDiscoveryUseCase:
    """Discover .pem files and update the key manifest.

    Auto-discovery rule: each .pem filename (minus extension) becomes
    the key_id.  For example, ``release.pem`` -> key_id ``release``.
    """

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


class KeyListUseCase:
    """List keys in a profile's key store.

    Returns manifest entries plus any .pem files on disk that are
    NOT yet in the manifest (unregistered keys).
    """

    def __init__(self, workspace: WorkspacePaths) -> None:
        self._ws = workspace

    def execute(self, request: KeyListRequest) -> KeyListResult:
        issues: list[OperationIssue] = []
        key_dir = self._ws.resolve_key_dir(request.profile_id)

        if not key_dir.exists():
            issues.append(
                OperationIssue(
                    "keys.directory_not_found",
                    f"Key directory not found: {key_dir}",
                )
            )
            return KeyListResult(
                manifest_entries=(),
                pem_files_on_disk=(),
                issues=tuple(issues),
            )

        repo = KeyRepository(key_dir)
        manifest = repo.load_manifest()
        discovered = repo.discover_keys()

        # Manifest entries
        entries = [(kid, entry.get("private_key", "")) for kid, entry in manifest.items()]

        # Find .pem files NOT in manifest
        registered_files = {entry.get("private_key", "") for entry in manifest.values()}
        unregistered = [filename for filename, _ in discovered if filename not in registered_files]

        return KeyListResult(
            manifest_entries=tuple(entries),
            pem_files_on_disk=tuple(unregistered),
            issues=tuple(issues),
        )


class KeyAddUseCase:
    """Add a key entry to the manifest."""

    def __init__(self, workspace: WorkspacePaths) -> None:
        self._ws = workspace

    def execute(self, request: KeyAddRequest) -> KeyAddResult:
        issues: list[OperationIssue] = []
        key_dir = self._ws.resolve_key_dir(request.profile_id)

        if not key_dir.exists():
            issues.append(
                OperationIssue("keys.directory_not_found", f"Key directory not found: {key_dir}")
            )
            return KeyAddResult(key_id=request.key_id, issues=tuple(issues))

        if not request.key_id or not request.private_key_filename:
            issues.append(
                OperationIssue("keys.invalid_request", "Key ID and filename are required")
            )
            return KeyAddResult(key_id=request.key_id, issues=tuple(issues))

        # Check file exists
        key_path = key_dir / request.private_key_filename
        if not key_path.exists():
            issues.append(OperationIssue("keys.file_not_found", f"Key file not found: {key_path}"))
            return KeyAddResult(key_id=request.key_id, issues=tuple(issues))

        repo = KeyRepository(key_dir)
        manifest = repo.load_manifest()

        if request.key_id in manifest:
            issues.append(
                OperationIssue(
                    "keys.already_exists",
                    f"Key ID {request.key_id!r} already exists in manifest",
                )
            )
            return KeyAddResult(key_id=request.key_id, issues=tuple(issues))

        manifest[request.key_id] = {"private_key": request.private_key_filename}
        repo.save_manifest(manifest)
        logger.info("Added key %r -> %s", request.key_id, request.private_key_filename)

        return KeyAddResult(key_id=request.key_id, issues=tuple(issues))


class KeyRemoveUseCase:
    """Remove a key entry from the manifest."""

    def __init__(self, workspace: WorkspacePaths) -> None:
        self._ws = workspace

    def execute(self, request: KeyRemoveRequest) -> KeyRemoveResult:
        issues: list[OperationIssue] = []
        key_dir = self._ws.resolve_key_dir(request.profile_id)

        if not key_dir.exists():
            issues.append(
                OperationIssue("keys.directory_not_found", f"Key directory not found: {key_dir}")
            )
            return KeyRemoveResult(key_id=request.key_id, issues=tuple(issues))

        repo = KeyRepository(key_dir)
        manifest = repo.load_manifest()

        if request.key_id not in manifest:
            issues.append(
                OperationIssue("keys.not_found", f"Key ID {request.key_id!r} not in manifest")
            )
            return KeyRemoveResult(key_id=request.key_id, issues=tuple(issues))

        del manifest[request.key_id]
        repo.save_manifest(manifest)
        logger.info("Removed key %r from manifest", request.key_id)

        return KeyRemoveResult(key_id=request.key_id, issues=tuple(issues))
