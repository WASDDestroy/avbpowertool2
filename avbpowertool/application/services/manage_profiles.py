"""Profile management use cases."""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from avbpowertool.application.commands import (
    ProfileActivateRequest,
    ProfileActivateResult,
    ProfileDeleteRequest,
    ProfileDeleteResult,
    ProfileListItem,
    ProfileListRequest,
    ProfileListResult,
    ProfileRenameRequest,
    ProfileRenameResult,
)
from avbpowertool.application.services.manage_configs import sanitize_profile_id
from avbpowertool.domain.errors import ConfigError
from avbpowertool.domain.models import OperationIssue
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.persistence.profile_repository import (
    ProfileRepository,
)

logger = logging.getLogger(__name__)


class ProfileListUseCase:
    """List all profiles with their status."""

    def __init__(self, workspace: WorkspacePaths) -> None:
        self._ws = workspace

    def execute(self, _request: ProfileListRequest) -> ProfileListResult:
        issues: list[OperationIssue] = []
        repo = ProfileRepository(self._ws)

        active_id = repo.get_active_profile_id()
        profile_ids = repo.list_profiles()

        items: list[ProfileListItem] = []
        for pid in profile_ids:
            try:
                profile = repo.load(pid)
                items.append(
                    ProfileListItem(
                        profile_id=pid,
                        name=profile.name,
                        is_active=(pid == active_id),
                        partition_count=len(profile.partitions),
                    )
                )
            except Exception as exc:
                issues.append(
                    OperationIssue(
                        "config.load_error",
                        f"Failed to load profile {pid!r}: {exc}",
                    )
                )

        return ProfileListResult(
            profiles=tuple(items),
            active_profile_id=active_id,
            issues=tuple(issues),
        )


class ProfileActivateUseCase:
    """Activate a profile by ID."""

    def __init__(self, workspace: WorkspacePaths) -> None:
        self._ws = workspace

    def execute(self, request: ProfileActivateRequest) -> ProfileActivateResult:
        issues: list[OperationIssue] = []
        repo = ProfileRepository(self._ws)

        # Verify profile exists
        profile_ids = repo.list_profiles()
        if request.profile_id not in profile_ids:
            logger.warning("Cannot activate missing profile %r", request.profile_id)
            issues.append(
                OperationIssue(
                    "config.not_found",
                    f"Profile not found: {request.profile_id}",
                )
            )
            return ProfileActivateResult(
                profile_id=request.profile_id,
                issues=tuple(issues),
            )

        try:
            repo.activate(request.profile_id)
            logger.info("Activated profile %r", request.profile_id)
        except Exception as exc:
            logger.error("Failed to activate profile %r: %s", request.profile_id, exc)
            issues.append(
                OperationIssue(
                    "config.activate_failed",
                    f"Failed to activate profile: {exc}",
                )
            )

        return ProfileActivateResult(
            profile_id=request.profile_id,
            issues=tuple(issues),
        )


