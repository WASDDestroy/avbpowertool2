"""Stable action identifiers for AVB Power Tool.

Action IDs use lowercase dot-separated names and never change once
released.  CLI dispatch, navigation, and future TUI binding all
reference these constants — never display strings.
"""

from __future__ import annotations

from enum import StrEnum


class ActionId(StrEnum):
    """Stable, machine-readable action identifiers."""

    IMAGE_INSPECT = "image.inspect"
    IMAGE_SIGN = "image.sign"
    CONFIG_SHOW = "config.show"
    CONFIG_VALIDATE = "config.validate"
    CONFIG_IMPORT = "config.import"
    CONFIG_IMPORT_LEGACY = "config.import_legacy"
    CONFIG_EXPORT = "config.export"
    CONFIG_ACTIVATE = "config.activate"
    CONFIG_LIST = "config.list"
    CONFIG_MIGRATE = "config.migrate"
    CONFIG_EDIT = "config.edit"
    SETTINGS_VIEW = "settings.view"
    SETTINGS_CHECK_L10N = "settings.check_l10n"
    VIEW_CURRENT_CONFIG = "view_current_config"
