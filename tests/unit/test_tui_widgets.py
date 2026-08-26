"""Tests for the TUI widgets — scrollable message screen."""

from __future__ import annotations

import curses

import pytest

from avbpowertool.presentation.tui.widgets import message_screen


class FakeWindow:
    """Minimal curses window double for exercising message_screen."""

    def __init__(self, rows: int, cols: int, keys: list[int]) -> None:
        self._rows = rows
        self._cols = cols
        self._keys = list(keys)
        self.rendered: list[tuple[int, int, str]] = []
        self.paints: list[list[tuple[int, int, str]]] = []

    def getmaxyx(self) -> tuple[int, int]:
        return self._rows, self._cols

    def clear(self) -> None:
        self.rendered.clear()

    def addstr(self, y: int, x: int, text: str, attr: int = 0) -> None:
        del attr
        self.rendered.append((y, x, text))

    def refresh(self) -> None:
        self.paints.append(list(self.rendered))

    def keypad(self, flag: bool) -> None:
        del flag

    def getch(self) -> int:
        if not self._keys:
            return 27  # Esc
        return self._keys.pop(0)


def _run_message_screen(
    monkeypatch: pytest.MonkeyPatch,
    lines: list[str],
    keys: list[int],
    rows: int = 12,
    cols: int = 40,
) -> FakeWindow:
    monkeypatch.setattr(curses, "curs_set", lambda v: None)
    monkeypatch.setattr(curses, "mousemask", lambda *a: None)
    win = FakeWindow(rows, cols, keys)
    message_screen(win, "Title", lines)
    return win


def _content(paint: list[tuple[int, int, str]], rows: int) -> list[str]:
    """Content rows (2..rows-2) rendered in one paint, in order."""
    body = [text for (row, _x, text) in paint if 2 <= row <= rows - 2]
    return [t for t in body if t.strip()]


def _status_line(win: FakeWindow) -> str:
    paint = win.paints[-1]
    return "".join(text for (row, _x, text) in paint if row == win._rows - 1)


class TestMessageScreenScrolling:
    def test_content_that_fits_is_shown_and_enter_exits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lines = ["line one", "line two"]
        win = _run_message_screen(monkeypatch, lines, keys=[curses.KEY_ENTER])

        assert _content(win.paints[0], 12) == lines
        assert len(win.paints) == 1  # closed on the first Enter

    def test_short_content_has_no_scroll_indicator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        win = _run_message_screen(monkeypatch, ["a", "b"], keys=[27])
        assert "%" not in _status_line(win)

    def test_long_content_shows_indicator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        lines = [f"line {i}" for i in range(20)]
        win = _run_message_screen(monkeypatch, lines, keys=[27])
        assert "%" in _status_line(win)

    def test_arrow_keys_scroll_down(self, monkeypatch: pytest.MonkeyPatch) -> None:
        lines = [f"line {i}" for i in range(20)]
        # rows=12 -> body_rows = 8; two KEY_DOWN presses -> offset 2
        win = _run_message_screen(monkeypatch, lines, keys=[curses.KEY_DOWN, curses.KEY_DOWN, 27])

        assert _content(win.paints[0], 12) == lines[0:8]
        assert _content(win.paints[-1], 12) == lines[2:10]

    def test_arrow_keys_scroll_up(self, monkeypatch: pytest.MonkeyPatch) -> None:
        lines = [f"line {i}" for i in range(20)]
        win = _run_message_screen(monkeypatch, lines, keys=[curses.KEY_END, curses.KEY_UP, 27])

        # after END -> bottom (offset 12); after one UP -> offset 11
        assert _content(win.paints[-1], 12) == lines[11:19]

    def test_vim_keys_scroll(self, monkeypatch: pytest.MonkeyPatch) -> None:
        lines = [f"line {i}" for i in range(20)]
        win = _run_message_screen(monkeypatch, lines, keys=[ord("j"), ord("j"), 27])
        assert _content(win.paints[-1], 12) == lines[2:10]

    def test_home_returns_to_top(self, monkeypatch: pytest.MonkeyPatch) -> None:
        lines = [f"line {i}" for i in range(20)]
        win = _run_message_screen(monkeypatch, lines, keys=[curses.KEY_END, curses.KEY_HOME, 27])
        assert _content(win.paints[-1], 12) == lines[0:8]

    def test_end_jumps_to_bottom(self, monkeypatch: pytest.MonkeyPatch) -> None:
        lines = [f"line {i}" for i in range(20)]
        win = _run_message_screen(monkeypatch, lines, keys=[curses.KEY_END, 27])
        # total 20, body_rows 8 -> max_top 12
        assert _content(win.paints[-1], 12) == lines[12:20]

    def test_page_down_and_page_up(self, monkeypatch: pytest.MonkeyPatch) -> None:
        lines = [f"line {i}" for i in range(30)]
        win = _run_message_screen(
            monkeypatch,
            lines,
            keys=[curses.KEY_NPAGE, curses.KEY_PPAGE, 27],
        )
        # after NPAGE -> offset 8; after PPAGE back to 0
        assert _content(win.paints[-1], 12) == lines[0:8]
        page_paint = win.paints[-2]
        assert _content(page_paint, 12) == lines[8:16]

    def test_down_clamps_at_bottom(self, monkeypatch: pytest.MonkeyPatch) -> None:
        lines = [f"line {i}" for i in range(20)]
        many_down = [curses.KEY_DOWN] * 30 + [27]
        win = _run_message_screen(monkeypatch, lines, keys=many_down)
        assert _content(win.paints[-1], 12) == lines[12:20]

    def test_mouse_wheel_down_scrolls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        lines = [f"line {i}" for i in range(20)]
        monkeypatch.setattr(curses, "getmouse", lambda: (0, 0, 0, 0, curses.BUTTON5_PRESSED))
        win = _run_message_screen(monkeypatch, lines, keys=[curses.KEY_MOUSE, 27])
        # wheel step = max(1, 8 // 3) = 2
        assert _content(win.paints[-1], 12) == lines[2:10]

    def test_mouse_wheel_up_scrolls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        lines = [f"line {i}" for i in range(20)]
        monkeypatch.setattr(curses, "getmouse", lambda: (0, 0, 0, 0, curses.BUTTON4_PRESSED))
        win = _run_message_screen(
            monkeypatch,
            lines,
            keys=[curses.KEY_END, curses.KEY_MOUSE, 27],
        )
        # from bottom (12) wheel up by 2 -> 10
        assert _content(win.paints[-1], 12) == lines[10:18]

    def test_esc_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        lines = [f"line {i}" for i in range(20)]
        win = _run_message_screen(monkeypatch, lines, keys=[27])
        assert len(win.paints) == 1
