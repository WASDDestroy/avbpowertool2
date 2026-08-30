# Architecture

The overall architecture of AVBPowerTool2: layers, data flow, and the responsibilities of each module.

## Big Picture

AVBPowerTool2 is a configuration-driven wrapper around AOSP's `avbtool.py`. It follows a **four-layer hexagonal (ports & adapters) architecture**:

```
                        ┌─────────────────────────────┐
                        │      presentation/          │
                        │  cli/ (argparse)  tui/ (curses) │
                        │  actions.py  audit.py  i18n.py  │
                        └──────────────┬──────────────┘
                                       │ calls use cases only
                        ┌──────────────▼──────────────┐
                        │      application/           │
                        │  commands.py (request/result) │
                        │  ports.py    (Protocols)      │
                        │  services/   (use cases)      │
                        └──────────────┬──────────────┘
                                       │ depends only on domain
                        ┌──────────────▼──────────────┐
                        │        domain/              │
                        │  models  validation          │
                        │  signing_plan  dependency_graph │
                        │  command_spec  command_builder  │
                        │  errors                       │
                        └─────────────────────────────┘
                                       ▲ implements ports
                        ┌──────────────┴──────────────┐
                        │      infrastructure/        │
                        │  avbtool/   (subprocess runner, parser) │
                        │  filesystem/ (workspace, atomic writer) │
                        │  persistence/ (profile/key/archive/settings) │
                        └─────────────────────────────┘
```

Dependency direction is **strictly inward**: presentation → application → domain. Infrastructure sits outside and implements the ports (interfaces) defined in `application/ports.py`. Two hard rules:

- `domain/` imports nothing from other layers.
- `application/` depends only on domain objects and the `Protocol` definitions in `ports.py` — never on concrete infrastructure classes.

## Layer Responsibilities

### domain/ — Pure business logic, zero I/O

All models are `@dataclass(frozen=True)`. No file, network, or subprocess access anywhere in this layer.

