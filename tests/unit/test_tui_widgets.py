"""Tests for the TUI widgets — scrollable message screen."""

from __future__ import annotations

import curses

import pytest

from avbpowertool.presentation.tui import widgets
from avbpowertool.presentation.tui.widgets import (
    SelectorWidget,
    message_screen,
    wrap_text,
)


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


class TestWrapText:
    def test_short_line_unchanged(self) -> None:
        assert wrap_text(["hello world"], 40) == ["hello world"]

    def test_wraps_at_word_boundaries(self) -> None:
        wrapped = wrap_text(["one two three four five"], 10)
        assert wrapped == ["one two", "three four", "five"]

    def test_hard_breaks_over_long_token(self) -> None:
        wrapped = wrap_text(["abcdefghijklmno"], 5)
        assert wrapped == ["abcde", "fghij", "klmno"]

    def test_mixed_long_token_breaks_after_fitting_words(self) -> None:
        wrapped = wrap_text(["ab abcdefghijkl"], 6)
        assert wrapped == ["ab", "abcdef", "ghijkl"]

    def test_preserves_empty_lines(self) -> None:
        wrapped = wrap_text(["aaa bbb ccc", "", "ddd"], 5)
        assert wrapped == ["aaa", "bbb", "ccc", "", "ddd"]

    def test_keeps_leading_indent_on_continuation(self) -> None:
        wrapped = wrap_text(["  one two three four"], 10)
        assert wrapped == ["  one two", "  three", "  four"]

    def test_cjk_wraps_by_display_width_on_ncurses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # ncurses + UTF-8 locale counts 2 columns per CJK char, so 4 fit in width 9.
        monkeypatch.setattr(widgets, "_IS_NCURSES", True)
        monkeypatch.setattr(widgets, "_utf8_locale_active", lambda: True)
        assert widgets.wrap_text(["一二三四五六"], 9) == ["一二三四", "五六"]

    def test_cjk_wraps_by_byte_accounting_on_pdcurses(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # PDCurses (and ncurses without a UTF-8 locale) count one column per
        # UTF-8 byte, so only 3 CJK chars fit in width 9 instead of 4.
        monkeypatch.setattr(widgets, "_IS_NCURSES", False)
        monkeypatch.setattr(widgets, "_utf8_locale_active", lambda: False)
        assert widgets.wrap_text(["一二三四五六"], 9) == ["一二三", "四五六"]

    def test_cjk_wrap_preserves_every_character(self, monkeypatch: pytest.MonkeyPatch) -> None:
        text = "中文消息很长很长需要被正确地折行并且不丢失任何字符abcdefg中文"
        for is_ncurses, is_utf8 in ((True, True), (False, False)):
            monkeypatch.setattr(widgets, "_IS_NCURSES", is_ncurses)
            monkeypatch.setattr(widgets, "_utf8_locale_active", lambda: is_utf8)
            wrapped = widgets.wrap_text([text], 20)
            assert "".join(wrapped) == text  # no character lost or reordered
            for line in wrapped:
                assert widgets._line_width(line) <= 20

    def test_nothing_never_exceeds_width(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for is_ncurses, is_utf8 in ((True, True), (False, False)):
            monkeypatch.setattr(widgets, "_IS_NCURSES", is_ncurses)
            monkeypatch.setattr(widgets, "_utf8_locale_active", lambda: is_utf8)
            lines = [
                "No keys found yet. You can still continue and register keys later via Key "
                "Management; partitions referencing the keys will fail at sign time until then.",
                "   [config.key_missing] A very long issue message that keeps going far past the "
                "available columns and must be wrapped",
                "这里有一段很长的中文提示信息需要按照终端列宽正确折行并且不丢失任何字符",
            ]
            for line in widgets.wrap_text(lines, 25):
                assert widgets._line_width(line) <= 25

    def test_truncate_to_width_never_splits_cjk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # PDCurses byte accounting: one column per UTF-8 byte.
        monkeypatch.setattr(widgets, "_IS_NCURSES", False)
        monkeypatch.setattr(widgets, "_utf8_locale_active", lambda: False)
        text = "  AVBPowerTool 主页"
        out = widgets._truncate_to_width(text, 18)
        assert widgets._line_width(out) <= 18
        assert out == "  AVBPowerTool 主"  # dropped only the trailing 页, never split it
        # A wide enough window keeps the whole string.
        assert widgets._truncate_to_width(text, 30) == text


class TestPadCjkLine:
    def test_pads_cjk_line_on_pdcurses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # PDCurses writes attributed rows using the string's character count
        # (1 column per CJK char), so the line must be padded with one
        # trailing space per CJK char to reach the real column width.
        monkeypatch.setattr(widgets, "_IS_NCURSES", False)
        monkeypatch.setattr(widgets, "_utf8_locale_active", lambda: False)
        text = "  AVBPowerTool 主页"  # 2 CJK chars -> 2 trailing spaces
        real_cells = sum(2 if ord(ch) > 127 else 1 for ch in text)
        out = widgets._pad_cjk_line(text, 64)
        assert out == text + "  "
        # char count now reaches the real column width of the content
        assert len(out) == real_cells

    def test_no_pad_without_cjk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(widgets, "_IS_NCURSES", False)
        monkeypatch.setattr(widgets, "_utf8_locale_active", lambda: False)
        assert widgets._pad_cjk_line("hello world", 64) == "hello world"

    def test_no_pad_on_ncurses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(widgets, "_IS_NCURSES", True)
        monkeypatch.setattr(widgets, "_utf8_locale_active", lambda: True)
        assert widgets._pad_cjk_line("  AVBPowerTool 主页", 64) == "  AVBPowerTool 主页"

    def test_pad_capped_at_width(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(widgets, "_IS_NCURSES", False)
        monkeypatch.setattr(widgets, "_utf8_locale_active", lambda: False)
        text = "  AVBPowerTool 主页"
        # No room for padding: line must never exceed cols - 1.
        assert widgets._pad_cjk_line(text, 18) == text
        # One column of room -> one trailing space only.
        assert widgets._pad_cjk_line(text, 19) == text + " "


class TestMessageScreenWrapping:
    def test_long_line_is_wrapped_not_truncated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        long = "one two three four five six seven eight nine ten"
        win = _run_message_screen(monkeypatch, [long], keys=[27], cols=12)
        rendered = _content(win.paints[0], 12)
        assert rendered != [long]  # not kept as a single over-wide line
        assert all(len(line) <= 11 for line in rendered)
        assert " ".join(rendered).replace(" ", "") == long.replace(" ", "")

    def test_wrap_grows_scrollable_total(self, monkeypatch: pytest.MonkeyPatch) -> None:
        long = "line " + " ".join(f"w{i}" for i in range(40))
        # cols=10 -> width 9, one line wraps into ~14 rows; body_rows = 8
        win = _run_message_screen(monkeypatch, [long], keys=[27], cols=10)
        assert "%" in _status_line(win)


class TestSelectorWrapping:
    def test_long_item_wraps_without_truncation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(curses, "curs_set", lambda v: None)
        item = "key_a -> a_really_long_private_key_filename_that_overflows.pem"
        win = FakeWindow(12, 24, [curses.KEY_ENTER])
        SelectorWidget("Title", [item]).run(win)

        body = [
            text for (row, _x, text) in win.paints[0] if 2 <= row <= win._rows - 3 and text.strip()
        ]
        # item renders as >1 rows and no rendered line exceeds the width
        assert len(body) > 1
        assert all(len(text) <= 23 for text in body)

    def test_cjk_title_renders_fully_on_pdcurses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # PDCurses byte accounting must not drop the trailing CJK characters
        # of the title (regression: "AVBPowerTool 主页" lost "页").
        monkeypatch.setattr(widgets, "_IS_NCURSES", False)
        monkeypatch.setattr(widgets, "_utf8_locale_active", lambda: False)
        monkeypatch.setattr(curses, "curs_set", lambda v: None)
        win = FakeWindow(12, 30, [curses.KEY_ENTER])
        SelectorWidget("AVBPowerTool 主页", ["ok"]).run(win)
        title = "".join(text for (row, _x, text) in win.paints[0] if row == 0)
        assert "主页" in title
        # A_BOLD rows are written by PDCurses using char count, so the CJK
        # title must be padded with trailing spaces to survive the console.
        assert title.endswith("  ")

    def test_cjk_item_loses_no_characters_on_narrow_pdcurses(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Regression: "[V] 查看当前配置信息" used to render as "[V] 查看当前"
        # on PDCurses because curses clipped the line at the right edge.
        # Long items must now wrap across rows instead of losing characters.
        monkeypatch.setattr(widgets, "_IS_NCURSES", False)
        monkeypatch.setattr(widgets, "_utf8_locale_active", lambda: False)
        monkeypatch.setattr(curses, "curs_set", lambda v: None)
        item = "[V] 查看当前配置信息"
        win = FakeWindow(12, 24, [curses.KEY_ENTER])
        SelectorWidget("标题", [item]).run(win)
        body = "".join(
            text for (row, _x, text) in win.paints[0] if 2 <= row <= win._rows - 3 and text.strip()
        )
        assert "查看当前配置信息" in body.replace(" ", "")
        assert all(len(text) <= 23 for (_row, _x, text) in win.paints[0])

    def test_current_item_padded_on_pdcurses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The highlighted (A_REVERSE) item is drawn with the ConPTY padding
        # workaround so its trailing CJK survives the console write.
        monkeypatch.setattr(widgets, "_IS_NCURSES", False)
        monkeypatch.setattr(widgets, "_utf8_locale_active", lambda: False)
        monkeypatch.setattr(curses, "curs_set", lambda v: None)
        win = FakeWindow(12, 40, [curses.KEY_ENTER])
        SelectorWidget("标题", ["[V] 查看当前配置信息"]).run(win)
        row2 = "".join(text for (row, _x, text) in win.paints[0] if row == 2)
        assert "查看当前配置信息" in row2
        assert row2.endswith("        ")  # 8 CJK chars -> 8 trailing spaces


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
