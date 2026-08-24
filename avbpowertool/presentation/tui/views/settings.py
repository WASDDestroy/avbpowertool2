"""Settings view — edit, view, import legacy configs, and check translations."""

from __future__ import annotations

import curses

from avbpowertool.application.commands import LegacyImportRequest
from avbpowertool.application.ports import AvbToolPort
from avbpowertool.application.services.manage_configs import LegacyConfigImportUseCase
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.persistence.settings_repository import (
    SETTING_DEFS,
    SettingsRepository,
)
from avbpowertool.presentation.i18n import _, check_l10n, get_current_language
from avbpowertool.presentation.tui.widgets import (
    SelectorWidget,
    message_screen,
)


def show_import_legacy(stdscr: object, ws: WorkspacePaths, avb: AvbToolPort) -> None:
    """Import a legacy (v1) config archive, converting it to v2."""
    stdscr_c: curses.window = stdscr  # type: ignore[assignment]

    # Find ZIP files in project root
    zip_files: list[str] = []
    for f in sorted(ws.root.iterdir()):
        if f.suffix == ".zip" and f.is_file():
            zip_files.append(f.name)

    if not zip_files:
        message_screen(stdscr_c, _("legacy.import.title"), [_("legacy.import.no_archives")])
        return

    sel = SelectorWidget(_("legacy.import.select_archive"), zip_files)
    chosen = sel.run(stdscr_c)
    if not chosen:
        return

    archive_name = zip_files[chosen[0]]
    archive_path = str(ws.root / archive_name)

    uc = LegacyConfigImportUseCase(ws)
    request = LegacyImportRequest(archive_path=archive_path)
    result = uc.execute(request)

    lines: list[str] = []
    if result.profile_id:
        lines.append(
            _(
                "legacy.import.success",
                profile=result.profile_id,
                partitions=result.partition_count,
                keys=result.key_count,
            )
        )
    for iss in result.issues:
        lines.append(f"  [{iss.error_code}] {iss.message}")

    message_screen(stdscr_c, _("legacy.import.title"), lines)


def show_edit(stdscr: object, ws: WorkspacePaths, avb: AvbToolPort) -> None:
    """Edit global settings."""
    stdscr_c: curses.window = stdscr  # type: ignore[assignment]
    repo = SettingsRepository(ws.root)
    settings = repo.load()

    # Build setting list
    setting_keys = list(SETTING_DEFS.keys())
    setting_labels = [f"{_(SETTING_DEFS[k]['label_key'])}: {settings.get(k)}" for k in setting_keys]

    sel = SelectorWidget(_("settings.select_setting"), setting_labels)
    result = sel.run(stdscr_c)
    if not result:
        return

    chosen_key = setting_keys[result[0]]
    defn = SETTING_DEFS[chosen_key]

    if defn["type"] == "choice":
        option_keys = list(defn["options"].keys())
        option_labels = [_(defn["options"][k]) for k in option_keys]

        # Mark current value
        current_val = settings.get(chosen_key)
        option_labels_display = []
        for i, k in enumerate(option_keys):
            suffix = f" ({_('settings.current_suffix')})" if k == current_val else ""
            option_labels_display.append(option_labels[i] + suffix)

        opt_sel = SelectorWidget(
            _(defn["label_key"]),
            option_labels_display,
        )
        opt_result = opt_sel.run(stdscr_c)
        if not opt_result:
            return

        new_value = option_keys[opt_result[0]]
        new_settings = settings.with_value(chosen_key, new_value)
        repo.save(new_settings)

        message_screen(
            stdscr_c,
            _("settings.saved_title"),
            [
                _("settings.saved", key=_(defn["label_key"]), old=current_val, new=new_value),
                _("settings.restart_notice"),
            ],
        )


def show_view(stdscr: object, ws: WorkspacePaths, avb: AvbToolPort) -> None:
    """View current settings."""
    stdscr_c: curses.window = stdscr  # type: ignore[assignment]
    repo = SettingsRepository(ws.root)
    settings = repo.load()

    lines: list[str] = [
        _("settings.current_settings"),
        "",
    ]
    for key, defn in SETTING_DEFS.items():
        val = settings.get(key)
        # Find the display label for the value
        display_val = _(defn["options"].get(val, val))
        lines.append(f"  {_(defn['label_key'])}: {display_val}")

    lines.append("")
    lines.append(f"  {_('settings.file_location')}: {repo.get_path()}")

    message_screen(stdscr_c, _("settings.view_title"), lines)


def show_check_l10n(stdscr: object, ws: WorkspacePaths, avb: AvbToolPort) -> None:
    """Check missing translations for the current language."""
    stdscr_c: curses.window = stdscr  # type: ignore[assignment]

    language = get_current_language()
    missing = check_l10n(language)

    lines: list[str] = [
        _("settings.check_l10n_header", language=language),
        "",
    ]

    if not missing:
        lines.append(_("settings.check_l10n.no_missing", language=language))
    else:
        lines.append(_("settings.check_l10n.missing_header", language=language, count=len(missing)))
        for key in sorted(missing.keys()):
            lines.append(f'  <string name="{key}">{missing[key]}</string>')

    message_screen(stdscr_c, _("settings.check_l10n_title"), lines)
