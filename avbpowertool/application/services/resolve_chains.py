"""ResolveChainKeysUseCase — map chain descriptors to key-store files.

A chain-partition descriptor in a vbmeta image references the partition
by name, a rollback-index location, and the SHA1 of the raw public-key
blob.  This use case extracts that same public-key blob from every key
in the profile's key store (via ``avbtool extract_public_key``), hashes
it, and resolves each chain descriptor to the matching key file.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from avbpowertool.application.commands import (
    ChainKeyResolution,
    ResolveChainKeysRequest,
    ResolveChainKeysResult,
)
from avbpowertool.application.ports import AvbToolPort
from avbpowertool.domain.models import OperationIssue
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.persistence.key_repository import KeyRepository

logger = logging.getLogger(__name__)


class ResolveChainKeysUseCase:
    """Resolve chain descriptors to ``PART:SLOT:KEY_FILE`` entries."""

    def __init__(self, workspace: WorkspacePaths, avb_tool: AvbToolPort) -> None:
        self._ws = workspace
        self._avb = avb_tool

    def execute(self, request: ResolveChainKeysRequest) -> ResolveChainKeysResult:
        if not request.chains:
            return ResolveChainKeysResult()

        key_dir = self._ws.resolve_key_dir(request.profile_id)
        manifest = KeyRepository(key_dir).load_manifest()

        # Map public-key SHA1 -> (key_id, extracted public-key filename).
        sha1_map: dict[str, tuple[str, str]] = {}
        for key_id, entry in manifest.items():
            filename = entry.get("private_key", "")
            if not filename:
                continue
            key_path = key_dir / filename
            if not key_path.exists():
                continue
            public_key = Path(entry.get("public_key", "")) if entry.get("public_key") else key_path.with_name(key_path.name + ".bin")
            if not public_key.is_absolute():
                public_key = key_dir / public_key
            digest = self._public_key_sha1(key_path, public_key)
            if digest:
                sha1_map[digest] = (key_id, public_key.name)

        resolutions: list[ChainKeyResolution] = []
        issues: list[OperationIssue] = []
        for chain in request.chains:
            match = sha1_map.get((chain.public_key_sha1 or "").lower())
            if match is None:
                issues.append(
                    OperationIssue(
                        "chain.key_not_found",
                        "Chain partition {!r}: no key in store matches public key {}".format(
                            chain.partition_name,
                            chain.public_key_sha1 or "(unknown)",
                        ),
                    )
                )
                resolutions.append(ChainKeyResolution())
                continue
            key_id, filename = match
            resolutions.append(
                ChainKeyResolution(
                    entry=f"{chain.partition_name}:{chain.rollback_index_location}:{filename}",
                    key_id=key_id,
                )
            )

        return ResolveChainKeysResult(
            resolutions=tuple(resolutions),
            issues=tuple(issues),
        )

    def _public_key_sha1(self, key_path: Path, public_key: Path) -> str | None:
        """Return the SHA1 of the public-key blob extracted from a private key.

        This is the same value avbtool info_image prints as
        ``Public key (sha1)`` (SHA1 over the encoded RSA public key).
        """
        pub_out = public_key
        if not pub_out.exists():
            result = self._avb.extract_public_key(key_path, pub_out)
            if result.returncode != 0:
                logger.warning(
                    "extract_public_key failed for %s: %s",
                    key_path,
                    (result.stderr or "").strip(),
                )
                return None
        try:
            blob = pub_out.read_bytes()
        except OSError as exc:
            logger.warning("Failed to read public key blob: %s", exc)
            return None
        return hashlib.sha1(blob).hexdigest()
