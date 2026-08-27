"""Profile management use cases."""

from __future__ import annotations

import logging

from avbpowertool.application.commands import (
    ProfileActivateRequest,
    ProfileActivateResult,
    ProfileDeleteRequest,
    ProfileDeleteResult,
    ProfileListItem,
    ProfileListRequest,
    ProfileListResult,
)
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
        except Exception as exc:
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
            return ProfileDeleteResult(
                request.profile_id,
                (OperationIssue("config.not_found", f"Profile not found: {request.profile_id}"),),
            )
        if repo.get_active_profile_id() == request.profile_id:
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
        except Exception as exc:
            return ProfileDeleteResult(
                request.profile_id,
                (OperationIssue("config.delete_failed", f"Failed to delete profile: {exc}"),),
            )
        return ProfileDeleteResult(request.profile_id)
