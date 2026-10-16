"""Chain-partition consistency checks (read-only).

``CheckChainsUseCase`` walks every ``chain_partitions`` entry of a profile
and reports *all* of its problems at once instead of stopping at the first
one.  It never writes to the profile directory or to the key store: the
only file it may create is a temporary public-key blob under the
workspace staging directory, used when ``keys/manifest.json`` has no
usable ``public_key`` for a key id.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from avbpowertool.application.commands import (
    ChainCheckEntry,
    CheckChainsRequest,
    CheckChainsResult,
)
from avbpowertool.application.ports import AvbToolPort
from avbpowertool.domain.errors import ConfigError
from avbpowertool.domain.models import (
    AvbProfile,
    OperationIssue,
    PartitionConfig,
    SigningAlgorithm,
)
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.persistence.key_repository import KeyRepository
from avbpowertool.infrastructure.persistence.profile_repository import (
    ProfileRepository,
)

# Staging sub-directory holding the public keys extracted for a check.
_STAGING_SUBDIR = "check-chains"


def parse_chain_entry(entry: str) -> tuple[str, int, str] | None:
    """Split a ``PART:SLOT:KEYFILE`` chain entry.

    Returns ``(partition, slot, key_file)`` or ``None`` when the entry is
    malformed: fewer than three segments, an empty partition, an empty key
    file, or a slot that is not a number ``>= 1``.  The key file keeps any
    further ``:`` (a Windows drive letter is part of the path), exactly as
    ``SigningPlanBuilder._resolve_chain_key`` does.
    """
    parts = entry.split(":")
    if len(parts) < 3 or not parts[0] or not parts[2]:
        return None
    try:
        slot = int(parts[1])
    except ValueError:
        return None
    if slot < 1:
        return None
    return parts[0], slot, ":".join(parts[2:])


def _sha1_of(path: Path) -> str:
    """Return the hex SHA1 of a file (the value avbtool prints as sha1)."""
    return hashlib.sha1(path.read_bytes()).hexdigest()


class CheckChainsUseCase:
    """Check the chain partitions of a profile against its key store.

    Every ``chain_partitions`` entry of every partition is checked (in
    practice only vbmeta partitions carry them), and the whole profile is
    reported in one pass: the use case never returns after the first
    failing entry.
    """

    def __init__(self, workspace: WorkspacePaths, avb_tool: AvbToolPort) -> None:
        self._ws = workspace
        self._avb_tool = avb_tool

    def execute(self, request: CheckChainsRequest) -> CheckChainsResult:
        repo = ProfileRepository(self._ws)
        try:
            profile_id = repo.resolve_profile_id(request.profile_id)
        except ConfigError as exc:
            return CheckChainsResult(
                profile_id=request.profile_id,
                issues=(OperationIssue(exc.error_code, str(exc)),),
            )

        try:
            profile = repo.load(profile_id)
        except Exception as exc:  # noqa: BLE001 - reported as an issue
            return CheckChainsResult(
                profile_id=profile_id,
                issues=(OperationIssue("config.not_found", f"Failed to load profile: {exc}"),),
            )

        key_dir = self._ws.resolve_key_dir(profile_id)
        manifest = KeyRepository(key_dir).load_manifest()

        issues: list[OperationIssue] = []
        entries: list[ChainCheckEntry] = []
        for partition_name, config in profile.partitions.items():
            for raw_entry in config.chain_partitions:
                entry_issues = self._check_entry(
                    profile, partition_name, raw_entry, key_dir, manifest
                )
                issues.extend(entry_issues)
                entries.append(
                    ChainCheckEntry(
                        partition_name=partition_name,
                        entry=raw_entry,
                        ok=not entry_issues,
                    )
                )

        return CheckChainsResult(
            profile_id=profile_id,
            checked=len(entries),
            issues=tuple(issues),
            entries=tuple(entries),
        )

    # ------------------------------------------------------------------
    # Checks for one chain entry
    # ------------------------------------------------------------------

    def _check_entry(
        self,
        profile: AvbProfile,
        partition_name: str,
        raw_entry: str,
        key_dir: Path,
        manifest: dict[str, dict[str, str]],
    ) -> list[OperationIssue]:
        """Return every issue of a single ``PART:SLOT:KEYFILE`` entry."""
        issues: list[OperationIssue] = []

        parsed = parse_chain_entry(raw_entry)
        if parsed is None:
            issues.append(
                OperationIssue(
                    "chain.malformed_entry",
                    f"Partition {partition_name!r}: malformed chain entry {raw_entry!r} "
                    "(expected PART:SLOT:KEYFILE with a numeric SLOT >= 1)",
                )
            )
            return issues

        chained_name, _slot, key_file = parsed
        if chained_name not in profile.partitions:
            issues.append(
                OperationIssue(
                    "config.missing_included_partition",
                    f"Partition {partition_name!r} chains to {chained_name!r}, "
                    "which is not in the profile",
                )
            )
            # Without the partition there is no algorithm and no key id to
            # compare the chain key against.
            return issues

        chained = profile.partitions[chained_name]
        if chained.algorithm is SigningAlgorithm.NONE:
            issues.append(
                OperationIssue(
                    "chain.chained_partition_unsigned",
                    f"Partition {partition_name!r}: chain entry {raw_entry!r} targets "
                    f"{chained_name!r}, which is unsigned (algorithm NONE); "
                    "the chain check is meaningless",
                )
            )
            # An unsigned partition has no signing key, so the key file and
            # its hash cannot be checked against anything meaningful.
            return issues

        key_path = Path(key_file)
        if not key_path.is_absolute():
            key_path = key_dir / key_path
        if not key_path.is_file():
            issues.append(
                OperationIssue(
                    "chain.key_file_missing",
                    f"Partition {partition_name!r}: chain entry {raw_entry!r} points at "
                    f"{key_file!r}, which is not in the key store ({key_path})",
                )
            )
            return issues

        public_key = self._resolve_public_key(partition_name, raw_entry, chained, key_dir, manifest)
        if isinstance(public_key, OperationIssue):
            issues.append(public_key)
            return issues

        chain_sha1 = _sha1_of(key_path)
        partition_sha1 = _sha1_of(public_key)
        if chain_sha1 != partition_sha1:
            issues.append(
                OperationIssue(
                    "chain.key_mismatch",
                    f"Partition {partition_name!r}: chain entry {raw_entry!r} uses "
                    f"{key_file!r} (sha1 {chain_sha1}), but {chained_name!r} is signed "
                    f"with key id {chained.key_id!r} (public key {public_key.name!r}, "
                    f"sha1 {partition_sha1})",
                )
            )
        return issues

    def _resolve_public_key(
        self,
        partition_name: str,
        raw_entry: str,
        chained: PartitionConfig,
        key_dir: Path,
        manifest: dict[str, dict[str, str]],
    ) -> Path | OperationIssue:
        """Locate the public key of the key id a chained partition signs with.

        The manifest's cached ``public_key`` file is used when it exists;
        otherwise the key is extracted into the staging directory (never
        into the key store).  Returns the public-key path, or the issue
        that prevented resolving it.
        """
        entry = manifest.get(chained.key_id)
        if entry is None:
            return OperationIssue(
                "config.key_missing",
                f"Partition {partition_name!r}: chain entry {raw_entry!r} targets "
                f"{chained.partition_name!r}, whose key id {chained.key_id!r} "
                "is not in the key manifest",
            )

        public_name = entry.get("public_key") or ""
        if public_name:
            cached = key_dir / public_name
            if cached.is_file():
                return cached

        private_name = entry.get("private_key") or ""
        if not private_name:
            return self._extract_failed_issue(partition_name, raw_entry, chained, key_dir)

        private_key = key_dir / private_name
        staged = self._ws.staging / _STAGING_SUBDIR / f"{Path(private_name).name}.bin"
        staged.parent.mkdir(parents=True, exist_ok=True)
        result = self._avb_tool.extract_public_key(private_key, staged)
        if result.returncode != 0 or not staged.is_file():
            return self._extract_failed_issue(partition_name, raw_entry, chained, key_dir)
        return staged

    def _extract_failed_issue(
        self,
        partition_name: str,
        raw_entry: str,
        chained: PartitionConfig,
        key_dir: Path,
    ) -> OperationIssue:
        return OperationIssue(
            "keys.public_key_extract_failed",
            f"Partition {partition_name!r}: chain entry {raw_entry!r} targets "
            f"{chained.partition_name!r}, whose public key for key id "
            f"{chained.key_id!r} could not be read from {key_dir}",
        )
