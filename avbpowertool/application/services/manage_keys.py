"""Key management use cases."""

from __future__ import annotations

import logging
from pathlib import Path

from avbpowertool.application.commands import (
    KeyAddRequest,
    KeyAddResult,
    KeyDiscoveryRequest,
    KeyDiscoveryResult,
    KeyEnsurePublicRequest,
    KeyEnsurePublicResult,
    KeyListRequest,
    KeyListResult,
    KeyRemoveRequest,
    KeyRemoveResult,
)
from avbpowertool.application.ports import AvbToolPort
from avbpowertool.application.services.profile_resolution import (
    resolve_key_store_profile_id,
)
from avbpowertool.domain.models import OperationIssue
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.persistence.key_repository import KeyRepository

logger = logging.getLogger(__name__)

# Manifest fields cached from a previous public-key extraction.  They are
# only trustworthy while the entry still points at the same private key.
_CACHED_PUBLIC_FIELDS = ("public_key", "public_key_sha1")


def _directory_not_found_issue(profile_id: str, key_dir: Path) -> OperationIssue:
    """Build the shared ``keys.directory_not_found`` issue.

    The resolved profile id and the key directory are part of the
    message so a caller can tell which profile was actually addressed
    (``--profile`` omitted resolves to the active profile).
    """
    return OperationIssue(
        "keys.directory_not_found",
        f"Key directory not found for profile {profile_id!r}: {key_dir}",
    )


def ensure_public_keys(
    workspace: WorkspacePaths, avb_tool: AvbToolPort, profile_id: str
) -> tuple[OperationIssue, ...]:
    key_dir = workspace.resolve_key_dir(profile_id)
    repo = KeyRepository(key_dir)
    manifest = repo.load_manifest()
    issues: list[OperationIssue] = []
    changed = False

    for key_id, entry in manifest.items():
        private_name = entry.get("private_key", "")
        private = key_dir / private_name
        if not private_name or not private.is_file():
            continue
        public_name = entry.get("public_key") or f"{private_name}.bin"
        public = key_dir / public_name
        if not public.is_file():
            result = avb_tool.extract_public_key(private, public)
            if result.returncode != 0 or not public.is_file():
                issues.append(
                    OperationIssue(
                        "keys.public_key_extract_failed",
                        f"Failed to extract public key for {key_id!r}",
                    )
                )
                continue
        if entry.get("public_key") != public_name:
            entry["public_key"] = public_name
            changed = True
    if changed:
        repo.save_manifest(manifest)
    return tuple(issues)


