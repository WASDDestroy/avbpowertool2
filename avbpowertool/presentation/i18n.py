"""i18n initialization — gettext setup for AVBPowerTool."""

from __future__ import annotations

import gettext
from pathlib import Path

_initialized = False
_t: gettext.NullTranslations | None = None


def init_i18n(language: str = "en", locale_dir: Path | None = None) -> None:
    """Initialize gettext for the given language.

    Args:
        language: Language code (e.g. 'en', 'zh').
        locale_dir: Directory containing locale/ subdirectories.
    """
    global _t, _initialized

    if locale_dir is None:
        # Default: avbpowertool/locale/
        locale_dir = Path(__file__).parent.parent / "locale"

    try:
        _t = gettext.translation(
            "avbpowertool",
            localedir=str(locale_dir),
            languages=[language],
            fallback=True,
        )
    except FileNotFoundError:
        _t = gettext.NullTranslations()

    _initialized = True


def _(message: str) -> str:
    """Translate a message. Returns the message itself if not initialized."""
    if _t is None:
        return message
    return _t.gettext(message)
