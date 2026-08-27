"""TUI application — curses main loop with navigation router."""

from __future__ import annotations

import contextlib
import curses
import locale
import logging
from pathlib import Path

from avbpowertool.application.services.manage_profiles import (
    ProfileActivateUseCase,
    ProfileDeleteUseCase,
    ProfileListUseCase,
)
from avbpowertool.infrastructure.avbtool.runner import SubprocessAvbTool
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.presentation.i18n import _
from avbpowertool.presentation.tui.router import Router
from avbpowertool.presentation.tui.widgets import (
    SelectorWidget,
    message_screen,
)

logger = logging.getLogger(__name__)


class App:
    """TUI application with curses."""

    def __init__(self, workspace: WorkspacePaths) -> None:
        self._ws = workspace
        nav_file = workspace.root / "avbpowertool" / "resources" / "navigation.json"
        if not nav_file.exists():
            # Fallback: look relative to the package
            import avbpowertool.resources

            nav_file = Path(avbpowertool.resources.__file__).parent / "navigation.json"
        self._router = Router(nav_file)
        self._avb = SubprocessAvbTool(workspace.avbtool_script)

    def run(self) -> None:
        """Run the TUI application."""
        # curses needs a real locale to count multibyte (CJK) columns
        # correctly; without it ncurses falls back to per-byte accounting.
        with contextlib.suppress(Exception):
            locale.setlocale(locale.LC_ALL, "")
        curses.wrapper(self._main_loop)

    def _main_loop(self, stdscr: curses.window) -> None:
        """Main curses loop."""
        curses.use_default_colors()
        self._router.start()

        while True:
            route = self._router.current_route()
            if route is None:
                break

            # Build menu items
            items: list[str] = []
            action_ids: list[str] = []

            for nav_item in route.items:
                if nav_item.action_id:
                    label = _(nav_item.label_key) if nav_item.label_key else nav_item.action_id
                    items.append(f"[{nav_item.shortcut}] {label}")
                    action_ids.append(nav_item.action_id)
                elif nav_item.route_id:
                    sub_route = self._router.get_route(nav_item.route_id)
                    label = (
                        _(sub_route.title_key)
                        if sub_route and sub_route.title_key
                        else nav_item.route_id
                    )
                    items.append(f"[{nav_item.shortcut}] {label} >")
                    action_ids.append(f"route:{nav_item.route_id}")

            # Add back/exit
            if self._router.is_root():
                items.append(f"[E] {_('Exit')}")
                action_ids.append("system:exit")
            else:
                items.append(f"[B] {_('Back')}")
                action_ids.append("system:back")

            # Show selector
            title = _(route.title_key) if route.title_key else route.route_id
            sel = SelectorWidget(title, items)
            result = sel.run(stdscr)

            if not result:
                # Esc pressed
                if not self._router.pop():
                    break
                continue

            idx = result[0]
            if idx >= len(action_ids):
                continue

            chosen = action_ids[idx]

            if chosen == "system:exit":
                break
            elif chosen == "system:back":
                if not self._router.pop():
                    break
            elif chosen.startswith("route:"):
                route_id = chosen[6:]
                self._router.push(route_id)
            else:
                # Dispatch action
                self._dispatch_action(stdscr, chosen)

    def _dispatch_action(self, stdscr: curses.window, action_id: str) -> None:
        """Dispatch an action to the appropriate view handler."""
        from avbpowertool.presentation.tui.views import (
            create_config,
            display_avb_info,
            export_config,
            import_config,
            manage_keys,
            read_image_info,
            settings,
            sign_images,
        )

        view_map = {
            "action:image.read_info": read_image_info.show,
            "action:image.sign": sign_images.show,
            "action:config.create": create_config.show,
            "action:config.import": import_config.show,
            "action:config.export": export_config.show,
            "action:view_current_config": display_avb_info.show,
            "action:config.library": self._show_config_library,
            "action:key.manage": manage_keys.show,
            "action:settings.edit": settings.show_edit,
            "action:settings.view": settings.show_view,
            "action:settings.import_legacy": settings.show_import_legacy,
            "action:settings.check_l10n": settings.show_check_l10n,
        }

        handler = view_map.get(action_id)
        if handler is None:
            message_screen(
                stdscr, "Not Implemented", [f"Action {action_id} is not yet implemented."]
            )
            return

        try:
            handler(stdscr, self._ws, self._avb)
        except Exception as exc:
            logger.exception("Error in action %s", action_id)
            message_screen(stdscr, "Error", [str(exc)])

    def _show_config_library(self, stdscr: curses.window, ws: WorkspacePaths, avb: object) -> None:
        """Config library management view."""
        uc = ProfileListUseCase(ws)
        from avbpowertool.application.commands import ProfileListRequest

        result = uc.execute(ProfileListRequest())
        if not result.profiles:
            message_screen(stdscr, "Config Library", ["No profiles found."])
            return

        items = [
            f"{p.profile_id}: {p.name} {'(active)' if p.is_active else ''}" for p in result.profiles
        ]
        sel = SelectorWidget("Config Library", items)
        choice = sel.run(stdscr)
        if not choice:
            return

        profile = result.profiles[choice[0]]
        actions = ["Activate", "Delete", "Back"]
        action_sel = SelectorWidget(f"Options for {profile.profile_id}", actions)
        action_choice = action_sel.run(stdscr)
        if action_choice and action_choice[0] == 0:
            activate_uc = ProfileActivateUseCase(ws)
            from avbpowertool.application.commands import ProfileActivateRequest

            activate_result = activate_uc.execute(
                ProfileActivateRequest(profile_id=profile.profile_id)
            )
            if activate_result.issues:
                message_screen(stdscr, "Error", [i.message for i in activate_result.issues])
            else:
                message_screen(stdscr, "Success", [f"Activated: {profile.profile_id}"])
        elif action_choice and action_choice[0] == 1:
            from avbpowertool.presentation.tui.widgets import confirm_dialog

            if not confirm_dialog(
                stdscr, f"Delete profile '{profile.profile_id}'? This cannot be undone."
            ):
                return
            from avbpowertool.application.commands import ProfileDeleteRequest

            result = ProfileDeleteUseCase(ws).execute(
                ProfileDeleteRequest(profile_id=profile.profile_id)
            )
            if result.issues:
                message_screen(stdscr, "Error", [i.message for i in result.issues])
            else:
                message_screen(stdscr, "Success", [f"Deleted: {profile.profile_id}"])
