"""Navigation router — loads navigation.json and manages route stack."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class NavItem:
    """A single navigation item (action or sub-route)."""

    shortcut: str
    action_id: str | None = None  # set if this is an action
    route_id: str | None = None  # set if this is a sub-route
    label_key: str = ""
    description_key: str = ""


@dataclass
class NavRoute:
    """A navigation route (page)."""

    route_id: str
    title_key: str
    description_key: str
    parent: str | None = None
    items: list[NavItem] = field(default_factory=lambda: [])


class Router:
    """Navigation router backed by navigation.json.

    Maintains a route stack for back navigation.
    """

    def __init__(self, nav_file: Path) -> None:
        self._nav_file = nav_file
        self._routes: dict[str, NavRoute] = {}
        self._actions: dict[str, dict[str, str]] = {}
        self._start_route: str = ""
        self._stack: list[str] = []  # route ID stack

        self._load()

    def _load(self) -> None:
        """Load and parse navigation.json."""
        with open(self._nav_file, encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)

        self._start_route = data.get("start_route", "")

        # Load routes
        for route_id, route_data in data.get("routes", {}).items():
            items: list[NavItem] = []
            for item_data in route_data.get("items", []):
                items.append(
                    NavItem(
                        shortcut=item_data.get("shortcut", ""),
                        action_id=item_data.get("action"),
                        route_id=item_data.get("route"),
                        label_key="",
                        description_key="",
                    )
                )
            self._routes[route_id] = NavRoute(
                route_id=route_id,
                title_key=route_data.get("title_key", ""),
                description_key=route_data.get("description_key", ""),
                parent=route_data.get("parent"),
                items=items,
            )

        # Load action metadata
        self._actions = data.get("actions", {})

        # Resolve label/description keys for items
        for route in self._routes.values():
            for item in route.items:
                action_id = item.action_id or ""
                if action_id in self._actions:
                    item.label_key = self._actions[action_id].get("label_key", "")
                    item.description_key = self._actions[action_id].get("description_key", "")

    def validate(self) -> list[str]:
        """Validate navigation integrity. Returns list of error messages."""
        errors: list[str] = []
        all_action_ids = set(self._actions.keys())
        all_route_ids = set(self._routes.keys())

        if self._start_route not in all_route_ids:
            errors.append(f"start_route {self._start_route!r} not found in routes")

        for route_id, route in self._routes.items():
            for item in route.items:
                if item.action_id and item.action_id not in all_action_ids:
                    errors.append(f"Route {route_id}: action {item.action_id!r} not in actions")
                if item.route_id and item.route_id not in all_route_ids:
                    errors.append(f"Route {route_id}: route {item.route_id!r} not in routes")

        return errors

    def start(self) -> str:
        """Navigate to the start route and return its ID."""
        self._stack = [self._start_route]
        return self._start_route

    def current_route(self) -> NavRoute | None:
        """Return the current route, or None if stack is empty."""
        if not self._stack:
            return None
        return self._routes.get(self._stack[-1])

    def push(self, route_id: str) -> bool:
        """Push a route onto the stack. Returns False if route not found."""
        if route_id not in self._routes:
            return False
        self._stack.append(route_id)
        return True

    def pop(self) -> bool:
        """Pop the current route. Returns False if at root."""
        if len(self._stack) <= 1:
            return False
        self._stack.pop()
        return True

    def is_root(self) -> bool:
        """True if at the start route."""
        return len(self._stack) == 1

    def get_action_label(self, action_id: str) -> str:
        """Get the label key for an action."""
        return self._actions.get(action_id, {}).get("label_key", action_id)

    def get_action_description(self, action_id: str) -> str:
        """Get the description key for an action."""
        return self._actions.get(action_id, {}).get("description_key", "")
