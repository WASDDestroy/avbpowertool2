"""Tests for TUI router — navigation loading and traversal."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from avbpowertool.presentation.tui.router import Router


def _write_nav(tmp_path: Path, nav: dict) -> Path:
    nav_file = tmp_path / "navigation.json"
    nav_file.write_text(json.dumps(nav, indent=2), encoding="utf-8")
    return nav_file


def _make_nav() -> dict:
    return {
        "schema_version": 1,
        "start_route": "route:home",
        "routes": {
            "route:home": {
                "title_key": "node.home.name",
                "description_key": "node.home.description",
                "items": [
                    {"action": "action:image.inspect", "shortcut": "R"},
                    {"route": "route:settings", "shortcut": "S"},
                ],
            },
            "route:settings": {
                "title_key": "node.settings.name",
                "description_key": "node.settings.description",
                "parent": "route:home",
                "items": [
                    {"action": "action:settings.view", "shortcut": "V"},
                ],
            },
        },
        "actions": {
            "action:image.inspect": {
                "label_key": "node.read_image_info.name",
                "description_key": "node.read_image_info.description",
            },
            "action:settings.view": {
                "label_key": "settings.action.view",
                "description_key": "",
            },
        },
    }


class TestRouter:
    def test_load_navigation(self, tmp_path: Path) -> None:
        nav_file = _write_nav(tmp_path, _make_nav())
        router = Router(nav_file)
        assert len(router._routes) == 2
        assert len(router._actions) == 2

    def test_start_navigates_to_start_route(self, tmp_path: Path) -> None:
        nav_file = _write_nav(tmp_path, _make_nav())
        router = Router(nav_file)
        route_id = router.start()
        assert route_id == "route:home"

    def test_current_route_returns_route(self, tmp_path: Path) -> None:
        nav_file = _write_nav(tmp_path, _make_nav())
        router = Router(nav_file)
        router.start()
        route = router.current_route()
        assert route is not None
        assert route.route_id == "route:home"
        assert len(route.items) == 2

    def test_push_and_pop(self, tmp_path: Path) -> None:
        nav_file = _write_nav(tmp_path, _make_nav())
        router = Router(nav_file)
        router.start()

        assert router.push("route:settings")
        route = router.current_route()
        assert route is not None
        assert route.route_id == "route:settings"
        assert not router.is_root()

        assert router.pop()
        assert router.is_root()

    def test_pop_root_returns_false(self, tmp_path: Path) -> None:
        nav_file = _write_nav(tmp_path, _make_nav())
        router = Router(nav_file)
        router.start()
        assert not router.pop()

    def test_push_nonexistent_returns_false(self, tmp_path: Path) -> None:
        nav_file = _write_nav(tmp_path, _make_nav())
        router = Router(nav_file)
        router.start()
        assert not router.push("route:nonexistent")

    def test_validate_passes(self, tmp_path: Path) -> None:
        nav_file = _write_nav(tmp_path, _make_nav())
        router = Router(nav_file)
        errors = router.validate()
        assert len(errors) == 0

    def test_validate_catches_missing_action(self, tmp_path: Path) -> None:
        nav = _make_nav()
        nav["routes"]["route:home"]["items"].append(
            {"action": "action:nonexistent", "shortcut": "X"}
        )
        nav_file = _write_nav(tmp_path, nav)
        router = Router(nav_file)
        errors = router.validate()
        assert any("nonexistent" in e for e in errors)

    def test_validate_catches_missing_route(self, tmp_path: Path) -> None:
        nav = _make_nav()
        nav["routes"]["route:home"]["items"].append({"route": "route:nonexistent", "shortcut": "X"})
        nav_file = _write_nav(tmp_path, nav)
        router = Router(nav_file)
        errors = router.validate()
        assert any("nonexistent" in e for e in errors)

    def test_get_action_label(self, tmp_path: Path) -> None:
        nav_file = _write_nav(tmp_path, _make_nav())
        router = Router(nav_file)
        assert router.get_action_label("action:image.inspect") == "node.read_image_info.name"
        assert router.get_action_label("unknown") == "unknown"


class TestRouterAuditTrail:
    def test_navigation_trail_records_steps(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """start/push/pop emit the tui nav.* audit trail at DEBUG."""
        import logging

        from avbpowertool.presentation import audit

        nav_file = _write_nav(tmp_path, _make_nav())
        router = Router(nav_file)

        with caplog.at_level(logging.DEBUG, logger=audit.AUDIT_LOGGER_NAME):
            router.start()
            router.push("route:settings")
            router.pop()

        messages = [r.getMessage() for r in caplog.records]
        assert "tui nav.enter: route:home (start)" in messages
        assert "tui nav.enter: route:settings (depth 2)" in messages
        assert "tui nav.back: from route:settings to route:home" in messages

    def test_push_unknown_route_is_audited(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        from avbpowertool.presentation import audit

        nav_file = _write_nav(tmp_path, _make_nav())
        router = Router(nav_file)
        router.start()

        with caplog.at_level(logging.DEBUG, logger=audit.AUDIT_LOGGER_NAME):
            assert not router.push("route:nonexistent")

        assert any(
            "tui nav.push_failed: route:nonexistent" in r.getMessage() for r in caplog.records
        )
