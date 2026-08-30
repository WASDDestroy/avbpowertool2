# AGENTS.MD

Guidance for coding agents working in this repository.

## Project Overview

AVBPowerTool2 is a Python 3.11+ configuration-driven wrapper for AOSP `avbtool.py`. It provides CLI and TUI for Android Verified Boot image signing, inspection, and config management.

The entry point is `avbpowertool/presentation/cli/parser.py:main`. Running `avbpowertool` without arguments launches the TUI; with arguments it runs the CLI.

## Repository Layout

```
avbtool.py                          Vendored AOSP avbtool (patched: in-process crypto + pure-Python FEC fallback; see docs/en/VENDORED_AVBTOOL_PATCHES.md)
avbpowertool/                       Python package
  domain/                           Pure models, validation, signing plan (no I/O)
  application/                      Use cases, ports (Protocol), events
  application/services/             Use case implementations
  infrastructure/                   I/O adapters
    avbtool/                        Subprocess runner, output parser, command builder
    filesystem/                     Workspace paths, atomic writer
    persistence/                    Profile codec, profile/key/archive repositories
    fec/                            (empty, FEC in vendor/)
  presentation/                     CLI and TUI
    actions.py                      ActionId StrEnum
    cli/                            argparse parser, handlers, renderer
    tui/                            Curses app, router, widgets, views
    i18n.py                         gettext setup
  resources/                        navigation.json
  locale/                           .po translation files
  vendor/fec_encoder.py             Cross-platform FEC encoder (numpy + reedsolo)
  bootstrap.py                      Composition root
  _version.py                       Version string
tests/
  unit/                             Unit tests
  integration/                      Integration tests
  contract/                         Schema/contract tests
  fixtures/                         Test data (avbtool outputs, profiles)
docs/en/                            English documentation
docs/zh/                            Chinese documentation
```

## Architecture

Four-layer hexagonal architecture. Dependency direction: presentation → application → domain. Infrastructure implements ports defined in application/ports.py.

- `domain/` never imports from other layers.
- `application/` depends only on domain objects and `ports.py` Protocols.
- `infrastructure/` implements the ports.
- `presentation/` calls application use cases only.

## Coding Conventions

- Python 3.11+. Use `X | Y` union syntax, `match/case`, builtin generics (`list`, `dict`, `tuple`).
- All domain models are `@dataclass(frozen=True)`.
- Stable error codes: `config.key_missing`, `image.not_found`, `signing.step_failed`, etc.
- Use Python `logging` stdlib — no custom singletons.
- i18n via Python gettext. Use `_("key")` in presentation layer.
- avbtool.py is vendored AOSP code — treat as vendor. Call via subprocess only, never import internals.
- FEC encoder in `vendor/` is excluded from strict pyright checking.
- Persistence modules (`infrastructure/persistence/`) are excluded from strict pyright (they deal with untyped JSON).

## Coding Workflow

Every change must pass this pipeline before commit:

```
1. Edit code
2. uv run pytest tests/          # all tests must pass
3. uv run ruff check avbpowertool  # zero warnings
4. uv run ruff format avbpowertool # all files formatted
5. uv run pyright avbpowertool     # zero errors (strict mode)
6. git add + git commit
```

If any step fails, fix the issue and restart from step 2.

### Committing Is Mandatory

A task is not complete when the code works — it is complete when the changes are committed. Step 6 is not optional:

- Never end a session with uncommitted changes. If the working tree is dirty when you finish, commit it.
- Commit as soon as a coherent unit of work passes the pipeline; prefer small, focused commits over one giant commit.
- Docs/markdown-only changes skip steps 2–5 (nothing to test or lint) but still require a commit.
- Match the existing commit message style (`feat(scope):`, `fix:`, `docs:`, `refactor:`).
- Do not push unless explicitly asked. Committing is part of the work; pushing is a separate decision.

## Development Commands

```shell
uv sync                              # Install all deps (including dev)
uv sync --all-extras                 # Install with dev tools (crypto/FEC/windows-curses are core deps)
uv run pytest tests/                 # Run all tests
uv run pytest tests/ -v              # Verbose test output
uv run pytest tests/ -q              # Quiet test output
uv run ruff check avbpowertool       # Lint
uv run ruff check --fix avbpowertool # Lint with auto-fix
uv run ruff format avbpowertool      # Format
uv run ruff format --check avbpowertool  # Check formatting
uv run pyright avbpowertool          # Type check (strict mode)
uv run avbpowertool --help           # CLI help
uv run avbpowertool about            # Version info
```

## Test Conventions

- Test files: `tests/unit/test_<module>.py`, `tests/integration/test_<feature>.py`, `tests/contract/test_<schema>.py`
- Fixtures in `tests/conftest.py`: `tmp_workspace`, `FakeAvbTool`, sample profile/manifest dicts
- avbtool output fixtures in `tests/fixtures/avbtool_output/`
- Never read real `Keys/`, `Images/`, or user profile directories in tests.
- Use `tmp_path` fixture for all filesystem tests.

## Adding a New Use Case

1. Define request/result frozen dataclasses in `application/commands.py`
2. Implement use case class in `application/services/`
3. Add CLI command in `presentation/cli/parser.py` + handler in `handlers.py`
4. Add renderer in `presentation/cli/renderer.py`
5. Add ActionId in `presentation/actions.py`
6. Add TUI view in `presentation/tui/views/` (if interactive)
7. Update `resources/navigation.json` (if TUI entry needed)
8. Write tests in `tests/integration/`

## Adding a New Navigation Entry

See `docs/en/FRONTEND_NAVIGATION.md` for detailed instructions.

## Adding a New TUI Page

See `docs/en/FRONTEND_PAGES.md` for detailed instructions.

## Runtime State and Safety

This project manipulates Android image files, key material, config archives, and logs. Be careful with:

- `profiles/` — user configs and keys (gitignored)
- `Logs/` — runtime logs (gitignored)
- `Images/` — user image files (gitignored)
- `*.zip` — exported archives (gitignored)

Do not delete, overwrite, or normalize these unless explicitly asked.

## Key Files Reference

| File | Purpose |
|---|---|
| `domain/models.py` | All domain dataclasses (AvbProfile, PartitionConfig, SigningPlan, etc.) |
| `domain/validation.py` | Profile/partition/key manifest validators |
| `domain/signing_plan.py` | SigningPlanBuilder (pure planner, zero writes) |
| `domain/dependency_graph.py` | vbmeta chain topological sort |
| `application/ports.py` | AvbToolPort, ProgressSink Protocols |
| `application/commands.py` | Request/result types for all use cases |
| `infrastructure/avbtool/runner.py` | SubprocessAvbTool |
| `infrastructure/avbtool/output_parser.py` | parse_info_image |
| `infrastructure/avbtool/command_builder.py` | Build avbtool arg lists |
| `infrastructure/persistence/profile_codec.py` | v2 JSON encode/decode |
| `infrastructure/persistence/profile_repository.py` | Profile CRUD |
| `infrastructure/persistence/key_repository.py` | Key manifest management |
| `infrastructure/persistence/archive_repository.py` | ZIP import/export |
| `infrastructure/filesystem/workspace.py` | WorkspacePaths |
| `infrastructure/filesystem/atomic_writer.py` | Atomic file writer |
| `presentation/cli/parser.py` | CLI entry point |
| `presentation/tui/app.py` | TUI entry point |
| `presentation/tui/router.py` | Navigation router |
| `resources/navigation.json` | Navigation tree |
| `bootstrap.py` | Composition root |
