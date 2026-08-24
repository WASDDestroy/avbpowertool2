# Editing and Creating TUI Pages

How to create or modify TUI views (pages).

## View Architecture

Each TUI page is a Python module in `avbpowertool/presentation/tui/views/` with a `show()` function:

```python
def show(stdscr: curses.window, ws: WorkspacePaths, avb: AvbToolPort) -> None
```

- `stdscr` — the curses window for rendering
- `ws` — workspace paths (immutable)
- `avb` — avbtool port (for subprocess calls)

## Creating a New View

1. Create a file in `avbpowertool/presentation/tui/views/my_view.py`:

```python
"""My custom view."""

from __future__ import annotations

import curses

from avbpowertool.application.ports import AvbToolPort
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.presentation.tui.widgets import (
    SelectorWidget,
    confirm_dialog,
    message_screen,
)


def show(stdscr: object, ws: WorkspacePaths, avb: AvbToolPort) -> None:
    """My custom view."""
    stdscr_c: curses.window = stdscr  # type: ignore[assignment]

    # Your logic here
    lines = ["Hello from my custom view!"]
    message_screen(stdscr_c, "My View", lines)
```

2. Register in `presentation/tui/app.py:_dispatch_action()`:

```python
from avbpowertool.presentation.tui.views import my_view

view_map = {
    ...
    "action:my.action": my_view.show,
}
```

3. Add the action to `resources/navigation.json`.

4. Add translations to `.po` files.

## Available Widgets

### SelectorWidget

Single or multi-select list with keyboard navigation.

```python
from avbpowertool.presentation.tui.widgets import SelectorWidget

# Single select
sel = SelectorWidget("Choose an option", ["Option A", "Option B", "Option C"])
result = sel.run(stdscr)  # returns list of selected indices, e.g. [0]
if result:
    chosen_index = result[0]

# Multi-select
sel = SelectorWidget("Select items", items, multi_select=True)
result = sel.run(stdscr)  # returns list of selected indices, e.g. [0, 2]
```

**Keyboard controls:**
- Up/Down or k/j: Navigate
- Enter: Confirm selection
- Space: Toggle selection (multi-select mode)
- Esc: Cancel

### confirm_dialog

Yes/No confirmation.

```python
from avbpowertool.presentation.tui.widgets import confirm_dialog

if confirm_dialog(stdscr, "Are you sure?"):
    # proceed
    pass
```

### message_screen

Display a message with title. Waits for Enter or Esc.

```python
from avbpowertool.presentation.tui.widgets import message_screen

message_screen(stdscr, "Results", [
    "Line 1",
    "Line 2",
    "Line 3",
])
```

### input_prompt

Text input prompt.

```python
from avbpowertool.presentation.tui.widgets import input_prompt

name = input_prompt(stdscr, "Enter profile name:")
```

## Calling Use Cases from Views

Views call application use cases and display results. Never access infrastructure directly.

```python
from avbpowertool.application.commands import InspectImagesRequest
from avbpowertool.application.services.inspect_images import InspectImagesUseCase

def show(stdscr, ws, avb):
    uc = InspectImagesUseCase(ws, avb)
    result = uc.execute(InspectImagesRequest(image_names=("boot",)))

    lines = []
    for img in result.images:
        lines.append(f"{img.image_name}: {img.descriptor}")
    for iss in result.issues:
        lines.append(f"[{iss.error_code}] {iss.message}")

    message_screen(stdscr, "Results", lines)
```

## Getting the Active Profile

```python
from avbpowertool.infrastructure.persistence.profile_repository import ProfileRepository

repo = ProfileRepository(ws)
active_id = repo.get_active_profile_id() or "current"
```

## Listing Images in a Profile

```python
profile_dir = ws.resolve_profile_dir(active_id)
images = [f.stem for f in sorted(profile_dir.iterdir()) if f.suffix == ".img"]
```

## Patterns

### Select-then-act

```python
def show(stdscr, ws, avb):
    # 1. Build list
    items = ["boot", "system", "vbmeta"]

    # 2. Show selector
    sel = SelectorWidget("Select images", items, multi_select=True)
    chosen = sel.run(stdscr)
    if not chosen:
        return  # user cancelled

    # 3. Confirm
    if not confirm_dialog(stdscr, "Proceed?"):
        return

    # 4. Execute
    selected = [items[i] for i in chosen]
    # ... call use case ...

    # 5. Show result
    message_screen(stdscr, "Done", [f"Processed {len(selected)} items"])
```

### Error handling

```python
def show(stdscr, ws, avb):
    try:
        # ... call use case ...
        pass
    except Exception as exc:
        message_screen(stdscr, "Error", [str(exc)])
        return
```
