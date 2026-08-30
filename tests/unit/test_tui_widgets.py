"""Tests for the TUI widgets - message screen, selector and input prompt."""

from __future__ import annotations

import curses

import pytest

from avbpowertool.presentation.tui import widgets
from avbpowertool.presentation.tui.widgets import (
    SelectorWidget,
    input_prompt,
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
        self.cursor_parks: list[tuple[int, int]] = []
        self.caret_highlights: list[tuple[int, int, int, int]] = []

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

    def get_wch(self) -> int | str:
        # Mirror get_wch semantics: characters (including CJK codepoints)
        # and control keys arrive as str; curses KEY_* codes (0x100..0x1FF)
        # stay int.
        key = self.getch()
        if 0x100 <= key < 0x200:
            return key
        return chr(key)

    def move(self, y: int, x: int) -> None:
        # Records where the hardware cursor is parked (IME anchor point).
        self.cursor_parks.append((y, x))

    def chgat(self, y: int, x: int, width: int, attr: int) -> None:
        # Records the reverse-video caret highlight (y, x, width).
        self.caret_highlights.append((y, x, width, attr))


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

    def test_cjk_wraps_by_byte_accounting_on_narrow_ncurses(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Narrow ncurses without a UTF-8 locale counts one column per UTF-8
        # byte, so only 3 CJK chars fit in width 9 instead of 4.
        monkeypatch.setattr(widgets, "_IS_NCURSES", True)
        monkeypatch.setattr(widgets, "_utf8_locale_active", lambda: False)
        assert widgets.wrap_text(["一二三四五六"], 9) == ["一二三", "四五六"]

    def test_cjk_wrap_preserves_every_character(self, monkeypatch: pytest.MonkeyPatch) -> None:
        text = "中文消息很长很长需要被正确地折行并且不丢失任何字符abcdefg中文"
        for is_ncurses, is_utf8 in ((True, True), (False, False)):
            monkeypatch.setattr(widgets, "_IS_NCURSES", is_ncurses)
            monkeypatch.setattr(widgets, "_utf8_locale_active", lambda is_utf8=is_utf8: is_utf8)
            wrapped = widgets.wrap_text([text], 20)
            assert "".join(wrapped) == text  # no character lost or reordered
            for line in wrapped:
                assert widgets._line_width(line) <= 20

    def test_nothing_never_exceeds_width(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for is_ncurses, is_utf8 in ((True, True), (False, False)):
            monkeypatch.setattr(widgets, "_IS_NCURSES", is_ncurses)
            monkeypatch.setattr(widgets, "_utf8_locale_active", lambda is_utf8=is_utf8: is_utf8)
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


class TestSelectorHotkeys:
    def _run_selector(
        self,
        monkeypatch: pytest.MonkeyPatch,
        keys: list[int],
        items: list[str],
        multi_select: bool = False,
    ) -> tuple[list[int], FakeWindow]:
        monkeypatch.setattr(curses, "curs_set", lambda v: None)
        win = FakeWindow(12, 40, keys)
        result = SelectorWidget("Title", items, multi_select=multi_select).run(win)  # type: ignore[arg-type]
        return result, win

    def test_uppercase_hotkey_activates_item(self, monkeypatch: pytest.MonkeyPatch) -> None:
        items = ["[R] Read image info", "[S] Sign images", "[E] Exit"]
        result, _win = self._run_selector(monkeypatch, [ord("R")], items)
        assert result == [0]

    def test_lowercase_hotkey_activates_item(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Hotkeys match both letter cases.
        items = ["[R] Read image info", "[S] Sign images", "[E] Exit"]
        result, _win = self._run_selector(monkeypatch, [ord("s")], items)
        assert result == [1]

    def test_hotkey_for_back_and_exit_entries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        items = ["[R] Read image info", "[B] Back"]
        result, _win = self._run_selector(monkeypatch, [ord("B")], items)
        assert result == [1]

    def test_hotkey_moves_cursor_in_multi_select(self, monkeypatch: pytest.MonkeyPatch) -> None:
        items = ["[A] One", "[B] Two"]
        result, _win = self._run_selector(
            monkeypatch, [ord("B"), ord(" "), 10], items, multi_select=True
        )
        assert result == [1]

    def test_unknown_letter_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        items = ["[R] Read image info"]
        result, _win = self._run_selector(monkeypatch, [ord("x"), 27], items)
        assert result == []

    def test_items_without_bracket_prefix_have_no_hotkey(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # e.g. the config library selector: plain labels, no hotkeys.
        result, _win = self._run_selector(monkeypatch, [ord("y"), 27], ["Yes", "No"])
        assert result == []

    def test_j_and_k_are_no_longer_movement_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # j/k must not move the cursor: 'k' now triggers the [K] hotkey
        # (e.g. "[K] Manage keys" in Key Management) and 'j' is inert
        # unless an item exposes [J].
        items = ["[C] One", "[K] Two", "[E] Three"]
        result, _win = self._run_selector(monkeypatch, [ord("k")], items)
        assert result == [1]  # hotkey wins over vim-style movement
        result, _win = self._run_selector(monkeypatch, [ord("j"), 27], items)
        assert result == []


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


class _NarrowWindow(FakeWindow):
    """Window without get_wch: models narrow ncurses (byte-wise getch)."""

    get_wch = None  # type: ignore[assignment]


def _run_input(
    monkeypatch: pytest.MonkeyPatch,
    keys: list[int],
    cols: int = 40,
    rows: int = 6,
    prompt: str = "Enter value:",
) -> tuple[FakeWindow, str]:
    monkeypatch.setattr(curses, "curs_set", lambda v: None)
    win = FakeWindow(rows, cols, keys)
    text = input_prompt(win, prompt)  # type: ignore[arg-type]
    return win, text


class TestInputPrompt:
    """Editing behaviour of the rewritten input_prompt."""

    def test_plain_typing_and_enter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        win, text = _run_input(monkeypatch, [ord("a"), ord("b"), ord("c"), 10])
        assert text == "abc"
        assert len(win.paints) == 4  # initial frame + one per character

    def test_enter_key_code_confirms(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _win, text = _run_input(monkeypatch, [ord("x"), curses.KEY_ENTER])
        assert text == "x"

    def test_esc_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _win, text = _run_input(monkeypatch, [ord("a"), 27])
        assert text == ""

    def test_backspace_erases(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _win, text = _run_input(monkeypatch, [ord("a"), ord("b"), curses.KEY_BACKSPACE, 10])
        assert text == "a"

    def test_backspace_control_code_erases(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # get_wch delivers Backspace as the control string -> normalized to 8
        _win, text = _run_input(monkeypatch, [ord("a"), ord("b"), 8, 10])
        assert text == "a"

    def test_delete_erases_forward(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _win, text = _run_input(
            monkeypatch, [ord("a"), ord("b"), curses.KEY_LEFT, curses.KEY_DC, 10]
        )
        assert text == "a"

    def test_arrow_keys_move_cursor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _win, text = _run_input(monkeypatch, [ord("a"), ord("b"), curses.KEY_LEFT, ord("X"), 10])
        assert text == "aXb"

    def test_home_and_end_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _win, text = _run_input(monkeypatch, [ord("a"), ord("b"), curses.KEY_HOME, ord("X"), 10])
        assert text == "Xab"

    def test_home_end_control_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Ctrl+A (1) = home, Ctrl+E (5) = end: ab -> Xab -> XabY
        _win, text = _run_input(monkeypatch, [ord("a"), ord("b"), 1, ord("X"), 5, ord("Y"), 10])
        assert text == "XabY"

    def test_ctrl_u_clears_line(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # get_wch delivers Ctrl+U as a control string -> normalized to 21
        _win, text = _run_input(monkeypatch, [ord("a"), ord("b"), 21, ord("c"), 10])
        assert text == "c"

    def test_left_at_start_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _win, text = _run_input(monkeypatch, [curses.KEY_LEFT, ord("a"), 10])
        assert text == "a"

    def test_right_at_end_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _win, text = _run_input(monkeypatch, [ord("a"), curses.KEY_RIGHT, 10])
        assert text == "a"

    def test_result_is_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _win, text = _run_input(monkeypatch, [ord(" "), ord("a"), ord(" "), 10])
        assert text == "a"

    def test_inline_cursor_cell_drawn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # "ab" then Left: the caret sits on "b" at column 1; the reverse
        # highlight is applied via chgat over the already-drawn glyph
        # (rewriting the cell with addstr would corrupt wide glyphs).
        win, _text = _run_input(monkeypatch, [ord("a"), ord("b"), curses.KEY_LEFT])
        assert win.caret_highlights[-1][:3] == (1, 1, 1)
        edit_line = [t for (y, _x, t) in win.paints[-1] if y == 1]
        assert edit_line == ["ab"]

    def test_empty_text_cursor_at_start(self, monkeypatch: pytest.MonkeyPatch) -> None:
        win, _text = _run_input(monkeypatch, [10])
        assert win.caret_highlights[0][:3] == (1, 0, 1)

    def test_long_text_scrolls_and_keeps_tail_visible(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        word = "abcdefghij"
        keys = [ord(c) for _ in range(5) for c in word] + [10]
        win, text = _run_input(monkeypatch, keys, cols=21)  # avail = 20
        assert text == word * 5
        edit_line = "".join(t for (y, _x, t) in win.paints[-1] if y == 1)
        assert edit_line.startswith("<")
        assert "j" in edit_line  # tail of the text stays visible

    def test_scrolled_caret_moves_with_arrow_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        word = "abcdefghij"
        keys = [ord(c) for _ in range(5) for c in word]
        keys += [curses.KEY_LEFT] * 15 + [10]
        win, text = _run_input(monkeypatch, keys, cols=21)
        assert text == word * 5
        edit_line = "".join(t for (y, _x, t) in win.paints[-1] if y == 1)
        assert edit_line.startswith("<")

    def test_home_scrolls_back_to_start(self, monkeypatch: pytest.MonkeyPatch) -> None:
        word = "abcdefghij"
        keys = [ord(c) for _ in range(5) for c in word] + [curses.KEY_HOME, 10]
        win, _text = _run_input(monkeypatch, keys, cols=21)
        edit_line = "".join(t for (y, _x, t) in win.paints[-1] if y == 1)
        assert edit_line.startswith(word)

    def test_cjk_input_via_get_wch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _win, text = _run_input(monkeypatch, [ord("中"), ord("文"), 10])
        assert text == "中文"

    def test_cjk_caret_column_on_pdcurses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # PDCurses lays CJK out in real columns on the physical screen: a
        # caret between two CJK characters highlights column 2 for 2
        # cells (the width of the caret glyph), and the glyph under it
        # stays intact because chgat only flips attributes.
        monkeypatch.setattr(widgets, "_IS_NCURSES", False)
        monkeypatch.setattr(widgets, "_utf8_locale_active", lambda: False)
        win, _text = _run_input(
            monkeypatch, [ord("中"), ord("中"), curses.KEY_LEFT], prompt="输入："
        )
        y, x, width, _attr = win.caret_highlights[-1]
        assert (y, x, width) == (1, 2, 2)  # on 2nd CJK char, 2 cells wide
        edit_line = [t for (ty, _tx, t) in win.paints[-1] if ty == 1]
        assert edit_line == ["中中  "]  # both glyphs still drawn

    def test_cjk_caret_column_on_ncurses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # ncurses with a UTF-8 locale counts 2 columns per CJK character:
        # a caret between two CJK characters sits at column 2.
        monkeypatch.setattr(widgets, "_IS_NCURSES", True)
        monkeypatch.setattr(widgets, "_utf8_locale_active", lambda: True)
        win, _text = _run_input(
            monkeypatch, [ord("中"), ord("中"), curses.KEY_LEFT], prompt="输入："
        )
        y, x, width, _attr = win.caret_highlights[-1]
        assert (y, x, width) == (1, 2, 2)

    def test_hardware_cursor_parked_on_drawn_caret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The hidden hardware cursor must be parked on the drawn caret cell:
        # the IME composition window anchors to it, so a stale position
        # floats the candidate window onto the prompt row while composing.
        monkeypatch.setattr(widgets, "_IS_NCURSES", False)
        monkeypatch.setattr(widgets, "_utf8_locale_active", lambda: False)
        win, _text = _run_input(
            monkeypatch, [ord("中"), ord("中"), curses.KEY_LEFT], prompt="输入："
        )
        assert win.cursor_parks[-1] == (1, 2)  # edit row, caret column

    def test_hardware_cursor_parked_at_end_of_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        win, _text = _run_input(monkeypatch, [ord("a"), ord("b"), 10])
        assert win.cursor_parks[-1] == (1, 2)  # after "ab"

    def test_narrow_getch_assembles_utf8_bytes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Narrow ncurses getch delivers a UTF-8 sequence one byte at a time.
        monkeypatch.setattr(curses, "curs_set", lambda v: None)
        keys = list("中".encode()) + [10]
        win = _NarrowWindow(6, 40, keys)
        text = input_prompt(win, "输入：")  # type: ignore[arg-type]
        assert text == "中"

    def test_narrow_getch_printable_int_keys_are_inserted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Regression: narrow ncurses getch delivers printable ASCII as int
        # key codes; the dispatch chain used to drop them silently.
        monkeypatch.setattr(curses, "curs_set", lambda v: None)
        keys = [ord(c) for c in "abc"] + [curses.KEY_LEFT, ord("X"), 10]
        win = _NarrowWindow(6, 40, keys)
        text = input_prompt(win, "Enter value:")  # type: ignore[arg-type]
        assert text == "abXc"