class ProfileDeleteUseCase:
    """Delete a profile directory, refusing the active one unless forced.

    Order of operations — every failure returns before anything is removed:

    1. the id must be a plain directory name: empty, ``.``, ``..`` or
       anything containing ``/`` / ``\\`` is rejected with
       ``config.invalid_profile_id``, and so is a value whose resolved
       directory is not a *direct* child of ``profiles/`` (defence in depth
       against a path that escapes the profile root);
    2. ``profiles/<id>/profile.json`` must exist (a bare directory does not
       count), otherwise ``config.not_found``;
    3. the active profile is refused with ``config.active_delete_forbidden``
       unless ``force`` is set;
    4. the files under the directory are counted *before* the removal, so
       ``deleted_files`` / ``deleted_bytes`` describe what was there;
    5. the directory is removed; an ``OSError`` (a locked file on Windows,
       for instance) reports ``config.delete_failed``;
    6. with ``force``, ``.active-profile`` is unlinked when it still pointed
       at the deleted id (a missing file is ignored).
    """

    def __init__(self, workspace: WorkspacePaths) -> None:
        self._ws = workspace

    def execute(self, request: ProfileDeleteRequest) -> ProfileDeleteResult:
        profile_id = request.profile_id

        # 1. Never let an id address anything but one directory under
        # profiles/: a separator or a dot-dot would make rmtree escape.
        if not profile_id or profile_id in (".", "..") or "/" in profile_id or "\\" in profile_id:
            logger.warning("Refused to delete invalid profile id %r", profile_id)
            return ProfileDeleteResult(
                profile_id,
                (
                    OperationIssue(
                        "config.invalid_profile_id",
                        f"Invalid profile id: {profile_id!r} "
                        "(must be a single directory name under profiles/)",
                    ),
                ),
            )

        profile_dir = self._ws.resolve_profile_dir(profile_id)
        if profile_dir.resolve().parent != self._ws.profiles.resolve():
            logger.warning("Refused to delete profile id outside profiles/: %r", profile_id)
            return ProfileDeleteResult(
                profile_id,
                (
                    OperationIssue(
                        "config.invalid_profile_id",
                        f"Invalid profile id: {profile_id!r} "
                        "(must be a single directory name under profiles/)",
                    ),
                ),
            )

        repo = ProfileRepository(self._ws)

        # 2. A directory without profile.json is not a profile.
        if not (profile_dir / "profile.json").is_file():
            logger.warning("Cannot delete missing profile %r", profile_id)
            return ProfileDeleteResult(
                profile_id,
                (OperationIssue("config.not_found", f"Profile not found: {profile_id}"),),
            )

        # 3. The active profile is protected unless the caller forces it.
        active_id = repo.get_active_profile_id()
        if active_id == profile_id and not request.force:
            logger.warning("Refused to delete active profile %r", profile_id)
            return ProfileDeleteResult(
                profile_id,
                (
                    OperationIssue(
                        "config.active_delete_forbidden", "Cannot delete the active profile"
                    ),
                ),
            )

        # 4. Count what is about to go away (rmtree destroys the evidence).
        deleted_files, deleted_bytes = _count_regular_files(profile_dir)

        # 5. Remove the directory.
        try:
            repo.delete(profile_id)
        except (OSError, ConfigError) as exc:
            logger.error("Failed to delete profile %r: %s", profile_id, exc)
            return ProfileDeleteResult(
                profile_id,
                (OperationIssue("config.delete_failed", f"Failed to delete profile: {exc}"),),
            )

        # 6. A forced delete of the active profile must not leave a dangling
        # pointer behind; another profile's pointer is left alone.
        if active_id == profile_id:
            try:
                self._clear_active_pointer(profile_id)
            except OSError as exc:
                logger.error("Failed to clear .active-profile for %r: %s", profile_id, exc)

        logger.info(
            "Deleted profile %r (%d files, %d bytes)", profile_id, deleted_files, deleted_bytes
        )
        return ProfileDeleteResult(
            profile_id,
            deleted=True,
            deleted_files=deleted_files,
            deleted_bytes=deleted_bytes,
        )

    def _clear_active_pointer(self, profile_id: str) -> None:
        """Unlink ``.active-profile`` when it still names *profile_id*."""
        active_path = self._ws.root / ".active-profile"
        if not active_path.exists():
            return
        if active_path.read_text(encoding="utf-8").strip() != profile_id:
            return
        active_path.unlink()
        logger.info("Cleared .active-profile after deleting %r", profile_id)


def _count_regular_files(directory: Path) -> tuple[int, int]:
    """Return ``(file_count, total_bytes)`` of the regular files under *directory*."""
    files = 0
    total = 0
    for path in directory.rglob("*"):
        try:
            if path.is_symlink() or not path.is_file():
                continue
            total += path.stat().st_size
        except OSError:
            # A file that cannot be stat'ed simply does not contribute; the
            # removal below decides whether the delete itself fails.
            continue
        files += 1
    return files, total


