"""Wiring tests: the TUI exposes the plugins page end to end.

The view's behaviour is covered by ``tests/unit/test_plugins_view.py``;
what is pinned here is the navigation entry, the action metadata, the
dispatch table in ``app.py``, and the translations of the new msgids.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from avbpowertool.presentation.i18n import _, check_l10n, get_current_language, init_i18n

#: Every msgid this page introduces (navigation label + view strings).
NEW_MSGIDS = (
    "node.plugins.name",
    "node.plugins.description",
    "plugin.title",
    "plugin.none",
    "plugin.none_hint",
    "plugin.select",
    "plugin.confirm_run",
    "plugin.run_title",
    "plugin.exit_code",
    "plugin.run_failed",
    "plugin.interrupted",
    "plugin.manifest_issues",
)


class TestPluginsTuiWiring:
    """The TUI must expose the plugins action end to end."""

    def _nav_file(self) -> Path:
        return (
            Path(__file__).parent.parent.parent / "avbpowertool" / "resources" / "navigation.json"
        )

    def test_misc_route_has_plugins_action(self) -> None:
        from avbpowertool.presentation.tui.router import Router

        router = Router(self._nav_file())
        misc_route = router.get_route("route:misc")
        assert misc_route is not None
        actions = [item.action_id for item in misc_route.items]
        assert "action:plugin.manage" in actions
        # shortcut 'P' must not collide with the existing misc shortcuts
        shortcuts = [item.shortcut for item in misc_route.items]
        assert len(shortcuts) == len(set(shortcuts))
        assert "P" in shortcuts
        assert "action:plugin.manage" in router._actions

    def test_menu_label_keys_resolve(self) -> None:
        """The menu renders ``_(label_key)``, so the keys must have translations."""
        from avbpowertool.presentation.tui.router import Router

        router = Router(self._nav_file())
        misc_route = router.get_route("route:misc")
        assert misc_route is not None
        item = next(i for i in misc_route.items if i.action_id == "action:plugin.manage")
        assert item.label_key == "node.plugins.name"
        assert item.description_key == "node.plugins.description"
        for language in ("en", "zh"):
            try:
                init_i18n(language)
                assert _(item.label_key) != item.label_key
                assert _(item.description_key) != item.description_key
            finally:
                init_i18n("en")

    def test_plugins_view_exposes_handler(self) -> None:
        from avbpowertool.presentation.tui.views import plugins as plugins_view

        assert callable(plugins_view.show)

    def test_dispatch_reaches_the_plugins_view(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The dispatch table must actually call the view (not just mention it)."""
        from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
        from avbpowertool.presentation.tui import app as tui_app
        from avbpowertool.presentation.tui.views import plugins as plugins_view

        calls: list[tuple[object, object, object]] = []
        monkeypatch.setattr(
            plugins_view, "show", lambda stdscr, ws, avb: calls.append((stdscr, ws, avb))
        )

        app = tui_app.App(WorkspacePaths.discover(tmp_path))
        marker = object()
        app._dispatch_action(marker, "action:plugin.manage")  # type: ignore[arg-type]

        assert len(calls) == 1
        assert calls[0][0] is marker

    def test_app_view_map_includes_handler(self) -> None:
        """The production app must dispatch the new action to its handler."""
        from avbpowertool.presentation.tui import app as tui_app

        source = inspect.getsource(tui_app.App._dispatch_action)
        assert "action:plugin.manage" in source
        assert "plugins.show" in source


class TestPluginsI18n:
    """The new msgids must be translated, not just present."""

    def test_zh_catalog_has_real_translations(self) -> None:
        try:
            init_i18n("zh")
            assert get_current_language() == "zh"
            for msgid in NEW_MSGIDS:
                assert _(msgid) != msgid, f"{msgid} has no Chinese translation"
            assert _("plugin.title") == "插件"
            assert _("plugin.exit_code", code=3) == "退出码：3"
        finally:
            init_i18n("en")

    def test_en_catalog_has_real_translations(self) -> None:
        try:
            init_i18n("en")
            for msgid in NEW_MSGIDS:
                assert _(msgid) != msgid, f"{msgid} has no English translation"
        finally:
            init_i18n("en")

    def test_zh_catalog_is_not_missing_the_new_msgids(self) -> None:
        try:
            init_i18n("zh")
            missing = check_l10n("zh")
        finally:
            init_i18n("en")
        assert missing == {}
        assert [msgid for msgid in NEW_MSGIDS if msgid in missing] == []
