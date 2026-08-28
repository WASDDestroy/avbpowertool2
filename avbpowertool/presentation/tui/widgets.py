"""Curses-based widgets for the TUI.

Provides reusable widgets: Selector, Confirm, Message, Input.
"""

from __future__ import annotations

import contextlib
import curses
import locale
import unicodedata
from collections.abc import Sequence
from typing import NamedTuple

from avbpowertool.presentation.i18n import _

# PDCurses (windows-curses on Windows) accounts a line's width as one column
# per UTF-8 byte (with a 2-column allowance for the trailing multibyte
# character), so it silently drops trailing CJK characters once a line gets
# close to the right edge.  ncurses (Linux/macOS) does the same when the
# active locale is not UTF-8, and counts real terminal columns only with a
# UTF-8 locale.  We therefore fit lines to the width the active build really
# enforces so a drawn line is never clipped by curses.
_IS_NCURSES = hasattr(curses, "ncurses_version")


def _utf8_locale_active() -> bool:
    """True when the active CTYPE locale is UTF-8 (wide chars count 2 columns)."""
    try:
        _code, encoding = locale.getlocale(locale.LC_CTYPE)
    except Exception:
        return False
    if not encoding:
        return False
    encoding = encoding.upper()
    return "UTF" in encoding or "65001" in encoding


def _curs_set(visible: bool) -> None:
    """Show/hide the hardware cursor; some terminals reject it, so ignore errors."""
    with contextlib.suppress(curses.error):
        curses.curs_set(1 if visible else 0)


def _counts_real_columns() -> bool:
    """True when the active curses build counts CJK as 2 real terminal columns."""
    return _IS_NCURSES and _utf8_locale_active()


def _char_width(ch: str) -> int:
    """Terminal column width of one character (CJK-aware)."""
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def _display_width(text: str) -> int:
    """Approximate terminal column width of ``text`` (CJK-aware)."""
    return sum(_char_width(ch) for ch in text)


def _line_width(text: str) -> int:
    """Width the active curses build enforces when clipping a line.

    Lines wrapped/truncated to fit within this width are never clipped by
    ``addstr``, so trailing CJK characters are never dropped.  When real
    columns are not counted (PDCurses, or ncurses without a UTF-8 locale),
    the enforced width is the UTF-8 byte count minus the 2-column allowance
    PDCurses reserves for the final multibyte character.
    """
    if _counts_real_columns():
        return _display_width(text)
    if any(ord(ch) > 127 for ch in text):
        return max(0, len(text.encode("utf-8")) - 2)
    return len(text)


def _truncate_to_width(text: str, width: int) -> str:
    """Longest prefix of ``text`` that fits within ``width`` columns.

    Never splits a multibyte character, so the result is always valid text.
    """
    if width < 1:
        return ""
    if _line_width(text) <= width:
        return text
    result = ""
    for ch in text:
        candidate = result + ch
        if _line_width(candidate) <= width:
            result = candidate
        else:
            break
    return result


def _pad_cjk_line(text: str, cols: int) -> str:
    """Pad a CJK line with trailing spaces for PDCurses' row write.

    PDCurses on Windows writes an *attributed* row (A_BOLD/A_REVERSE/color
    pairs) to the console using the string's character count — counting
    each CJK character as 1 column — as the row width.  CJK renders as 2
    columns, so the trailing characters get dropped unless the character
    count reaches the real column width.  Appending one trailing space per
    CJK character makes ``len(text) == real column width``, so the whole
    line is written.  No-op on ncurses (which counts real columns) and for
    ASCII-only lines; the padding is capped so the line never exceeds the
    available width.
    """
    if _counts_real_columns():
        return text
    cjk = sum(1 for ch in text if ord(ch) > 127)
    if cjk == 0:
        return text
    pad = min(cjk, max(0, (cols - 1) - len(text)))
    return text + " " * pad if pad > 0 else text


def _split_token(token: str, width: int) -> list[str]:
    """Break an over-long token into chunks that each fit ``width`` columns."""
    chunks: list[str] = []
    current = ""
    for ch in token:
        candidate = current + ch
        if current and _line_width(candidate) > width:
            chunks.append(current)
            current = ""
        current += ch
    if current:
        chunks.append(current)
    return chunks


