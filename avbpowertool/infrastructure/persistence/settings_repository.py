"""Global settings model and persistence."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SETTINGS_FILENAME = "settings.json"

# Available settings with their options
SETTING_DEFS: dict[str, dict[str, Any]] = {
    "language": {
        "type": "choice",
        "label_key": "settings.language",
        "options": {
            "en": "settings.option.language.en",
            "zh": "settings.option.language.zh",
        },
        "default": "en",
    },
    "log_level": {
        "type": "choice",
        "label_key": "settings.log_level",
        "options": {
            "DEBUG": "settings.option.log_level.DEBUG",
            "INFO": "settings.option.log_level.INFO",
            "WARNING": "settings.option.log_level.WARNING",
            "ERROR": "settings.option.log_level.ERROR",
        },
        "default": "INFO",
    },
}


@dataclass(frozen=True)
class Settings:
    """Immutable global settings snapshot."""

    language: str = "en"
    log_level: str = "INFO"

    def get(self, key: str) -> str:
        """Get a setting value by key."""
        return getattr(self, key, "")

    def with_value(self, key: str, value: str) -> Settings:
        """Return a new Settings with one value changed."""
        return Settings(
            **{k: value if k == key else getattr(self, k) for k in self.__dataclass_fields__}
        )


class SettingsRepository:
    """Read/write global settings from settings.json."""

    def __init__(self, root: Path) -> None:
        self._path = root / SETTINGS_FILENAME

    def load(self) -> Settings:
        """Load settings from disk. Returns defaults if file missing."""
        if not self._path.exists():
            return Settings()
        try:
            with open(self._path, encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
            return Settings(
                language=data.get("language", "en"),
                log_level=data.get("log_level", "INFO"),
            )
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.warning("Failed to load settings: %s", exc)
            return Settings()

    def save(self, settings: Settings) -> None:
        """Save settings to disk."""
        data = {
            "language": settings.language,
            "log_level": settings.log_level,
        }
        self._path.write_bytes(json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))
        logger.info("Saved settings to %s", self._path)

    def get_path(self) -> Path:
        return self._path