class ProfileRenameUseCase:
    """Rename a profile directory and/or its display name.

    The profile directory name and the ``id`` embedded in ``profile.json``
    are an implicit invariant: :meth:`ProfileRepository.save` writes to
    ``profiles/<profile.id>/`` while ``list_profiles`` enumerates the
    directory names, and ``config edit`` refuses a profile whose embedded
    id disagrees with its directory (``config.profile_id_mismatch``).
    Renaming therefore moves the directory *and* rewrites the embedded id
    through ``ProfileRepository.save``, which repairs such stale data as
    a side effect.

    Order of operations — every failure returns before anything else is
    written:

    1. the new id must survive :func:`sanitize_profile_id` unchanged,
       otherwise ``config.invalid_profile_id``;
    2. ``profiles/<old>/profile.json`` must exist (a directory without it
       counts as missing), otherwise ``config.not_found``;
    3. ``profiles/<new>`` must not exist unless it is the old profile
       itself, otherwise ``config.profile_exists``;
    4. the directory is moved; an ``OSError`` (a locked directory on
       Windows, for instance) reports ``config.rename_failed`` after a
       best-effort rollback, so no half-renamed profile is left behind;
    5. ``profile.json`` is rewritten with the new id and, when
       ``new_name`` was given, the new display name;
    6. ``.active-profile`` follows the rename when it pointed at the old
       id.

    When ``new_profile_id == profile_id`` no directory move happens
    (``renamed`` stays ``False``) and only the display name — plus the
    embedded id, when it disagrees with the directory — is written.
    """

    def __init__(self, workspace: WorkspacePaths) -> None:
        self._ws = workspace

    def execute(self, request: ProfileRenameRequest) -> ProfileRenameResult:
        repo = ProfileRepository(self._ws)

        old_id = request.profile_id
        # The requested id must be usable as a directory name as-is;
        # silently rewriting it would rename the profile to another id.
        new_id = sanitize_profile_id(request.new_profile_id)
        if new_id != request.new_profile_id:
            logger.warning("Refused to rename to invalid profile id %r", request.new_profile_id)
            return ProfileRenameResult(
                old_profile_id=old_id,
                profile_id=request.new_profile_id,
                issues=(
                    OperationIssue(
                        "config.invalid_profile_id",
                        f"Invalid profile id: {request.new_profile_id!r} "
                        "(use letters, digits, '_', '-', '.' only)",
                    ),
                ),
            )

        old_dir = self._ws.resolve_profile_dir(old_id)
        if not (old_dir / "profile.json").is_file():
            logger.warning("Cannot rename missing profile %r", old_id)
            return ProfileRenameResult(
                old_profile_id=old_id,
                profile_id=new_id,
                issues=(OperationIssue("config.not_found", f"Profile not found: {old_id}"),),
            )

        new_dir = self._ws.resolve_profile_dir(new_id)
        if new_id != old_id and new_dir.exists():
            logger.warning("Refused to rename %r onto existing profile %r", old_id, new_id)
            return ProfileRenameResult(
                old_profile_id=old_id,
                profile_id=new_id,
                issues=(
                    OperationIssue("config.profile_exists", f"Profile already exists: {new_id}"),
                ),
            )

        renamed = False
        if new_id != old_id:
            try:
                old_dir.rename(new_dir)
            except OSError as exc:
                # Windows refuses to move a directory whose files are open;
                # a failed move may still have created the target, so put
                # the profile back before reporting the failure.
                if new_dir.exists() and not old_dir.exists():
                    try:
                        new_dir.rename(old_dir)
                    except OSError as rollback_exc:
                        logger.error(
                            "Failed to roll back partial rename %r -> %r: %s",
                            old_id,
                            new_id,
                            rollback_exc,
                        )
                logger.error("Failed to rename profile %r to %r: %s", old_id, new_id, exc)
                return ProfileRenameResult(
                    old_profile_id=old_id,
                    profile_id=new_id,
                    issues=(
                        OperationIssue(
                            "config.rename_failed",
                            f"Failed to rename profile: {exc}",
                        ),
                    ),
                )
            renamed = True

        try:
            profile = repo.load(new_id)
        except ConfigError as exc:
            logger.error("Failed to load profile %r after rename: %s", new_id, exc)
            return ProfileRenameResult(
                old_profile_id=old_id,
                profile_id=new_id,
                renamed=renamed,
                issues=(OperationIssue(exc.error_code, str(exc)),),
            )

        name_changed = request.new_name is not None
        # "Same id, no --name, embedded id already correct" is a pure
        # no-op: rewriting profile.json would only churn the file.  Every
        # other case rewrites it with the new id (which is also what
        # repairs a directory whose embedded id disagreed with it).
        if renamed or name_changed or profile.id != new_id:
            updated = replace(
                profile,
                id=new_id,
                name=request.new_name if request.new_name is not None else profile.name,
            )
            try:
                repo.save(updated)
            except Exception as exc:
                logger.error("Failed to save renamed profile %r: %s", new_id, exc)
                return ProfileRenameResult(
                    old_profile_id=old_id,
                    profile_id=new_id,
                    renamed=renamed,
                    name_changed=name_changed,
                    issues=(
                        OperationIssue("config.save_failed", f"Failed to save profile: {exc}"),
                    ),
                )

        issues: list[OperationIssue] = []
        if renamed and repo.get_active_profile_id() == old_id:
            try:
                repo.activate(new_id)
            except OSError as exc:
                logger.error("Failed to update .active-profile to %r: %s", new_id, exc)
                issues.append(
                    OperationIssue(
                        "config.activate_failed",
                        f"Failed to update .active-profile: {exc}",
                    )
                )

        logger.info("Renamed profile %r to %r (renamed=%s)", old_id, new_id, renamed)
        return ProfileRenameResult(
            old_profile_id=old_id,
            profile_id=new_id,
            renamed=renamed,
            name_changed=name_changed,
            issues=tuple(issues),
        )
