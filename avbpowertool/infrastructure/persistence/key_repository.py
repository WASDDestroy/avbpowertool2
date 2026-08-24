"""Key repository — manage key store and manifest.json for a profile."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from avbpowertool.domain.errors import ConfigError

logger = logging.getLogger(__name__)


class KeyRepository:
    """Manage keys/manifest.json and key files for a single profile."""

    def __init__(self, key_dir: Path) -> None:
        self._key_dir = key_dir

    def load_manifest(self) -> dict[str, dict[str, str]]:
        """Load the key manifest. Returns empty dict if not found."""
        manifest_path = self._manifest_path()
        if not manifest_path.exists():
            return {}
        try:
            with open(manifest_path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {}
            return data  # type: ignore[return-value]
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read key manifest: %s", exc)
            return {}

    def save_manifest(self, manifest: dict[str, dict[str, str]]) -> None:
        """Save the key manifest to disk."""
        self._key_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = self._manifest_path()
        manifest_path.write_bytes(
            json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
        )
        logger.info("Saved key manifest with %d entries", len(manifest))

    def resolve_key_path(self, key_id: str) -> Path:
        """Resolve the private key file path for a key_id.

        Raises ConfigError if not found.
        """
        manifest = self.load_manifest()
        entry = manifest.get(key_id)
        if entry is None:
            raise ConfigError(
                f"Key {key_id!r} not found in manifest",
                error_code="config.key_missing",
            )
        private_key = entry.get("private_key")
        if not private_key:
            raise ConfigError(
                f"Key {key_id!r}: no private_key in manifest",
                error_code="config.key_missing",
            )
        key_path = self._key_dir / private_key
        if not key_path.exists():
            raise ConfigError(
                f"Key file not found: {key_path}",
                error_code="config.key_missing",
            )
        return key_path

    def discover_keys(self) -> list[tuple[str, Path]]:
        """Scan key_dir for .pem files. Returns [(filename, path), ...]."""
        if not self._key_dir.exists():
            return []
        return [
            (f.name, f)
            for f in sorted(self._key_dir.iterdir())
            if f.suffix == ".pem" and f.is_file()
        ]

    def _manifest_path(self) -> Path:
        return self._key_dir / "manifest.json"
