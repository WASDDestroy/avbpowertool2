"""Regression: bootstrap must apply the persisted language setting.

The TUI settings view saves the chosen language to settings.json, but the
TUI was launched via ``bootstrap()`` which always defaulted to English.
These tests pin the resolution order: explicit ``language`` argument wins,
otherwise the persisted setting (default 'en') is used.
"""

from __future__ import annotations

import json
from pathlib import Path

from avbpowertool.bootstrap import bootstrap
from avbpowertool.presentation.i18n import _, get_current_language, init_i18n


def _write_settings(root: Path, language: str) -> None:
    (root / "settings.json").write_text(
        json.dumps({"language": language, "log_level": "INFO"}, indent=2),
        encoding="utf-8",
    )


class TestBootstrapI18n:
    def test_persisted_zh_setting_is_applied(self, tmp_path: Path) -> None:
        _write_settings(tmp_path, "zh")
        try:
            ws = bootstrap(root=tmp_path)
            assert ws.root == tmp_path.resolve()
            assert get_current_language() == "zh"
            # Verify the actual catalog is active, not just the flag.
            assert _("Exit") == "退出"
        finally:
            init_i18n("en")

    def test_explicit_language_overrides_setting(self, tmp_path: Path) -> None:
        _write_settings(tmp_path, "zh")
        try:
            bootstrap(root=tmp_path, language="en")
            assert get_current_language() == "en"
        finally:
            init_i18n("en")

    def test_missing_settings_defaults_to_en(self, tmp_path: Path) -> None:
        try:
            bootstrap(root=tmp_path)
            assert get_current_language() == "en"
        finally:
            init_i18n("en")
