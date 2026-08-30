"""Config library view — list, activate, and delete profiles."""

from __future__ import annotations

import curses

from avbpowertool.application.commands import (
    ProfileActivateRequest,
    ProfileDeleteRequest,
    ProfileListRequest,
)
from avbpowertool.application.ports import AvbToolPort
from avbpowertool.application.services.manage_profiles import (
    ProfileActivateUseCase,
    ProfileDeleteUseCase,
    ProfileListUseCase,
)
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.presentation import audit
from avbpowertool.presentation.i18n import _
from avbpowertool.presentation.tui.widgets import (
    SelectorWidget,
    confirm_dialog,
    message_screen,
)

audit_log = audit.audit_logger()


def show(stdscr: object, ws: WorkspacePaths, avb: AvbToolPort) -> None:
    """Config library management view."""
    stdscr_c: curses.window = stdscr  # type: ignore[assignment]
    uc = ProfileListUseCase(ws)

    result = uc.execute(ProfileListRequest())
    if not result.profiles:
        audit_log.debug("tui message: Config Library (empty)")
        message_screen(stdscr_c, _("library.title"), [_("library.no_profiles")])
        return

    items = [
        f"{p.profile_id}: {p.name} {('(' + _('library.active_suffix') + ')') if p.is_active else ''}"
        for p in result.profiles
    ]
    sel = SelectorWidget(_("library.title"), items)
    choice = sel.run(stdscr_c)
    if not choice:
        audit_log.debug("tui select.cancel: Config Library")
        return

    profile = result.profiles[choice[0]]
    audit_log.debug(
        "tui select.choose: Config Library -> %s (profile %s)",
        profile.profile_id,
        profile.profile_id,
    )
    actions = [_("library.action.activate"), _("library.action.delete"), _("Back")]
    action_sel = SelectorWidget(_("library.options_title", profile=profile.profile_id), actions)
    action_choice = action_sel.run(stdscr_c)
    if not action_choice:
        audit_log.debug("tui select.cancel: Options for %s", profile.profile_id)
        return
    audit_log.debug(
        "tui select.choose: Options for %s -> %s",
        profile.profile_id,
        actions[action_choice[0]],
    )
    if action_choice[0] == 0:
        audit.log_action_start("tui", "profile.activate", profile.profile_id)
        activate_uc = ProfileActivateUseCase(ws)

        activate_result = activate_uc.execute(ProfileActivateRequest(profile_id=profile.profile_id))
        if activate_result.issues:
            audit.log_action_end(
                "tui",
                "profile.activate",
                f"issues: {[i.error_code for i in activate_result.issues]}",
            )
            message_screen(
                stdscr_c, _("app.error_title"), [i.message for i in activate_result.issues]
            )
        else:
            audit.log_action_end("tui", "profile.activate", "activated")
            message_screen(
                stdscr_c,
                _("app.success_title"),
                [_("library.activated", profile=profile.profile_id)],
            )
    elif action_choice[0] == 1:
        confirmed = confirm_dialog(
            stdscr_c, _("library.delete_confirm", profile=profile.profile_id)
        )
        audit.log_confirmation(f"Delete profile '{profile.profile_id}'", confirmed)
        if not confirmed:
            return
        audit.log_action_start("tui", "profile.delete", profile.profile_id)

        result = ProfileDeleteUseCase(ws).execute(
            ProfileDeleteRequest(profile_id=profile.profile_id)
        )
        if result.issues:
            audit.log_action_end(
                "tui", "profile.delete", f"issues: {[i.error_code for i in result.issues]}"
            )
            message_screen(stdscr_c, _("app.error_title"), [i.message for i in result.issues])
        else:
            audit.log_action_end("tui", "profile.delete", "deleted")
            message_screen(
                stdscr_c,
                _("app.success_title"),
                [_("library.deleted", profile=profile.profile_id)],
            )
