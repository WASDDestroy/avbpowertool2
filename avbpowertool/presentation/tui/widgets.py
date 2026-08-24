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
    """Display a message screen. Waits for Enter or Esc."""
    curses.curs_set(0)
    stdscr.keypad(True)

    while True:
        stdscr.clear()
        rows, cols = stdscr.getmaxyx()

        stdscr.addstr(0, 0, f"  {title}"[: cols - 1], curses.A_BOLD)
        stdscr.addstr(1, 0, "=" * min(80, cols - 1))

        for i, line in enumerate(lines):
            row = 2 + i
            if row >= rows - 2:
                break
            with contextlib.suppress(curses.error):
                stdscr.addstr(row, 0, line[: cols - 1])

        with contextlib.suppress(curses.error):
            stdscr.addstr(rows - 1, 0, "  Press Enter or Esc to continue"[: cols - 1], curses.A_DIM)

        stdscr.refresh()

        key = stdscr.getch()
        if key in (curses.KEY_ENTER, 10, 13, 27):
            return


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
