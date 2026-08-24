"""i18n initialization — gettext setup for AVBPowerTool.

Auto-compiles .po to .mo on first run if .mo files are missing.
"""

from __future__ import annotations

import gettext
import logging
import struct
from pathlib import Path

logger = logging.getLogger(__name__)

_initialized = False
_t: gettext.NullTranslations | None = None
_current_language: str = "en"
_locale_dir: Path | None = None


def get_current_language() -> str:
    """Return the currently active language code."""
    return _current_language


def init_i18n(language: str = "en", locale_dir: Path | None = None) -> None:
    """Initialize gettext for the given language.

    Auto-compiles .po -> .mo if the .mo file is missing.

    Args:
        language: Language code (e.g. 'en', 'zh').
        locale_dir: Directory containing locale/ subdirectories.
    """
    global _t, _initialized, _current_language, _locale_dir

    if locale_dir is None:
        locale_dir = Path(__file__).parent.parent / "locale"

    _current_language = language
    _locale_dir = locale_dir

    # Ensure .mo files exist
    _ensure_compiled(locale_dir, language)
    # Also ensure default (en) .mo exists for fallback comparison
    if language != "en":
        _ensure_compiled(locale_dir, "en")

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


def _(message: str, **kwargs: object) -> str:
    """Translate a message. Supports str.format() kwargs.

    Example: _("settings.saved", key="Language", old="en", new="zh")
    """
    translated = message if _t is None else _t.gettext(message)
    if kwargs:
        try:
            return translated.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return translated
    return translated


def _ensure_compiled(locale_dir: Path, language: str) -> None:
    """Compile .po -> .mo if the .mo file doesn't exist."""
    po_path = locale_dir / language / "LC_MESSAGES" / "avbpowertool.po"
    mo_path = locale_dir / language / "LC_MESSAGES" / "avbpowertool.mo"

    if not po_path.exists():
        return

    if mo_path.exists() and mo_path.stat().st_mtime >= po_path.stat().st_mtime:
        return  # .mo is up to date

    try:
        _compile_po_to_mo(po_path, mo_path)
        logger.info("Compiled %s -> %s", po_path.name, mo_path.name)
    except Exception as exc:
        logger.warning("Failed to compile %s: %s", po_path, exc)


