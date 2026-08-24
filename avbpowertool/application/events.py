"""Progress event types for long-running operations.

Events are emitted by use cases via a ProgressSink and consumed
by the presentation layer for UI updates.
"""

from __future__ import annotations

from dataclasses import dataclass

from avbpowertool.application.ports import ProgressEvent


@dataclass(frozen=True)
class PlanCreated(ProgressEvent):
    """A signing plan was created."""

    profile_id: str
    step_count: int


@dataclass(frozen=True)
class StepStarted(ProgressEvent):
    """A signing step is about to execute."""

    step_index: int
    step_total: int
    partition_name: str
    operation: str


@dataclass(frozen=True)
class StepCompleted(ProgressEvent):
    """A signing step finished."""

    step_index: int
    step_total: int
    partition_name: str
    success: bool
    error_message: str = ""


@dataclass(frozen=True)
class SigningCompleted(ProgressEvent):
    """All signing steps are done."""

    success_count: int
    fail_count: int
    skip_count: int
