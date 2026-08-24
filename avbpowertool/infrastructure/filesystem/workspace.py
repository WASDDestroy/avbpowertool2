"""Immutable workspace layout resolved once at startup.

Every path used by the application flows through a WorkspacePaths
instance.  Business logic never calls os.getcwd() or constructs
paths relative to an implicit working directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from avbpowertool.domain.errors import WorkspaceError


@dataclass(frozen=True)
class WorkspacePaths:
    """Canonical filesystem layout for an AVB Power Tool project."""

    root: Path  # project root
    profiles: Path  # profiles/
    logs: Path  # Logs/
    staging: Path  # .avbpowertool-staging/
    avbtool_script: Path  # avbtool.py (vendored AOSP)

    @classmethod
    def discover(cls, root: str | Path | None = None) -> WorkspacePaths:
        """Resolve the project root and build all sub-paths.

        If *root* is not given the current working directory is used.
        """
        root_path = Path(root).resolve() if root is not None else Path.cwd().resolve()

        if not root_path.is_dir():
            raise WorkspaceError(
                f"Project root does not exist: {root_path}",
                error_code="workspace.root_not_found",
            )

        return cls(
            root=root_path,
            profiles=root_path / "profiles",
            logs=root_path / "Logs",
            staging=root_path / ".avbpowertool-staging",
            avbtool_script=root_path / "avbtool.py",
        )

    def resolve_profile_dir(self, profile_id: str) -> Path:
        """Return the directory for a given profile."""
        return self.profiles / profile_id

    def resolve_key_dir(self, profile_id: str) -> Path:
        """Return the key store directory for a given profile."""
        return self.profiles / profile_id / "keys"

    def resolve_image_path(self, image_file: str, profile_id: str) -> Path:
        """Resolve an image file path under a profile's image directory.

        Automatically appends .img when missing.
        Raises WorkspaceError if the resolved path escapes the profile dir.
        """
        if not image_file.endswith(".img"):
            image_file += ".img"
        profile_dir = self.resolve_profile_dir(profile_id)
        path = (profile_dir / image_file).resolve()
        # Safety: ensure the resolved path stays inside the profile dir
        try:
            path.relative_to(profile_dir.resolve())
        except ValueError as exc:
            raise WorkspaceError(
                f"Image path escapes profile directory: {path}",
                error_code="workspace.path_escape",
            ) from exc
        return path

    def ensure_dirs(self) -> None:
        """Create runtime directories that must exist."""
        self.profiles.mkdir(parents=True, exist_ok=True)
        self.logs.mkdir(parents=True, exist_ok=True)
        self.staging.mkdir(parents=True, exist_ok=True)
