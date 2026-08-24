# Adding Navigation Entries

How to add new entries to the TUI navigation tree.

## Navigation File

All navigation is defined in a single file: `avbpowertool/resources/navigation.json`.

## Structure

```json
{
  "schema_version": 1,
  "start_route": "route:home",
  "routes": { ... },
  "actions": { ... }
}
```

- **routes**: Pages in the navigation tree. Each has items that are either actions or sub-routes.
- **actions**: Metadata (label key, description key) for each callable action.

## Adding an Action to an Existing Route

1. Add the action metadata to the `actions` section:

```json
"action:my.new_action": {
  "label_key": "my.new_action.label",
  "description_key": "my.new_action.description"
}
```

2. Add the action item to the route's `items` array:

```json
"route:home": {
  "items": [
    {"action": "action:my.new_action", "shortcut": "N"},
    ...
  ]
}
```

3. Add translations to `locale/en/LC_MESSAGES/avbpowertool.po` and `locale/zh/LC_MESSAGES/avbpowertool.po`.

4. Register the action handler in `presentation/tui/app.py:_dispatch_action()`:

```python
view_map = {
    ...
    "action:my.new_action": my_view.show,
}
```

5. Create the view module in `presentation/tui/views/my_view.py`.

## Adding a New Sub-Route

1. Add the route to the `routes` section:

```json
"route:my_section": {
  "title_key": "my.section.title",
  "description_key": "my.section.description",
  "parent": "route:home",
  "items": [
    {"action": "action:my.action1", "shortcut": "A"},
    {"action": "action:my.action2", "shortcut": "B"}
  ]
}
```

2. Add a route item to the parent route:

```json
"route:home": {
  "items": [
    {"route": "route:my_section", "shortcut": "M"},
    ...
  ]
}
```

3. Add all referenced actions to the `actions` section.

## Rules

- **Shortcuts** must be single uppercase letters, unique within each route.
- **Action IDs** use the format `action:<domain>.<verb>` (e.g. `action:image.sign`).
- **Route IDs** use the format `route:<name>` (e.g. `route:config_manager`).
- The router auto-adds `[B] Back` (when not at root) and `[E] Exit` (at root).
- Every action and route referenced in items must exist in their respective sections.
- The contract test `tests/contract/test_navigation_schema.py` validates these rules.

## Validation

After modifying `navigation.json`, run the contract tests:

```shell
uv run pytest tests/contract/test_navigation_schema.py -v
```

This checks:
- All action references exist in the `actions` section
- All route references exist in the `routes` section
- No orphan routes (every route is reachable from start)
- Shortcuts are unique within each route
