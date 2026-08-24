"""Key management view — list, discover, add, remove keys."""

from __future__ import annotations

import curses

from avbpowertool.application.commands import (
    KeyAddRequest,
    KeyDiscoveryRequest,
    KeyListRequest,
    KeyRemoveRequest,
)
from avbpowertool.application.ports import AvbToolPort
from avbpowertool.application.services.manage_keys import (
    KeyAddUseCase,
    KeyDiscoveryUseCase,
    KeyListUseCase,
    KeyRemoveUseCase,
)
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.presentation.i18n import _
from avbpowertool.presentation.tui.widgets import (
    SelectorWidget,
    confirm_dialog,
    input_prompt,
    message_screen,
)


def show(stdscr: object, ws: WorkspacePaths, avb: AvbToolPort) -> None:
    """Key management hub — list, discover, add, remove."""
    stdscr_c: curses.window = stdscr  # type: ignore[assignment]

    while True:
        actions = [
            _("keys.action.list"),
            _("keys.action.discover"),
            _("keys.action.add"),
            _("keys.action.remove"),
        ]
        sel = SelectorWidget(_("keys.management_title"), actions)
        result = sel.run(stdscr_c)
        if not result:
            return

        action_idx = result[0]
        if action_idx == 0:
            _show_key_list(stdscr_c, ws)
        elif action_idx == 1:
            _run_discover(stdscr_c, ws)
        elif action_idx == 2:
            _add_key(stdscr_c, ws)
        elif action_idx == 3:
            _remove_key(stdscr_c, ws)


def _get_active_profile(ws: WorkspacePaths) -> str:
    from avbpowertool.infrastructure.persistence.profile_repository import ProfileRepository

    repo = ProfileRepository(ws)
    return repo.get_active_profile_id() or "current"


def _show_key_list(stdscr: curses.window, ws: WorkspacePaths) -> None:
    """Show all keys in the active profile's key store."""
    profile_id = _get_active_profile(ws)
    uc = KeyListUseCase(ws)
    result = uc.execute(KeyListRequest(profile_id=profile_id))

    lines: list[str] = []

    if result.manifest_entries:
        lines.append(_("keys.list_registered"))
        for key_id, filename in result.manifest_entries:
            lines.append(f"  {key_id} -> {filename}")
        lines.append("")

    if result.pem_files_on_disk:
        lines.append(_("keys.list_unregistered"))
        for filename in result.pem_files_on_disk:
            lines.append(f"  {filename}")
        lines.append("")
        lines.append(_("keys.list_unregistered_hint"))
    elif not result.manifest_entries:
        lines.append(_("keys.list_empty"))

    for iss in result.issues:
        lines.append(f"  [{iss.error_code}] {iss.message}")

    message_screen(stdscr, _("keys.list_title"), lines)


def _run_discover(stdscr: curses.window, ws: WorkspacePaths) -> None:
    """Auto-discover .pem files and rebuild manifest."""
    profile_id = _get_active_profile(ws)

    if not confirm_dialog(stdscr, _("keys.discover_confirm")):
        return

    uc = KeyDiscoveryUseCase(ws)
    result = uc.execute(KeyDiscoveryRequest(profile_id=profile_id))

    lines: list[str] = [_("keys.discover_result", count=result.discovered_count)]
    for key_id, filename in result.manifest_entries:
        lines.append(f"  {key_id} -> {filename}")
    for iss in result.issues:
        lines.append(f"  [{iss.error_code}] {iss.message}")

    message_screen(stdscr, _("keys.discover_title"), lines)


def _add_key(stdscr: curses.window, ws: WorkspacePaths) -> None:
    """Manually add a key entry to the manifest."""
    profile_id = _get_active_profile(ws)

    key_id = input_prompt(stdscr, _("keys.add_key_id"))
    if not key_id or not key_id.strip():
        return

    filename = input_prompt(stdscr, _("keys.add_filename"))
    if not filename or not filename.strip():
        return

    uc = KeyAddUseCase(ws)
    result = uc.execute(
        KeyAddRequest(
            profile_id=profile_id,
            key_id=key_id.strip(),
            private_key_filename=filename.strip(),
        )
    )

    lines: list[str] = []
    if not result.issues:
        lines.append(_("keys.add_success", key_id=result.key_id))
    for iss in result.issues:
        lines.append(f"  [{iss.error_code}] {iss.message}")

    message_screen(stdscr, _("keys.add_title"), lines)


def _remove_key(stdscr: curses.window, ws: WorkspacePaths) -> None:
    """Remove a key entry from the manifest."""
    profile_id = _get_active_profile(ws)

    # Show current manifest entries first
    list_uc = KeyListUseCase(ws)
    list_result = list_uc.execute(KeyListRequest(profile_id=profile_id))

    if not list_result.manifest_entries:
        message_screen(stdscr, _("keys.remove_title"), [_("keys.list_empty")])
        return

    entries = list(list_result.manifest_entries)
    items = [f"{kid} -> {fn}" for kid, fn in entries]
    sel = SelectorWidget(_("keys.select_remove"), items)
    result = sel.run(stdscr)
    if not result:
        return

    key_id = entries[result[0]][0]
    if not confirm_dialog(stdscr, _("keys.remove_confirm", key_id=key_id)):
        return

    remove_uc = KeyRemoveUseCase(ws)
    remove_result = remove_uc.execute(KeyRemoveRequest(profile_id=profile_id, key_id=key_id))

    lines: list[str] = []
    if not remove_result.issues:
        lines.append(_("keys.remove_success", key_id=key_id))
    for iss in remove_result.issues:
        lines.append(f"  [{iss.error_code}] {iss.message}")

    message_screen(stdscr, _("keys.remove_title"), lines)