| Module | Responsibility |
|---|---|
| `models.py` | Core dataclasses: `AvbProfile`, `PartitionConfig`, `SigningStep`, `SigningPlan`, `ChainDescriptor`, `ImageInspection`, `OperationIssue` |
| `validation.py` | Profile / partition / key-manifest validators (return issues, don't raise for user data) |
| `signing_plan.py` | `SigningPlanBuilder` — turns a profile + images into an ordered `SigningPlan` of `SigningStep`s. Pure planner: computes, writes nothing |
| `dependency_graph.py` | Topological sort of the vbmeta chain so chained partitions sign after their dependencies |
| `command_spec.py` | `CommandSpec` — declarative description of each avbtool command's arguments (used for validation and defaults) |
| `command_builder.py` | Builds avbtool argument lists (`build_hash_footer_command`, `build_vbmeta_command`, …) from `PartitionConfig` objects |
| `errors.py` | Domain exceptions with stable error codes (`config.key_missing`, `image.not_found`, `signing.step_failed`, `workspace.root_not_found`, …) |

Note that `command_builder.py` lives in domain, not infrastructure: command construction is a pure business concern (an option is only emitted when its value differs from the default). `infrastructure/avbtool/command_builder.py` is a backward-compatible re-export of it.

### application/ — Use cases and ports

| Module | Responsibility |
|---|---|
| `commands.py` | Frozen `*Request` / `*Result` dataclasses for every use case (`SignImagesRequest`, `InspectImagesResult`, …). This is the API surface between presentation and application |
| `ports.py` | `AvbToolPort` (how to invoke avbtool operations) and `ProgressSink` (progress events: `StepStarted`, `StepCompleted`, `SigningCompleted`). Protocols — use cases accept any implementation |
| `services/` | One module per capability: `inspect_images.py`, `sign_images.py`, `manage_configs.py`, `manage_profiles.py`, `manage_keys.py`, `resolve_chains.py` |

Use case pattern: constructor takes the ports it needs (plus repositories), `execute(request) -> result` does the orchestration. Use cases own transactions/logging around domain logic but never touch the filesystem or subprocesses directly — they go through ports.

Example call flow for signing:

```
SignImagesUseCase.execute(SignImagesRequest)
  -> SigningPlanBuilder (domain)        # pure plan: order steps, stage copies
  -> AvbToolPort (infrastructure)       # run each avbtool command
  -> ProgressSink (presentation)        # report step progress
  -> SignImagesResult(steps, issues)
```

### infrastructure/ — I/O adapters

| Module | Responsibility |
|---|---|
| `avbtool/runner.py` | `SubprocessAvbTool` — implements `AvbToolPort` by shelling out to the vendored `avbtool.py`. avbtool is vendor code: called via subprocess only, never imported |
| `avbtool/output_parser.py` | `parse_info_image` — parses `avbtool info_image` text output into `ImageInspection` domain objects |
| `filesystem/workspace.py` | `WorkspacePaths` — frozen dataclass resolving the canonical layout (`Images/`, `profiles/`, `Logs/`, `.avbpowertool-staging/`, `avbtool.py`). All paths flow through it; business logic never calls `os.getcwd()` |
| `filesystem/atomic_writer.py` | `AtomicWriter` — write-to-temp-then-move so config files are never half-written |
| `persistence/profile_codec.py` | v2/v3 JSON encode/decode for `profile.json` (plus `v1_profile_codec.py` and `v2_to_v3.py` for legacy imports) |
| `persistence/profile_repository.py` | Profile CRUD on disk |
| `persistence/key_repository.py` | Key manifest management (`keys/manifest.json` + `.pem` files) |
| `persistence/archive_repository.py` | ZIP import/export of configs |
| `persistence/settings_repository.py` | Global `settings.json` (`language`, `log_level`) and `SETTING_DEFS` |
| `fec/` | Empty — the FEC encoder lives in `avbpowertool/vendor/fec_encoder.py` (numpy + reedsolo, cross-platform) |

Persistence modules are excluded from strict pyright (they handle untyped JSON at the boundary).

### presentation/ — CLI and TUI

| Module | Responsibility |
|---|---|
| `actions.py` | `ActionId` StrEnum — stable machine-readable identifiers (`image.sign`, `config.import`, …). CLI dispatch, navigation, and TUI binding all reference these constants, never display strings |
| `cli/parser.py` | argparse setup + `main()` entry point. No args → launch TUI; args → CLI dispatch |
| `cli/handlers.py` | `dispatch()` maps parsed args to use case calls; one `_handle_*` per command. Builds Request objects, passes results to renderer |
| `cli/renderer.py` | `render_*` functions — output as text or JSON (`--json`) |
| `tui/app.py` | `App` — curses main loop. Reads `resources/navigation.json`, renders the current route, translates labels via `_()`, dispatches actions |
| `tui/router.py` | `Router` — loads and validates `navigation.json`; routes, nav items, and back/exit semantics |
| `tui/views/` | One module per screen (`sign_images.py`, `read_image_info.py`, `settings.py`, …). Each exposes a `show(...)` function following `docs/en/FRONTEND_PAGES.md` |
| `tui/widgets.py` | Reusable curses widgets (`SelectorWidget`, `message_screen`, input widgets) |
| `audit.py` | Audit logger — sessions, navigation, selections, confirmations, action starts/endings |
| `i18n.py` | gettext wrapper (`_()`, `init_i18n`, `check_l10n`). See `docs/en/I18N.md` |

## Composition Root

`bootstrap.py` is the single place where concrete implementations are wired:

```
bootstrap(root, language)
  1. WorkspacePaths.discover(root)          # resolve layout
  2. SettingsRepository.load()              # persisted settings
  3. init_i18n(language)                    # locale from arg or settings
  4. setup_logging(...)                     # timestamped session log
  -> WorkspacePaths
```

CLI and TUI entry points both call `bootstrap()` first, then construct their own adapters (`SubprocessAvbTool`, repositories) and use cases. There is no global service locator; each view/handler receives what it needs.

## Workspace Layout at Runtime

```
<workspace root>/
  avbtool.py                  # vendored AOSP tool (also lives at repo root in dev)
  Images/                     # device-local image files (gitignored)
  profiles/<profile>/         # portable per-device configs (gitignored)
    profile.json
    keys/                     # .pem files + manifest.json
  Logs/                       # session logs + audit log (gitignored)
  .avbpowertool-staging/      # temp copies during signing (gitignored)
  settings.json               # global settings (gitignored)
```

Images live at workspace level (not inside profiles) so that configs + keys stay portable across devices while images are device-local. `WorkspacePaths.resolve_image_path()` rejects paths escaping `Images/` (`workspace.path_escape`).

## Key Data Flows

### Inspect an image

```
CLI/TUI -> InspectImagesUseCase -> AvbToolPort.info_image (subprocess)
        -> output_parser.parse_info_image -> ImageInspection -> renderer/view
```

### Sign images

```
CLI/TUI -> SignImagesUseCase
        -> SigningPlanBuilder (domain: order steps via dependency_graph, stage copies)
        -> AvbToolPort (erase/hash/hashtree footer, vbmeta commands)
        -> ProgressSink events + OperationIssue list
        -> SignImagesResult
```

Footer commands modify images in place, so the plan stages a copy under `.avbpowertool-staging/` before running them.

### Config import/export

```
ZIP file -> ArchiveRepository -> ProfileCodec (v2/v3) -> ProfileRepository
```

Legacy 1.x archives go through `v1_profile_codec` + `v2_to_v3` migration.

## Testing Strategy

```
tests/
  unit/          # domain logic, codecs, parsers, builders (no I/O; tmp_path where needed)
  integration/   # use cases against fake adapters (FakeAvbTool), TUI router, bootstrap i18n
  contract/      # navigation.json schema validation
  fixtures/      # avbtool output samples, profile/manifest dicts
```

- `tests/conftest.py` provides `tmp_workspace`, `FakeAvbTool`, and sample profile/manifest fixtures. `FakeAvbTool` implements `AvbToolPort` in memory so use case tests never invoke real subprocesses.
- Real `Keys/`, `Images/`, and user profiles are never read in tests; everything uses `tmp_path`.
- Contract tests guard `resources/navigation.json` (all referenced actions/routes exist, start route valid) so TUI navigation can't silently break.

## Cross-Cutting Concerns

- **Error codes**: stable dotted codes on domain exceptions (`config.key_missing`, `image.not_found`, `signing.step_failed`, …). Renderers and views can match on them; they appear in JSON output.
- **Logging**: stdlib `logging` only. Each session opens a timestamped file in `Logs/`; audit events go through `presentation/audit.py` to a dedicated audit logger.
- **i18n**: only presentation translates; see `docs/en/I18N.md`.
- **Atomic writes**: all config/manifest persistence goes through `AtomicWriter` (temp file + move), so a crash mid-write cannot corrupt a profile.

## Extension Points

- **New use case**: `commands.py` types → `services/` implementation → CLI parser/handler/renderer → `ActionId` → optional TUI view + `navigation.json` entry. Detailed checklists: "Adding a New Use Case" in `AGENTS.md`, `docs/en/FRONTEND_NAVIGATION.md`, `docs/en/FRONTEND_PAGES.md`.
- **New avbtool operation**: extend `domain/command_spec.py` + `domain/command_builder.py`, add a method to `AvbToolPort` and `SubprocessAvbTool`, then call it from a use case.
- **New storage format version**: add a codec in `infrastructure/persistence/` and a migration module (pattern: `v1_profile_codec` + `v2_to_v3`).
