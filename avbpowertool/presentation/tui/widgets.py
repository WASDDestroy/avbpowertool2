"""Curses-based widgets for the TUI.

Provides reusable widgets: Selector, Confirm, Message, Input.
"""

from __future__ import annotations

import contextlib
import curses
from collections.abc import Sequence


class SelectorWidget:
    """Single/multi-select list widget with keyboard navigation."""

    def __init__(
        self,
        title: str,
        items: Sequence[str],
        multi_select: bool = False,
    ) -> None:
        self.title = title
        self.items = list(items)
        self.multi_select = multi_select
        self.current = 0
        self.selected: set[int] = set()

    def run(self, stdscr: curses.window) -> list[int]:
        """Run the selector. Returns list of selected indices."""
        curses.curs_set(0)
        stdscr.keypad(True)

        while True:
            stdscr.clear()
            rows, cols = stdscr.getmaxyx()

            # Title
            stdscr.addstr(0, 0, f"  {self.title}"[: cols - 1], curses.A_BOLD)
            stdscr.addstr(1, 0, "=" * min(80, cols - 1))

            # Items
            start_row = 2
            for i, item in enumerate(self.items):
                row = start_row + i
                if row >= rows - 3:
                    break

                cursor = "-> " if i == self.current else "   "
                checkbox = ("[x] " if i in self.selected else "[ ] ") if self.multi_select else ""
                line = f"{cursor}{checkbox}{item}"
                attr = curses.A_REVERSE if i == self.current else 0
                with contextlib.suppress(curses.error):
                    stdscr.addstr(row, 0, line[: cols - 1], attr)

            # Status bar
            status_row = rows - 2
            stdscr.addstr(status_row, 0, "=" * min(80, cols - 1))
            if self.multi_select:
                status = f"  Selected: {len(self.selected)}/{len(self.items)}"
                with contextlib.suppress(curses.error):
                    stdscr.addstr(status_row + 1, 0, status[: cols - 1])
                help_text = "  Up/Down: Navigate  Space: Select  Enter: Confirm  Esc: Cancel"
            else:
                help_text = "  Up/Down: Navigate  Enter: Select  Esc: Back"
            with contextlib.suppress(curses.error):
                stdscr.addstr(rows - 1, 0, help_text[: cols - 1], curses.A_DIM)

            stdscr.refresh()

            # Input
            key = stdscr.getch()

            if key in (curses.KEY_UP, ord("k")):
                self.current = max(0, self.current - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                self.current = min(len(self.items) - 1, self.current + 1)
            elif key == ord(" ") and self.multi_select:
                if self.current in self.selected:
                    self.selected.discard(self.current)
                else:
                    self.selected.add(self.current)
            elif key in (curses.KEY_ENTER, 10, 13):
                if not self.multi_select:
                    return [self.current]
                if not self.selected:
                    return []
                return sorted(self.selected)
            elif key == 27:  # Esc
                return []

        return []


def confirm_dialog(stdscr: curses.window, prompt: str) -> bool:
    """Show a yes/no confirmation dialog. Returns True if confirmed."""
    sel = SelectorWidget(prompt, ["Yes", "No"])
    result = sel.run(stdscr)
    return len(result) > 0 and result[0] == 0


def message_screen(stdscr: curses.window, title: str, lines: list[str]) -> None:
    """Display a scrollable message screen.

    Content that does not fit on screen can be scrolled with the arrow
    keys (or ``j``/``k``), ``PageUp``/``PageDown``, ``Home``/``End`` and
    the mouse wheel.  Enter or Esc closes the screen.
    """
    curses.curs_set(0)
    stdscr.keypad(True)
    with contextlib.suppress(curses.error):
        curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)

    total = len(lines)
    top = 0  # index of the first visible content line

    while True:
        stdscr.clear()
        rows, cols = stdscr.getmaxyx()

        stdscr.addstr(0, 0, f"  {title}"[: cols - 1], curses.A_BOLD)
        stdscr.addstr(1, 0, "=" * min(80, cols - 1))

        # Content area: rows 2 .. rows-3 (bottom line is the help bar).
        body_rows = max(1, rows - 4)
        max_top = max(0, total - body_rows)
        top = min(max(top, 0), max_top)

        for i in range(body_rows):
            idx = top + i
            if idx >= total:
                break
            with contextlib.suppress(curses.error):
                stdscr.addstr(2 + i, 0, lines[idx][: cols - 1])

        help_text = "  Up/Down: Scroll  PgUp/PgDn: Page  Enter/Esc: Exit"
        with contextlib.suppress(curses.error):
            stdscr.addstr(rows - 1, 0, help_text[: cols - 1], curses.A_DIM)

        if total > body_rows:
            # Right-aligned scroll position indicator.
            percent = 100 * top // max_top if max_top else 0
            indicator = f" {percent}% "
            with contextlib.suppress(curses.error):
                stdscr.addstr(rows - 1, cols - len(indicator) - 1, indicator, curses.A_DIM)

        stdscr.refresh()

        key = stdscr.getch()

        if key in (curses.KEY_ENTER, 10, 13, 27):
            return
        if key == curses.KEY_RESIZE:
            continue
        if key in (curses.KEY_UP, ord("k")):
            top -= 1
        elif key in (curses.KEY_DOWN, ord("j")):
            top += 1
        elif key == curses.KEY_PPAGE:
            top -= body_rows
        elif key == curses.KEY_NPAGE:
            top += body_rows
        elif key == curses.KEY_HOME:
            top = 0
        elif key == curses.KEY_END:
            top = max_top
        elif key == curses.KEY_MOUSE:
            top = _scroll_from_mouse(top, body_rows)


def _scroll_from_mouse(top: int, body_rows: int) -> int:
    """Apply a mouse-wheel scroll to ``top`` and return the new offset."""
    try:
        _id, _x, _y, _z, bstate = curses.getmouse()
    except curses.error:
        return top
    step = max(1, body_rows // 3)
    if bstate & curses.BUTTON4_PRESSED:  # wheel up
        return top - step
    if bstate & curses.BUTTON5_PRESSED:  # wheel down
        return top + step
    return top


def input_prompt(stdscr: curses.window, prompt: str) -> str:
    """Show an input prompt. Returns the entered string."""
    curses.curs_set(1)
    stdscr.keypad(True)
    stdscr.clear()

    _rows, cols = stdscr.getmaxyx()
    with contextlib.suppress(curses.error):
        stdscr.addstr(0, 0, prompt[: cols - 1])
    stdscr.refresh()

    curses.echo()
    try:
        stdscr.move(1, 0)
        text = stdscr.getstr(1, 0, cols - 1).decode("utf-8", errors="replace")
    except curses.error:
        text = ""
    finally:
        curses.noecho()

    return text.strip()