def _compile_po_to_mo(po_path: Path, mo_path: Path) -> None:
    """Minimal .po to .mo compiler.

    Handles msgid/msgstr pairs. Does NOT handle plural forms,
    contexts, or multiline entries with embedded newlines beyond
    basic concatenation.
    """
    translations: dict[str, str] = {}
    current_msgid_parts: list[str] = []
    current_msgstr_parts: list[str] = []
    in_msgid = False
    in_msgstr = False

    with open(po_path, encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n\r")

            # Skip empty lines and comments
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                # Flush pending entry
                if current_msgid_parts and current_msgstr_parts:
                    msgid = "".join(current_msgid_parts)
                    msgstr = "".join(current_msgstr_parts)
                    if msgid and msgstr:
                        translations[msgid] = msgstr
                current_msgid_parts = []
                current_msgstr_parts = []
                in_msgid = False
                in_msgstr = False
                continue

            if stripped.startswith("msgid "):
                # Flush previous
                if current_msgid_parts and current_msgstr_parts:
                    msgid = "".join(current_msgid_parts)
                    msgstr = "".join(current_msgstr_parts)
                    if msgid and msgstr:
                        translations[msgid] = msgstr
                current_msgid_parts = []
                current_msgstr_parts = []
                in_msgid = True
                in_msgstr = False
                # Extract the quoted string
                value = _extract_quoted(stripped[6:])
                if value is not None:
                    current_msgid_parts.append(value)
            elif stripped.startswith("msgstr "):
                in_msgid = False
                in_msgstr = True
                value = _extract_quoted(stripped[7:])
                if value is not None:
                    current_msgstr_parts.append(value)
            elif stripped.startswith('"'):
                # Continuation line
                value = _extract_quoted(stripped)
                if value is not None:
                    if in_msgid:
                        current_msgid_parts.append(value)
                    elif in_msgstr:
                        current_msgstr_parts.append(value)

    # Flush last entry
    if current_msgid_parts and current_msgstr_parts:
        msgid = "".join(current_msgid_parts)
        msgstr = "".join(current_msgstr_parts)
        if msgid and msgstr:
            translations[msgid] = msgstr

    # Write .mo file
    _write_mo(translations, mo_path)


def _extract_quoted(s: str) -> str | None:
    """Extract content from a quoted .po string like '"hello world"'."""
    s = s.strip()
    if not s.startswith('"') or not s.endswith('"'):
        return None
    inner = s[1:-1]
    # Unescape common sequences
    inner = inner.replace('\\"', '"')
    inner = inner.replace("\\n", "\n")
    inner = inner.replace("\\t", "\t")
    inner = inner.replace("\\\\", "\\")
    return inner


def _write_mo(translations: dict[str, str], mo_path: Path) -> None:
    """Write a .mo file from a dict of msgid -> msgstr.

    .mo binary format:
      - Header: magic, revision, nstrings, offset_orig, offset_trans, size_hash, offset_hash
      - Sorted offset table for originals
      - Sorted offset table for translations
      - Original strings (null-terminated)
      - Translation strings (null-terminated)
    """
    # Sort by msgid
    keys = sorted(translations.keys())
    nstrings = len(keys)

    # Encode strings
    encoded_keys = [k.encode("utf-8") + b"\0" for k in keys]
    encoded_vals = [translations[k].encode("utf-8") + b"\0" for k in keys]

    # Calculate offsets
    # Header: 7 * 4 = 28 bytes
    # Offset tables: 2 * nstrings * 8 bytes each
    keystart = 28 + nstrings * 16
    valstart = keystart + sum(len(e) for e in encoded_keys)

    # Build output
    out = bytearray()

    # Header
    out += struct.pack("Iiiiiii", 0x950412DE, 0, nstrings, 28, 28 + nstrings * 8, 0, 0)

    # Key offset table
    offset = keystart
    for e in encoded_keys:
        out += struct.pack("ii", len(e) - 1, offset)  # -1 for trailing null
        offset += len(e)

    # Value offset table
    offset = valstart
    for e in encoded_vals:
        out += struct.pack("ii", len(e) - 1, offset)
        offset += len(e)

    # Key data
    for e in encoded_keys:
        out += e

    # Value data
    for e in encoded_vals:
        out += e

    mo_path.parent.mkdir(parents=True, exist_ok=True)
    mo_path.write_bytes(bytes(out))


def check_l10n(language: str) -> dict[str, str]:
    """Check for missing translations in the given language.

    Returns a dict of {msgid: default_msgstr} for entries that exist in
    the default (en) .po file but are missing from the target language.
    """
    if _locale_dir is None:
        return {}

    default_strings = _parse_po_keys(_locale_dir / "en" / "LC_MESSAGES" / "avbpowertool.po")
    if language == "en":
        return {}

    target_po = _locale_dir / language / "LC_MESSAGES" / "avbpowertool.po"
    if not target_po.exists():
        return dict(default_strings)

    target_strings = _parse_po_keys(target_po)
    missing: dict[str, str] = {}
    for key, default_val in default_strings.items():
        if key not in target_strings:
            missing[key] = default_val
    return missing


def _parse_po_keys(po_path: Path) -> dict[str, str]:
    """Parse a .po file and return {msgid: msgstr} for non-empty entries."""
    if not po_path.exists():
        return {}

    result: dict[str, str] = {}
    current_msgid_parts: list[str] = []
    current_msgstr_parts: list[str] = []
    in_msgid = False
    in_msgstr = False

    with open(po_path, encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n\r")
            stripped = line.strip()

            if not stripped or stripped.startswith("#"):
                if current_msgid_parts and current_msgstr_parts:
                    msgid = "".join(current_msgid_parts)
                    msgstr = "".join(current_msgstr_parts)
                    if msgid and msgstr:
                        result[msgid] = msgstr
                current_msgid_parts = []
                current_msgstr_parts = []
                in_msgid = False
                in_msgstr = False
                continue

            if stripped.startswith("msgid "):
                if current_msgid_parts and current_msgstr_parts:
                    msgid = "".join(current_msgid_parts)
                    msgstr = "".join(current_msgstr_parts)
                    if msgid and msgstr:
                        result[msgid] = msgstr
                current_msgid_parts = []
                current_msgstr_parts = []
                in_msgid = True
                in_msgstr = False
                value = _extract_quoted(stripped[6:])
                if value is not None:
                    current_msgid_parts.append(value)
            elif stripped.startswith("msgstr "):
                in_msgid = False
                in_msgstr = True
                value = _extract_quoted(stripped[7:])
                if value is not None:
                    current_msgstr_parts.append(value)
            elif stripped.startswith('"'):
                value = _extract_quoted(stripped)
                if value is not None:
                    if in_msgid:
                        current_msgid_parts.append(value)
                    elif in_msgstr:
                        current_msgstr_parts.append(value)

    if current_msgid_parts and current_msgstr_parts:
        msgid = "".join(current_msgid_parts)
        msgstr = "".join(current_msgstr_parts)
        if msgid and msgstr:
            result[msgid] = msgstr

    return result