def _wrap_line(line: str, width: int) -> list[str]:
    """Wrap one line to fit within ``width`` terminal columns.

    Words are kept intact where they fit; a single token wider than
    ``width`` is hard-broken. Leading spaces are preserved on every
    continuation line. Empty lines stay single empty lines.
    """
    if width < 1 or _line_width(line) <= width:
        return [line]

    indent = line[: len(line) - len(line.lstrip(" "))]
    content = line[len(indent) :]
    words = content.split()
    if not words:
        return [line]

    result: list[str] = []
    current = indent

    for word in words:
        separator = " " if current != indent else ""
        candidate = current + separator + word
        if _line_width(candidate) <= width:
            current = candidate
            continue
        if current != indent:
            result.append(current)
            current = indent
        if _line_width(indent + word) <= width:
            current = indent + word
        else:
            for chunk in _split_token(word, width):
                result.append(indent + chunk)
            current = indent

    if current != indent:
        result.append(current)

    return result


def wrap_text(lines: Sequence[str], width: int) -> list[str]:
    """Wrap a sequence of lines so each fits within ``width`` columns.

    ``width`` is measured in the columns the active curses build enforces
    (see ``_line_width``), so wrapped lines are never clipped by curses.
    """
    wrapped: list[str] = []
    for line in lines:
        wrapped.extend(_wrap_line(line, width))
    return wrapped


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
            stdscr.addstr(
                0,
                0,
                _pad_cjk_line(_truncate_to_width(f"  {self.title}", cols - 1), cols),
                curses.A_BOLD,
            )
            stdscr.addstr(1, 0, "=" * min(80, cols - 1))

            # Items — long items are wrapped instead of truncated.
            start_row = 2
            row = start_row
            for i, item in enumerate(self.items):
                cursor = "-> " if i == self.current else "   "
                checkbox = ("[x] " if i in self.selected else "[ ] ") if self.multi_select else ""
                prefix = f"{cursor}{checkbox}"
                prefix_width = _display_width(prefix)
                content_width = max(1, cols - 1 - prefix_width)
                item_lines = wrap_text([item], content_width)
                if row + len(item_lines) > rows - 3:
                    break

                attr = curses.A_REVERSE if i == self.current else 0
                with contextlib.suppress(curses.error):
                    for j, item_line in enumerate(item_lines):
                        pad = prefix if j == 0 else " " * prefix_width
                        drawn = pad + item_line
                        if attr:
                            # Attributed rows lose trailing CJK on PDCurses;
                            # pad so the whole line is written.
                            drawn = _pad_cjk_line(drawn, cols)
                        stdscr.addstr(row + j, 0, drawn, attr)
                row += len(item_lines)

            # Status bar
            status_row = rows - 2
            stdscr.addstr(status_row, 0, "=" * min(80, cols - 1))
            if self.multi_select:
                status = f"  Selected: {len(self.selected)}/{len(self.items)}"
                with contextlib.suppress(curses.error):
                    stdscr.addstr(status_row + 1, 0, _truncate_to_width(status, cols - 1))
                help_text = "  Up/Down: Navigate  Space: Select  Enter: Confirm  Esc: Cancel"
            else:
                help_text = "  Up/Down: Navigate  Enter: Select  Esc: Back"
            with contextlib.suppress(curses.error):
                stdscr.addstr(
                    rows - 1,
                    0,
                    _pad_cjk_line(_truncate_to_width(help_text, cols - 1), cols),
                    curses.A_DIM,
                )

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

    Long lines are automatically wrapped to the available width so no
    text is truncated.  Content that does not fit on screen can be
    scrolled with the arrow keys (or ``j``/``k``), ``PageUp``/``PageDown``,
    ``Home``/``End`` and the mouse wheel.  Enter or Esc closes the screen.
    """
    curses.curs_set(0)
    stdscr.keypad(True)
    with contextlib.suppress(curses.error):
        curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)

    top = 0  # index of the first visible content line

    while True:
        stdscr.clear()
        rows, cols = stdscr.getmaxyx()

        stdscr.addstr(
            0, 0, _pad_cjk_line(_truncate_to_width(f"  {title}", cols - 1), cols), curses.A_BOLD
        )
        stdscr.addstr(1, 0, "=" * min(80, cols - 1))

        # Wrap long lines to the available width (recomputed each frame so
        # a terminal resize re-wraps automatically).
        wrapped = wrap_text(lines, max(1, cols - 1))
        total = len(wrapped)

        # Content area: rows 2 .. rows-3 (bottom line is the help bar).
        body_rows = max(1, rows - 4)
        max_top = max(0, total - body_rows)
        top = min(max(top, 0), max_top)

        for i in range(body_rows):
            idx = top + i
            if idx >= total:
                break
            with contextlib.suppress(curses.error):
                stdscr.addstr(2 + i, 0, wrapped[idx])

        help_text = "  Up/Down: Scroll  PgUp/PgDn: Page  Enter/Esc: Exit"
        with contextlib.suppress(curses.error):
            stdscr.addstr(
                rows - 1,
                0,
                _pad_cjk_line(_truncate_to_width(help_text, cols - 1), cols),
                curses.A_DIM,
            )

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


class _LineEditor:
    """Line-edit state: a character buffer plus a caret index."""

    def __init__(self) -> None:
        self.chars: list[str] = []
        self.pos = 0  # caret position: 0..len(chars)

    def text(self) -> str:
        return "".join(self.chars)

    def left(self) -> None:
        self.pos = max(0, self.pos - 1)

    def right(self) -> None:
        self.pos = min(len(self.chars), self.pos + 1)

    def home(self) -> None:
        self.pos = 0

    def end(self) -> None:
        self.pos = len(self.chars)

    def backspace(self) -> None:
        if self.pos > 0:
            self.chars.pop(self.pos - 1)
            self.pos -= 1

    def delete(self) -> None:
        if self.pos < len(self.chars):
            self.chars.pop(self.pos)

    def clear(self) -> None:
        self.chars.clear()
        self.pos = 0

    def insert(self, text: str) -> None:
        for ch in text:
            self.chars.insert(self.pos, ch)
            self.pos += 1


def _read_key(stdscr: curses.window) -> int | str:
    """Read one key event: an int key code or a single-character string.

    ``get_wch`` (ncursesw and windows-curses builds) returns whole
    multi-byte characters as strings and function keys as ints; control
    characters also arrive as strings there, so they are normalized back
    to their int codes.  The plain-``getch`` fallback covers narrow
    ncurses builds that deliver UTF-8 bytes one at a time (function keys
    are >= 0x100 there, so byte values never collide with them).
    """
    get_wch = getattr(stdscr, "get_wch", None)
    if get_wch is not None:
        try:
            key = get_wch()
        except curses.error:
            return -1
        if isinstance(key, str):
            if len(key) == 1 and (ord(key) < 32 or ord(key) == 0x7F):
                return ord(key)  # control keys arrive as str: normalize to int
            return key
        return int(key)

    key = stdscr.getch()
    if not 0x80 <= key <= 0xFF:
        return key  # ASCII, function key code, or error

    if not 0xC2 <= key <= 0xF4:
        return chr(key)  # stray continuation byte or invalid lead: Latin-1 fallback

    # Narrow ncurses delivers a UTF-8 sequence one byte per getch.
    buf = bytearray([key])
    expected = 1 if key < 0xE0 else 2 if key < 0xF0 else 3
    for _i in range(expected):
        nxt = stdscr.getch()
        if not 0x80 <= nxt <= 0xBF:
            return chr(key)  # malformed sequence: keep the buffer valid
        buf.append(nxt)
    try:
        return buf.decode("utf-8")
    except UnicodeDecodeError:
        return chr(key)


class _EditRender(NamedTuple):
    """Render plan for one frame of the edit line."""

    line: str  # overflow marks + visible text, drawn at column 0
    cursor_col: int  # cell column of the cursor within the row
    cursor_ch: str  # character drawn in the cursor cell (" " at end of text)


def _fit_unit(ch: str) -> int:
    """Columns one character consumes in the clip-safe fitting budget."""
    if _counts_real_columns():
        return _char_width(ch)
    return len(ch.encode("utf-8"))


def _fit_width(text: str) -> int:
    return sum(_fit_unit(ch) for ch in text)


def _cursor_units(text: str) -> int:
    """Row cells ``text`` occupies in the active curses build.

    Cell accounting differs per build: real columns (ncurses with a UTF-8
    locale), one cell per character (PDCurses) or one cell per UTF-8 byte
    (narrow ncurses).  A separately drawn cursor cell must be positioned
    with the build's own accounting or it lands on the wrong character.
    """
    if _counts_real_columns():
        return _display_width(text)
    if not _IS_NCURSES:
        return len(text)
    return len(text.encode("utf-8"))


def _fit_prefix(text: str, width: int) -> str:
    """Longest prefix of ``text`` whose fit width stays within ``width``."""
    out: list[str] = []
    used = 0
    for ch in text:
        w = _fit_unit(ch)
        if used + w > width:
            break
        used += w
        out.append(ch)
    return "".join(out)


def _scroll_start(text: str, end: int, budget: int) -> int:
    """Largest ``start <= end`` with the fit width of ``text[start:end]`` in budget."""
    start = end
    used = 0
    while start > 0:
        w = _fit_unit(text[start - 1])
        if used + w > budget:
            break
        used += w
        start -= 1
    return start


def _edit_line_render(text: str, pos: int, avail: int) -> _EditRender:
    """Plan one frame of the edit line for ``text`` with the caret at ``pos``.

    The whole text is shown when it fits ``avail`` columns; otherwise a
    window around the caret is shown, with ``<``/``>`` marking hidden text
    on either side.  The caret is always visible.
    """
    if _fit_width(text) <= avail:
        return _EditRender(text, _cursor_units(text[:pos]), text[pos] if pos < len(text) else " ")

    # Head-anchored window while the caret character is visible from column 0.
    if pos < len(text) and _fit_width(text[: pos + 1]) <= avail:
        drawn = _fit_prefix(text, avail - 1)
        return _EditRender(
            drawn + (">" if len(drawn) < len(text) else ""),
            _cursor_units(text[:pos]),
            text[pos],
        )

    # Scrolled window ending at the caret; column 0 holds the "<" mark.
    budget = max(1, avail - 1)
    start = _scroll_start(text, min(pos + 1, len(text)), budget)
    drawn = _fit_prefix(text[start:], budget)
    line = ("<" if start > 0 else "") + drawn + (">" if start + len(drawn) < len(text) else "")
    return _EditRender(
        line,
        (1 if start > 0 else 0) + _cursor_units(text[start:pos]),
        text[pos] if pos < len(text) else " ",
    )


def _draw_input_prompt(stdscr: curses.window, prompt: str, editor: _LineEditor) -> None:
    """Draw the prompt, the edit line with an inline cursor, and a help bar."""
    stdscr.clear()
    rows, cols = stdscr.getmaxyx()
    avail = max(3, cols - 1)

    row = 0
    for line in wrap_text([prompt], max(1, cols - 1)):
        with contextlib.suppress(curses.error):
            stdscr.addstr(row, 0, _pad_cjk_line(line, cols), curses.A_BOLD)
        row += 1

    render = _edit_line_render(editor.text(), editor.pos, avail)
    with contextlib.suppress(curses.error):
        stdscr.addstr(row, 0, _pad_cjk_line(render.line, cols))
    with contextlib.suppress(curses.error):
        stdscr.addstr(row, render.cursor_col, render.cursor_ch, curses.A_REVERSE)

    help_text = "  " + _("input.help")
    with contextlib.suppress(curses.error):
        stdscr.addstr(
            min(row + 1, rows - 1),
            0,
            _pad_cjk_line(_truncate_to_width(help_text, cols - 1), cols),
            curses.A_DIM,
        )

    stdscr.refresh()


def input_prompt(stdscr: curses.window, prompt: str) -> str:
    """Show an input prompt. Returns the entered string (stripped).

    The caret is drawn inline as a reverse-video cell, so it stays visible
    even on terminals where the hardware cursor is unreliable (PDCurses
    under Windows Terminal/ConPTY).  Editing keys: Left/Right/Home/End
    move the caret, Backspace/Delete erase, Ctrl+U clears the line, Enter
    confirms and Esc cancels (empty string).
    """
    _curs_set(False)
    stdscr.keypad(True)
    editor = _LineEditor()

    while True:
        _draw_input_prompt(stdscr, prompt, editor)
        key = _read_key(stdscr)

        if isinstance(key, str):
            editor.insert(key)
            continue
        if key in (curses.KEY_ENTER, 10, 13):
            return editor.text().strip()
        if key == 27:  # Esc
            return ""
        if key == curses.KEY_LEFT:
            editor.left()
        elif key == curses.KEY_RIGHT:
            editor.right()
        elif key in (curses.KEY_HOME, 1):  # Home / Ctrl+A
            editor.home()
        elif key in (curses.KEY_END, 5):  # End / Ctrl+E
            editor.end()
        elif key in (curses.KEY_BACKSPACE, 8, 127):
            editor.backspace()
        elif key in (curses.KEY_DC, 4):  # Delete / Ctrl+D
            editor.delete()
        elif key == 21:  # Ctrl+U
            editor.clear()
        elif 32 <= key < 0x100:
            # Narrow ncurses getch delivers printable characters as int key
            # codes; KEY_* codes are >= 0x100 and matched above.
            editor.insert(chr(key))
