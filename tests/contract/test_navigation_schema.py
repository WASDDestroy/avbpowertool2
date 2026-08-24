"""Contract tests for navigation.json schema validation."""

from __future__ import annotations

import json
from pathlib import Path

from avbpowertool.presentation.tui.router import Router


class TestNavigationSchema:
    """Validate the production navigation.json."""

    def _get_nav_file(self) -> Path:
        return Path(__file__).parent.parent.parent / "avbpowertool" / "resources" / "navigation.json"

    def test_navigation_loads(self) -> None:
        router = Router(self._get_nav_file())
        assert len(router._routes) > 0

    def test_navigation_validates_clean(self) -> None:
        router = Router(self._get_nav_file())
        errors = router.validate()
        assert errors == [], f"Navigation errors: {errors}"

    def test_start_route_exists(self) -> None:
        router = Router(self._get_nav_file())
        router.start()
        route = router.current_route()
        assert route is not None

    def test_all_actions_referenced_exist(self) -> None:
        router = Router(self._get_nav_file())
        for route in router._routes.values():
            for item in route.items:
                if item.action_id:
                    assert item.action_id in router._actions, (
                        f"Action {item.action_id} in route {route.route_id} not in actions"
                    )

    def test_all_routes_referenced_exist(self) -> None:
        router = Router(self._get_nav_file())
        for route in router._routes.values():
            for item in route.items:
                if item.route_id:
                    assert item.route_id in router._routes, (
                        f"Route {item.route_id} in route {route.route_id} not in routes"
                    )

    def test_no_orphan_routes(self) -> None:
        """Every route (except start) should be reachable from start via items."""
        router = Router(self._get_nav_file())
        reachable: set[str] = set()
        stack = [router._start_route]

        while stack:
            current = stack.pop()
            if current in reachable:
                continue
            reachable.add(current)
            route = router._routes.get(current)
            if route:
                for item in route.items:
                    if item.route_id:
                        stack.append(item.route_id)

        for route_id in router._routes:
            assert route_id in reachable, f"Route {route_id} is not reachable from start"

    def test_shortcuts_unique_per_route(self) -> None:
        """Shortcuts should be unique within each route."""
        router = Router(self._get_nav_file())
        for route in router._routes.values():
            shortcuts = [item.shortcut for item in route.items if item.shortcut]
            assert len(shortcuts) == len(set(shortcuts)), (
                f"Duplicate shortcuts in route {route.route_id}: {shortcuts}"
            )

    def test_schema_version_present(self) -> None:
        nav_file = self._get_nav_file()
        with open(nav_file, encoding="utf-8") as f:
            data = json.load(f)
        assert "schema_version" in data
        assert isinstance(data["schema_version"], int)
