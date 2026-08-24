"""Port (interface) definitions for infrastructure adapters.

Every port is a typing.Protocol so that application services
can depend on the *contract* rather than on concrete implementations.
Tests supply fakes; production wires the real adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class AvbToolResult:
    """Raw result from an avbtool.py subprocess invocation."""

    returncode: int
    stdout: str
    stderr: str
    command_summary: str


@runtime_checkable
class AvbToolPort(Protocol):
    """Contract for invoking the bundled avbtool.py."""

    def inspect_image(self, image_path: Path) -> AvbToolResult:
        """Run avbtool.py info_image --image <image_path>."""
        ...

    def erase_footer(self, image_path: Path) -> AvbToolResult:
        """Run avbtool.py erase_footer --image <image_path>."""
        ...

    def add_hash_footer(
        self,
        image_path: Path,
        output_path: Path,
        *,
        partition_name: str,
        algorithm: str,
        key_path: Path,
        salt: str,
        rollback_index: int,
        flags: int = 0,
        props: tuple[tuple[str, str], ...] = (),
    ) -> AvbToolResult:
        """Run avbtool.py add_hash_footer."""
        ...

    def add_hashtree_footer(
        self,
        image_path: Path,
        output_path: Path,
        *,
        partition_name: str,
        algorithm: str,
        key_path: Path,
        salt: str,
        rollback_index: int,
        data_block_size: int = 4096,
        hash_block_size: int = 4096,
        flags: int = 0,
        props: tuple[tuple[str, str], ...] = (),
    ) -> AvbToolResult:
        """Run avbtool.py add_hashtree_footer."""
        ...

    def make_vbmeta_image(
        self,
        output_path: Path,
        *,
        algorithm: str,
        key_path: Path,
        rollback_index: int,
        include_descriptors: tuple[Path, ...] = (),
        chain_partitions: tuple[str, ...] = (),
        flags: int = 0,
        props: tuple[tuple[str, str], ...] = (),
    ) -> AvbToolResult:
        """Run avbtool.py make_vbmeta_image."""
        ...

    def extract_public_key(self, key_path: Path, output_path: Path) -> AvbToolResult:
        """Run avbtool.py extract_public_key."""
        ...


class ProgressEvent:
    """Base class for progress events emitted during long operations."""

    pass


@dataclass(frozen=True)
class StepStarted(ProgressEvent):
    step_index: int
    step_total: int
    partition_name: str
    operation: str


@dataclass(frozen=True)
class StepCompleted(ProgressEvent):
    step_index: int
    step_total: int
    partition_name: str
    success: bool
    error_message: str = ""


@dataclass(frozen=True)
class SigningCompleted(ProgressEvent):
    success_count: int
    fail_count: int
    skip_count: int


class ProgressSink(Protocol):
    """Protocol for receiving progress events."""

    def on_event(self, event: ProgressEvent) -> None: ...


class _NullProgress:
    """Silently drops all progress events."""

    def on_event(self, event: ProgressEvent) -> None:
        pass


NULL_PROGRESS: ProgressSink = _NullProgress()
