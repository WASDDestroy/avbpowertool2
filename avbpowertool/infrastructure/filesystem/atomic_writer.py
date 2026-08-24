"""Atomic file writer with staging directory.

Writes files to a temporary staging directory first, then atomically
replaces the target on success. On failure, the target is untouched.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from types import TracebackType
from typing import Self


class AtomicWriter:
    """Context manager for atomic multi-file writes.

    Usage::

        with AtomicWriter(target_dir, staging_base) as writer:
            writer.write("profile.json", data)
            writer.write("keys/manifest.json", manifest_data)
        # On success: all files atomically moved to target_dir
        # On exception: staging cleaned up, target_dir untouched
    """

    def __init__(self, target_dir: Path, staging_base: Path) -> None:
        self._target = target_dir.resolve()
        self._staging_base = staging_base
        self._staging_dir: Path | None = None
        self._files: list[tuple[str, bytes]] = []

    def write(self, relative_path: str, data: bytes) -> None:
        """Queue a file to be written. Path is relative to target_dir."""
        self._files.append((relative_path, data))

    def __enter__(self) -> Self:
        self._staging_dir = Path(tempfile.mkdtemp(prefix=".avbpt-atomic-", dir=self._staging_base))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            # Failure: clean up staging
            self._cleanup_staging()
            return

        # Success: write files to staging, then atomically replace
        assert self._staging_dir is not None, "staging_dir must be set in __enter__"
        staging_dir = self._staging_dir
        try:
            for rel_path, data in self._files:
                staged = staging_dir / rel_path
                staged.parent.mkdir(parents=True, exist_ok=True)
                staged.write_bytes(data)

            # Atomic replace: move staging contents to target
            self._target.mkdir(parents=True, exist_ok=True)
            for rel_path, _data in self._files:
                staged = staging_dir / rel_path
                dest = self._target / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                _atomic_move(staged, dest)
        except Exception:
            # If move fails, clean up staging
            self._cleanup_staging()
            raise
        finally:
            self._cleanup_staging()

    def _cleanup_staging(self) -> None:
        if self._staging_dir is not None and self._staging_dir.exists():
            shutil.rmtree(self._staging_dir, ignore_errors=True)
            self._staging_dir = None


def _atomic_move(src: Path, dest: Path) -> None:
    """Atomically move src to dest. Handles cross-device moves."""
    try:
        os.replace(str(src), str(dest))
    except OSError:
        # Cross-device: copy + delete fallback
        shutil.copy2(str(src), str(dest))
        src.unlink(missing_ok=True)
