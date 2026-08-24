# CLAUDE.md

## Project

AVBPowerTool2 — a configuration-driven Python wrapper for AOSP `avbtool.py`.
Provides CLI and TUI for Android Verified Boot image signing, inspection, and config management.

## Commands

```shell
uv sync                          # Install deps
uv run pytest                    # Run tests
uv run ruff check avbpowertool   # Lint
uv run ruff format avbpowertool  # Format
uv run pyright avbpowertool      # Type check
```

## Architecture

Four-layer hexagonal architecture (see IMPLEMENTATION_PLAN.md):

- `domain/` — pure models, validation, signing plan (no I/O)
- `application/` — use cases, ports (Protocol interfaces)
- `infrastructure/` — avbtool subprocess, filesystem, persistence, FEC
- `presentation/` — CLI (argparse) and TUI (curses)

Dependency direction: presentation -> application -> domain. Infrastructure implements ports.

## Key Conventions

- Python 3.11+ required. Use `X | Y` union syntax, `match/case`, builtin generics.
- All domain models are `@dataclass(frozen=True)`.
- avbtool.py is vendored AOSP code with a minimal FEC fallback patch — treat as vendor.
- i18n via Python gettext. `.po` files in `locale/`.
- Navigation tree: single `resources/navigation.json`.
- Config: v2 JSON schema. Profile + key store in `profiles/<name>/`.
- Tests: pytest. `tests/unit/`, `tests/integration/`, `tests/contract/`.
- Logging: Python `logging` stdlib, no custom singletons.
- Never import avbtool.py internals — call via subprocess only.
