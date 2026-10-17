"""Plugin manifest domain model.

A plugin is a directory under ``<workspace>/plugins/`` holding a manifest
(``avbpowertool_plugin_config.xml``) plus an entry script.  The manifest
carries the plugin's identity, its localized names/descriptions and the
entry file name; the localization lives *inside* the manifest and is
deliberately kept out of gettext (a plugin ships its own translations).

This module is pure: no I/O, no infrastructure imports.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Localized pairs are ``(lang, text)``; ``en`` is the fallback language.
_FALLBACK_LANGUAGE = "en"


@dataclass(frozen=True)
class PluginManifest:
    """A plugin's declared identity, version, and entry point.

    ``names`` / ``descriptions`` keep the document order of the manifest,
    so the first non-empty entry doubles as the last-resort fallback when
    neither the requested language nor ``en`` matches.

    ``version`` is a **monotonically increasing integer** maintained by the
    plugin author: it is what decides whether an install is an upgrade, a
    same-version reinstall, or a refused downgrade.  A manifest without a
    ``<version>`` element is version ``0``, so an unversioned plugin can be
    installed and upgraded from without any special casing.  ``version_name``
    is a free-form human-readable label (``"1.1.0"``, ``"2024-06 beta"``, …)
    and never participates in the comparison.
    """

    plugin_id: str
    entry: str
    version: int = 0
    version_name: str = ""
    names: tuple[tuple[str, str], ...] = ()  # (lang, name)
    descriptions: tuple[tuple[str, str], ...] = ()
    schema_version: int = 1

    def name_for(self, language: str) -> str:
        """Return the display name for *language*.

        Resolution order: exact (case-insensitive) match, then the primary
        subtag of a regional code (``zh_CN`` -> ``zh``), then ``en``, then
        the first non-empty name, then :attr:`plugin_id`.
        """
        return _localized(self.names, language, self.plugin_id)

    def description_for(self, language: str) -> str:
        """Return the description for *language*.

        Same resolution order as :meth:`name_for`, but an empty string is
        returned when the manifest declares no usable description.
        """
        return _localized(self.descriptions, language, "")


def _localized(entries: tuple[tuple[str, str], ...], language: str, fallback: str) -> str:
    """Resolve ``(lang, text)`` *entries* for *language* (see ``name_for``)."""
    # Blank texts are not translations: they must not shadow a real
    # fallback further down the chain.
    values = [(lang.strip().lower(), text) for lang, text in entries if text.strip()]

    for candidate in _language_candidates(language):
        for lang, text in values:
            if lang == candidate:
                return text

    for lang, text in values:
        if lang == _FALLBACK_LANGUAGE:
            return text

    if values:
        return values[0][1]

    return fallback


def _language_candidates(language: str) -> tuple[str, ...]:
    """Return the lookup keys for *language*: ``zh_CN`` -> ``zh_cn``, ``zh``."""
    normalized = (language or "").strip().lower()
    if not normalized:
        return ()

    candidates = [normalized]
    primary = normalized.split("_", 1)[0]
    if primary and primary not in candidates:
        candidates.append(primary)
    return tuple(candidates)
