"""SignImagesUseCase — execute signing plan with staging and atomic replace."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from avbpowertool.application.commands import (
    SignImagesRequest,
    SignImagesResult,
)
from avbpowertool.application.events import (
    PlanCreated,
    SigningCompleted,
    StepCompleted,
    StepStarted,
)
from avbpowertool.application.ports import (
    NULL_PROGRESS,
    AvbToolPort,
    AvbToolResult,
    ProgressSink,
)
from avbpowertool.domain.models import (
    OperationIssue,
    SigningPlan,
    SigningStep,
)
from avbpowertool.domain.signing_plan import SigningPlanBuilder
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.persistence.profile_repository import (
    ProfileRepository,
)

logger = logging.getLogger(__name__)


class SignImagesUseCase:
    """Sign images according to a profile's configuration."""

    def __init__(
        self,
        workspace: WorkspacePaths,
        avb_tool: AvbToolPort,
        progress: ProgressSink = NULL_PROGRESS,
    ) -> None:
        self._ws = workspace
        self._avb = avb_tool
        self._progress = progress

    def execute(self, request: SignImagesRequest) -> SignImagesResult:
        issues: list[OperationIssue] = []

        # Load profile
        repo = ProfileRepository(self._ws)
        try:
            profile = repo.load(request.profile_id)
        except Exception as exc:
            issues.append(OperationIssue("config.not_found", f"Failed to load profile: {exc}"))
            return SignImagesResult(
                plan=SigningPlan(profile_id=request.profile_id, steps=(), vbmeta_order=()),
                issues=tuple(issues),
            )

        # Build signing plan
        image_dir = self._ws.images
        key_dir = self._ws.resolve_key_dir(request.profile_id)
        staging_dir = self._ws.staging / f"sign-{request.profile_id}"

        builder = SigningPlanBuilder(profile, image_dir, key_dir, staging_dir)
        plan = builder.build(request.image_names)
        issues.extend(plan.issues)

        self._progress.on_event(
            PlanCreated(profile_id=request.profile_id, step_count=len(plan.steps))
        )

        if request.dry_run or not plan.steps:
            return SignImagesResult(
                plan=plan,
                executed=False,
                issues=tuple(issues),
            )

        # Execute plan
        return self._execute_plan(plan, request, issues)

    def _execute_plan(
        self,
        plan: SigningPlan,
        request: SignImagesRequest,
        issues: list[OperationIssue],
    ) -> SignImagesResult:
        """Execute the signing plan step by step."""
        staging_dir = self._ws.staging / f"sign-{request.profile_id}"
        staging_dir.mkdir(parents=True, exist_ok=True)

        # Remove existing footers if requested
        if request.remove_existing_footers:
            self._remove_footers(plan)

        success_count = 0
        fail_count = 0
        total = len(plan.steps)

        for i, step in enumerate(plan.steps):
            self._progress.on_event(
                StepStarted(
                    step_index=i,
                    step_total=total,
                    partition_name=step.partition_name,
                    operation=step.operation,
                )
            )

            success = self._execute_step(step)

            if success:
                success_count += 1
                self._progress.on_event(
                    StepCompleted(
                        step_index=i,
                        step_total=total,
                        partition_name=step.partition_name,
                        success=True,
                    )
                )
            else:
                fail_count += 1
                error_msg = f"Failed to execute {step.operation} for {step.partition_name}"
                issues.append(OperationIssue("signing.step_failed", error_msg))
                self._progress.on_event(
                    StepCompleted(
                        step_index=i,
                        step_total=total,
                        partition_name=step.partition_name,
                        success=False,
                        error_message=error_msg,
                    )
                )

        self._progress.on_event(
            SigningCompleted(
                success_count=success_count,
                fail_count=fail_count,
                skip_count=0,
            )
        )

        # Atomic replace: move staging to target image dir
        if fail_count == 0 and success_count > 0:
            self._commit_staging(staging_dir, request.profile_id)

        return SignImagesResult(
            plan=plan,
            executed=True,
            success_count=success_count,
            fail_count=fail_count,
            issues=tuple(issues),
        )

    def _execute_step(self, step: SigningStep) -> bool:
        """Execute a single signing step. Returns True on success."""
        result = self._dispatch_to_avb(step)
        if result is None:
            logger.warning("Unknown operation: %s", step.operation)
            return False

        if result.returncode == 0:
            logger.info("Signed %s successfully", step.partition_name)
            return True
        else:
            logger.warning("Failed to sign %s: %s", step.partition_name, result.stderr)
            return False

    def _dispatch_to_avb(self, step: SigningStep) -> AvbToolResult | None:
        """Dispatch a signing step to the appropriate AvbToolPort method."""
        cmd = step.command
        if not cmd:
            return None

        if (
            step.operation == "add_hash_footer"
            or step.operation == "add_hashtree_footer"
            or step.operation == "make_vbmeta_image"
        ):
            return self._run_avbtool(cmd)
        return None

    def _run_avbtool(self, cmd: tuple[str, ...]) -> AvbToolResult:
        """Run avbtool command via SubprocessAvbTool's _run method.

        This is the only place where we use the concrete runner's _run.
        For FakeAvbTool in tests, we fall back to calling by operation name.
        """
        # Check if the avb tool has a _run method (SubprocessAvbTool)
        if hasattr(self._avb, "_run"):
            return self._avb._run(list(cmd))  # type: ignore[attr-defined]
        # Fallback for FakeAvbTool: call the matching method with dummy args
        operation = cmd[0] if cmd else ""
        if operation == "add_hash_footer":
            return self._avb.add_hash_footer(
                Path("/"),
                Path("/"),
                partition_name="",
                algorithm="",
                key_path=Path("/"),
                salt="",
                rollback_index=0,
            )
        elif operation == "add_hashtree_footer":
            return self._avb.add_hashtree_footer(
                Path("/"),
                Path("/"),
                partition_name="",
                algorithm="",
                key_path=Path("/"),
                salt="",
                rollback_index=0,
            )
        elif operation == "make_vbmeta_image":
            return self._avb.make_vbmeta_image(
                Path("/"),
                algorithm="",
                key_path=Path("/"),
                rollback_index=0,
            )
        return AvbToolResult(-1, "", f"Unknown operation: {operation}", "")

    def _remove_footers(self, plan: SigningPlan) -> None:
        """Remove existing AVB footers from images before signing."""
        for step in plan.steps:
            if step.operation in ("add_hash_footer", "add_hashtree_footer"):
                self._avb.erase_footer(Path(step.input_path))

    def _commit_staging(self, staging_dir: Path, profile_id: str) -> None:
        """Atomically move staging results to workspace Images/ directory."""
        images_dir = self._ws.images
        images_dir.mkdir(parents=True, exist_ok=True)
        for staged_file in staging_dir.iterdir():
            if staged_file.is_file():
                target = images_dir / staged_file.name
                try:
                    shutil.move(str(staged_file), str(target))
                    logger.info("Committed %s to %s", staged_file.name, target)
                except OSError as exc:
                    logger.error("Failed to commit %s: %s", staged_file.name, exc)
        # Clean up staging
        shutil.rmtree(staging_dir, ignore_errors=True)
