"""Profile repository — read/write v2 profiles to disk."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from avbpowertool.domain.errors import ConfigError
from avbpowertool.domain.models import AvbProfile
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.persistence.profile_codec import (
    decode_profile,
    encode_profile,
)

logger = logging.getLogger(__name__)


class ProfileRepository:
    """Read/write AvbProfile instances on disk."""

    def __init__(self, workspace: WorkspacePaths) -> None:
        self._ws = workspace

    def load(self, profile_id: str) -> AvbProfile:
        """Load a profile by ID. Raises ConfigError on failure."""
        profile_path = self._profile_json_path(profile_id)
        if not profile_path.exists():
            raise ConfigError(
                f"Profile not found: {profile_id}",
                error_code="config.not_found",
            )
        try:
            with open(profile_path, encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(
                f"Failed to read profile {profile_id!r}: {exc}",
                error_code="config.parse_error",
            ) from exc
        return decode_profile(data)

    def save(self, profile: AvbProfile) -> None:
        """Save a profile to disk (atomic write via staging)."""
        from avbpowertool.infrastructure.filesystem.atomic_writer import AtomicWriter

        profile_dir = self._ws.resolve_profile_dir(profile.id)
        data = encode_profile(profile)
        json_bytes = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")

        with AtomicWriter(profile_dir, self._ws.staging) as writer:
            writer.write("profile.json", json_bytes)
        logger.info("Saved profile %r", profile.id)

    def list_profiles(self) -> tuple[str, ...]:
        """List all profile IDs (directory names under profiles/)."""
        if not self._ws.profiles.exists():
            return ()
        return tuple(
            sorted(
                entry.name
                for entry in self._ws.profiles.iterdir()
                if entry.is_dir() and (entry / "profile.json").exists()
            )
        )

    def delete(self, profile_id: str) -> None:
        """Delete a profile directory."""
        import shutil

        profile_dir = self._ws.resolve_profile_dir(profile_id)
        if not profile_dir.exists():
            raise ConfigError(
                f"Profile not found: {profile_id}",
                error_code="config.not_found",
            )
        shutil.rmtree(profile_dir)
        logger.info("Deleted profile %r", profile_id)

    def activate(self, profile_id: str) -> None:
        """Activate a profile by writing its ID to the active link file."""
        active_path = self._ws.root / ".active-profile"
        active_path.write_text(profile_id, encoding="utf-8")
        logger.info("Activated profile %r", profile_id)

    def get_active_profile_id(self) -> str | None:
        """Return the currently active profile ID, or None."""
        active_path = self._ws.root / ".active-profile"
        if not active_path.exists():
            return None
        try:
            return active_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None

    def _profile_json_path(self, profile_id: str) -> Path:
        return self._ws.resolve_profile_dir(profile_id) / "profile.json"