class KeyDiscoveryUseCase:
    """Discover .pem files and update the key manifest.

    Auto-discovery rule: each .pem filename (minus extension) becomes
    the key_id.  For example, ``release.pem`` -> key_id ``release``.

    Two modes (see :class:`KeyDiscoveryRequest`):

    ``merge`` (default)
        The manifest already on disk is the baseline.  Every discovered
        ``.pem`` sets its own entry's ``private_key``; the cached
        ``public_key`` / ``public_key_sha1`` are kept **only** when the
        entry's previous ``private_key`` is the same filename (a renamed
        file means the cache belongs to a different key).  Entries whose
        ``.pem`` no longer exists on disk are left untouched.

    ``replace``
        Historical behaviour: the manifest is rebuilt from the discovered
        ``.pem`` files only, so every cached ``public_key`` is dropped.
    """

    def __init__(self, workspace: WorkspacePaths) -> None:
        self._ws = workspace

    def execute(self, request: KeyDiscoveryRequest) -> KeyDiscoveryResult:
        issues: list[OperationIssue] = []
        profile_id, resolution_issue = resolve_key_store_profile_id(self._ws, request.profile_id)
        if resolution_issue is not None:
            issues.append(resolution_issue)
            return KeyDiscoveryResult(
                discovered_count=0,
                manifest_entries=(),
                issues=tuple(issues),
                merged=request.merge,
            )
        key_dir = self._ws.resolve_key_dir(profile_id)

        if not key_dir.exists():
            issues.append(_directory_not_found_issue(profile_id, key_dir))
            return KeyDiscoveryResult(
                discovered_count=0,
                manifest_entries=(),
                issues=tuple(issues),
                merged=request.merge,
            )

        repo = KeyRepository(key_dir)
        discovered = repo.discover_keys()
        previous = repo.load_manifest()

        # Build manifest entries from discovered PEM files
        manifest: dict[str, dict[str, str]] = dict(previous) if request.merge else {}
        entries: list[tuple[str, str]] = []

        for filename, _path in discovered:
            # Use filename without extension as key_id
            key_id = filename.removesuffix(".pem")
            old_entry = previous.get(key_id, {})
            new_entry: dict[str, str] = {"private_key": filename}
            if request.merge and old_entry.get("private_key") == filename:
                # Same file as before: the cached public key still matches.
                for field_name in _CACHED_PUBLIC_FIELDS:
                    cached = old_entry.get(field_name)
                    if cached:
                        new_entry[field_name] = cached
            manifest[key_id] = new_entry
            entries.append((key_id, filename))

        retained = len(set(manifest) - {key_id for key_id, _ in entries})
        changed = manifest != previous
        if changed and (request.merge or manifest):
            repo.save_manifest(manifest)
            logger.info("Discovered %d keys in %s", len(entries), key_dir)

        return KeyDiscoveryResult(
            discovered_count=len(discovered),
            manifest_entries=tuple(entries),
            issues=tuple(issues),
            retained_count=retained,
            merged=request.merge,
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
        profile_id, resolution_issue = resolve_key_store_profile_id(self._ws, request.profile_id)
        if resolution_issue is not None:
            issues.append(resolution_issue)
            return KeyListResult(
                manifest_entries=(),
                pem_files_on_disk=(),
                issues=tuple(issues),
            )
        key_dir = self._ws.resolve_key_dir(profile_id)

        if not key_dir.exists():
            issues.append(_directory_not_found_issue(profile_id, key_dir))
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
        profile_id, resolution_issue = resolve_key_store_profile_id(self._ws, request.profile_id)
        if resolution_issue is not None:
            issues.append(resolution_issue)
            return KeyAddResult(key_id=request.key_id, issues=tuple(issues))
        key_dir = self._ws.resolve_key_dir(profile_id)

        if not key_dir.exists():
            issues.append(_directory_not_found_issue(profile_id, key_dir))
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
        profile_id, resolution_issue = resolve_key_store_profile_id(self._ws, request.profile_id)
        if resolution_issue is not None:
            issues.append(resolution_issue)
            return KeyRemoveResult(key_id=request.key_id, issues=tuple(issues))
        key_dir = self._ws.resolve_key_dir(profile_id)

        if not key_dir.exists():
            issues.append(_directory_not_found_issue(profile_id, key_dir))
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


class KeyEnsurePublicUseCase:
    """Materialise the public-key files a key store still needs.

    Mirrors :func:`ensure_public_keys` (which stays untouched because
    ``SignImagesUseCase`` shares it) but reports what it did: the
    ``(key_id, public_key_filename)`` pairs it produced or newly
    registered, and the entries it had to skip because their private-key
    file is missing on disk (``keys.private_key_missing``).
    """

    def __init__(self, workspace: WorkspacePaths, avb_tool: AvbToolPort) -> None:
        self._ws = workspace
        self._avb_tool = avb_tool

    def execute(self, request: KeyEnsurePublicRequest) -> KeyEnsurePublicResult:
        issues: list[OperationIssue] = []
        profile_id, resolution_issue = resolve_key_store_profile_id(self._ws, request.profile_id)
        if resolution_issue is not None:
            issues.append(resolution_issue)
            return KeyEnsurePublicResult(issues=tuple(issues))
        key_dir = self._ws.resolve_key_dir(profile_id)

        if not key_dir.exists():
            issues.append(_directory_not_found_issue(profile_id, key_dir))
            return KeyEnsurePublicResult(issues=tuple(issues))

        repo = KeyRepository(key_dir)
        manifest = repo.load_manifest()
        extracted: list[tuple[str, str]] = []
        skipped: list[str] = []
        changed = False

        for key_id, entry in manifest.items():
            private_name = entry.get("private_key", "")
            private = key_dir / private_name
            if not private_name or not private.is_file():
                skipped.append(key_id)
                issues.append(
                    OperationIssue(
                        "keys.private_key_missing",
                        f"Private key file missing for {key_id!r}: {private}",
                    )
                )
                continue
            public_name = entry.get("public_key") or f"{private_name}.bin"
            public = key_dir / public_name
            if not public.is_file():
                result = self._avb_tool.extract_public_key(private, public)
                if result.returncode != 0 or not public.is_file():
                    issues.append(
                        OperationIssue(
                            "keys.public_key_extract_failed",
                            f"Failed to extract public key for {key_id!r}",
                        )
                    )
                    continue
                extracted.append((key_id, public_name))
            if entry.get("public_key") != public_name:
                entry["public_key"] = public_name
                changed = True

        if changed:
            repo.save_manifest(manifest)
            logger.info("Registered public keys for %d key(s)", len(manifest))

        return KeyEnsurePublicResult(
            extracted=tuple(extracted),
            skipped=tuple(skipped),
            issues=tuple(issues),
        )
