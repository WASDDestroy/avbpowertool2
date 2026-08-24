"""Tests for AtomicWriter."""

from __future__ import annotations

from pathlib import Path

from avbpowertool.infrastructure.filesystem.atomic_writer import AtomicWriter


class TestAtomicWriter:
    def test_success_writes_files(self, tmp_path: Path) -> None:
        target = tmp_path / "target"
        staging = tmp_path / "staging"
        staging.mkdir()

        with AtomicWriter(target, staging) as writer:
            writer.write("file1.txt", b"hello")
            writer.write("sub/file2.txt", b"world")

        assert (target / "file1.txt").read_bytes() == b"hello"
        assert (target / "sub" / "file2.txt").read_bytes() == b"world"

    def test_failure_leaves_target_untouched(self, tmp_path: Path) -> None:
        target = tmp_path / "target"
        target.mkdir()
        (target / "existing.txt").write_bytes(b"original")
        staging = tmp_path / "staging"
        staging.mkdir()

        try:
            with AtomicWriter(target, staging) as writer:
                writer.write("new.txt", b"data")
                raise ValueError("simulated failure")
        except ValueError:
            pass

        # Original file untouched, new file not written
        assert (target / "existing.txt").read_bytes() == b"original"
        assert not (target / "new.txt").exists()

    def test_staging_cleaned_up_on_success(self, tmp_path: Path) -> None:
        target = tmp_path / "target"
        staging = tmp_path / "staging"
        staging.mkdir()

        with AtomicWriter(target, staging) as writer:
            writer.write("file.txt", b"data")

        # Staging temp dir should be gone
        staging_contents = list(staging.iterdir())
        assert len(staging_contents) == 0

    def test_staging_cleaned_up_on_failure(self, tmp_path: Path) -> None:
        target = tmp_path / "target"
        staging = tmp_path / "staging"
        staging.mkdir()

        try:
            with AtomicWriter(target, staging) as writer:
                writer.write("file.txt", b"data")
                raise RuntimeError("fail")
        except RuntimeError:
            pass

        staging_contents = list(staging.iterdir())
        assert len(staging_contents) == 0

    def test_creates_target_dir(self, tmp_path: Path) -> None:
        target = tmp_path / "new" / "nested" / "target"
        staging = tmp_path / "staging"
        staging.mkdir()

        with AtomicWriter(target, staging) as writer:
            writer.write("file.txt", b"data")

        assert (target / "file.txt").exists()
