"""Profile management use cases."""

from __future__ import annotations

import logging
from dataclasses import replace

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
    """Delete a profile, refusing to remove the active profile."""

    def __init__(self, workspace: WorkspacePaths) -> None:
        self._ws = workspace

    def execute(self, request: ProfileDeleteRequest) -> ProfileDeleteResult:
        repo = ProfileRepository(self._ws)
        if request.profile_id not in repo.list_profiles():
            logger.warning("Cannot delete missing profile %r", request.profile_id)
            return ProfileDeleteResult(
                request.profile_id,
                (OperationIssue("config.not_found", f"Profile not found: {request.profile_id}"),),
            )
        if repo.get_active_profile_id() == request.profile_id:
            logger.warning("Refused to delete active profile %r", request.profile_id)
            return ProfileDeleteResult(
                request.profile_id,
                (
                    OperationIssue(
                        "config.active_delete_forbidden", "Cannot delete the active profile"
                    ),
                ),
            )
        try:
            repo.delete(request.profile_id)
            logger.info("Deleted profile %r", request.profile_id)
        except Exception as exc:
            logger.error("Failed to delete profile %r: %s", request.profile_id, exc)
            return ProfileDeleteResult(
                request.profile_id,
                (OperationIssue("config.delete_failed", f"Failed to delete profile: {exc}"),),
            )
        return ProfileDeleteResult(request.profile_id)


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
