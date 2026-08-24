# AVBPowerTool2 Implementation Plan

## 1. Decision Record

| Decision | Choice | Rationale |
|---|---|---|
| Starting point | From scratch | Clean slate, no legacy debt |
| avbtool invocation | subprocess only | avbtool exposes CLI only; no internal import |
| avbtool.py FEC | Minimal patch (A2) | Fallback to Python FEC when external `fec` unavailable |
| FEC call path | avbtool internally calls patched FEC (E1) | avbtool owns the signing flow end-to-end |
| TUI framework | curses + `windows-curses` | stdlib on POSIX; single optional dep on Windows |
| Navigation | Single `navigation.json` | Easier to validate, edit, diff; old tree structure preserved exactly |
| Config schema | v2 with `keys.json` | Canonical field names, explicit schema version |
| Key store layout | `profiles/<name>/keys/` + `manifest.json` | One profile = one key store |
| Package / CLI | `avbpowertool` / `avbpowertool` | |
| Python version | 3.11+ | `match/case`, `X \| Y` unions, complete gettext |
| i18n | Python gettext (`.po` / `.mo`) | stdlib, standard tooling |
| Logging | Python `logging` stdlib | No custom singleton |
| Tests | Written from scratch | Old tests have structural issues |
| Signing execution | Staging + atomic replace | Original images untouched until verified |
| Archive format | New format with manifest | No v1 compatibility |
| Scope | Phase 6 complete | CLI + TUI + all core use cases |

---

## 2. Target Directory Layout

```
AVBPowerTool2/
  avbtool.py                          # Vendored AOSP avbtool, minimally patched for FEC
  pyproject.toml                       # Build config, deps, entry points
  IMPLEMENTATION_PLAN.md               # This file
  CLAUDE.md                            # Agent instructions

  avbpowertool/                        # Python package
    __init__.py
    _version.py

    # ── Domain layer (pure logic, no I/O) ──
    domain/
      __init__.py
      models.py                        # Frozen dataclasses, enums
      errors.py                        # Typed exception hierarchy
      validation.py                    # Profile / partition / key validators
      signing_plan.py                  # SigningPlanBuilder (pure planner, zero writes)
      dependency_graph.py              # vbmeta chain ordering, cycle detection

    # ── Application layer (use cases) ──
    application/
      __init__.py
      commands.py                      # Request / result frozen dataclasses
      events.py                        # Progress event types
      ports.py                         # Protocol interfaces (AvbToolPort, KeyRepositoryPort, ...)
      services/
        __init__.py
        inspect_images.py              # InspectImagesUseCase
        sign_images.py                 # SignImagesUseCase (execute plan, staging, atomic replace)
        manage_configs.py              # Config CRUD use cases
        manage_keys.py                 # Key discovery, validation, cache generation
        manage_profiles.py             # Profile activate / deactivate / list

    # ── Infrastructure layer (I/O, subprocess, filesystem) ──
    infrastructure/
      __init__.py
      avbtool/
        __init__.py
        runner.py                      # SubprocessAvbTool (AvbToolPort impl)
        output_parser.py               # Parse avbtool info_image stdout
        command_builder.py             # Build avbtool arg lists from domain objects
      persistence/
        __init__.py
        profile_repository.py          # Read/write v2 profile.json
        profile_codec.py               # v2 JSON encode/decode + schema validation
        archive_repository.py          # ZIP import/export with manifest
        key_repository.py              # Key store + manifest.json management
      filesystem/
        __init__.py
        workspace.py                   # WorkspacePaths (immutable, resolved once)
        atomic_writer.py               # Staging dir + atomic replace
      fec/
        __init__.py
        encoder.py                     # Cross-platform FEC (numpy + reedsolo fallback)

    # ── Presentation layer ──
    presentation/
      __init__.py
      actions.py                       # ActionId enum, ActionRegistry
      cli/
        __init__.py
        parser.py                      # argparse tree
        handlers.py                    # Command handlers (build request, call use case, render)
        renderer.py                    # Text / JSON output formatters
      tui/
        __init__.py
        app.py                         # curses main loop, screen management
        router.py                      # Route stack, navigation.json loader
        widgets.py                     # Reusable curses widgets (selector, input, confirm)
        views/
          __init__.py
          home.py                      # Home page
          read_image_info.py           # Read image info page
          config_manager.py            # Config manager hub
          import_config.py             # Import config page
          export_config.py             # Export config page
          config_library.py            # Config library manager
          sign_images.py               # Sign images page
          settings.py                  # Settings page
          display_avb_info.py          # View current config info

    # ── Resources ──
    resources/
      navigation.json                  # Single navigation file
      logging.yaml                     # Logging config template
      profiles/                        # Runtime: created at first run
        .gitkeep

    locale/                            # gettext translation files
      en/
        LC_MESSAGES/
          avbpowertool.po
          avbpowertool.mo
      zh/
        LC_MESSAGES/
          avbpowertool.po
          avbpowertool.mo

    # ── Vendor ──
    vendor/
      __init__.py
      fec_encoder.py                   # Moved from infrastructure/fec or symlinked

  tests/
    __init__.py
    conftest.py                        # Shared fixtures (tmp workspace, fake avbtool, sample outputs)
    unit/
      __init__.py
      test_models.py
      test_validation.py
      test_signing_plan.py
      test_dependency_graph.py
      test_output_parser.py
      test_command_builder.py
      test_profile_codec.py
      test_profile_repository.py
      test_key_repository.py
      test_archive_repository.py
      test_atomic_writer.py
      test_workspace.py
      test_actions.py
    integration/
      __init__.py
      test_inspect_images.py
      test_sign_images.py
      test_manage_configs.py
      test_manage_keys.py
      test_manage_profiles.py
      test_cli_contract.py             # CLI --help, --json, exit codes
      test_tui_router.py               # Navigation completeness, action binding
    contract/
      __init__.py
      test_navigation_schema.py        # Every route/action referenced exists
      test_avbtool_output_fixtures.py  # Parser contract against known outputs
      test_profile_v2_schema.py        # JSON schema validation
    fixtures/
      avbtool_output/                  # Sample avbtool stdout text files
      profiles/                        # Sample v2 profile.json files
      archives/                        # Sample import/export archives
```

---

## 3. Domain Models (`domain/models.py`)

All models are `@dataclass(frozen=True)`. Python 3.11+ union syntax allowed.

```python
# Key types
PartitionName          # str, validated (alphanum + underscore)
ProfileId              # str, validated
KeyId                  # str, stable identifier in keys.json

# Enums
class DescriptorType(Enum):
    HASH = "hash"
    HASHTREE = "hashtree"
    VBMETA = "vbmeta"

class SigningAlgorithm(Enum):
    NONE = "NONE"
    SHA256_RSA2048 = "SHA256_RSA2048"
    SHA256_RSA4096 = "SHA256_RSA4096"
    SHA512_RSA2048 = "SHA512_RSA2048"
    SHA512_RSA4096 = "SHA512_RSA4096"

# Config models (v2)
@dataclass(frozen=True)
class KeyRef:
    key_id: KeyId
    private_key_filename: str       # filename within profile key store
    public_key_filename: str | None # derived, or explicit

@dataclass(frozen=True)
class PartitionConfig:
    image: str                      # e.g. "boot.img"
    descriptor: DescriptorType
    algorithm: SigningAlgorithm
    key_id: KeyId
    partition_name: str
    rollback_index: int = 0
    salt: str = ""
    flags: int = 0
    props: tuple[tuple[str, str], ...] = ()
    # vbmeta-specific
    included_partitions: tuple[str, ...] = ()   # partition names to include_descriptors_from
    chain_partitions: tuple[str, ...] = ()      # "partition_name:rollback_index_location:key_filename"
    # hashtree-specific
    data_block_size: int = 4096
    hash_block_size: int = 4096

@dataclass(frozen=True)
class AvbProfile:
    id: ProfileId
    name: str
    schema_version: int             # always 2
    key_store_path: str | None      # relative to profile dir; default "keys"
    partitions: dict[str, PartitionConfig]  # partition_name -> config

# Execution models
@dataclass(frozen=True)
class SigningStep:
    partition_name: str
    operation: str                  # "add_hash_footer" | "add_hashtree_footer" | "make_vbmeta_image"
    command: tuple[str, ...]        # avbtool arg list (without python + script prefix)
    input_path: str
    output_path: str                # staging path
    order: int

@dataclass(frozen=True)
class SigningPlan:
    profile_id: ProfileId
    steps: tuple[SigningStep, ...]
    vbmeta_order: tuple[str, ...]
    issues: tuple[OperationIssue, ...]

@dataclass(frozen=True)
class OperationIssue:
    error_code: str                 # stable machine-readable, e.g. "config.key_missing"
    message: str                    # human-readable (untranslated; localization at presentation)

# Inspection
@dataclass(frozen=True)
class ImageInspection:
    image_name: str
    image_path: str
    descriptor: DescriptorType
    algorithm: str | None = None
    partition_name: str | None = None
    public_key_sha1: str | None = None
    rollback_index: str | None = None
    salt: str | None = None
    digest: str | None = None
    flags: str | None = None
    props: tuple[tuple[str, str], ...] = ()
    raw_extensions: tuple[tuple[str, str], ...] = ()
```

---

## 4. Navigation Tree (`resources/navigation.json`)

Exact replica of the old tree:

```json
{
  "schema_version": 1,
  "start_route": "route:home",
  "routes": {
    "route:home": {
      "title_key": "node.home.name",
      "description_key": "node.home.description",
      "items": [
        {"action": "action:image.read_info", "shortcut": "R"},
        {"route": "route:config_manager", "shortcut": "M"},
        {"action": "action:image.sign", "shortcut": "S"},
        {"route": "route:settings", "shortcut": "T"},
        {"action": "action:view_current_config", "shortcut": "V"}
      ]
    },
    "route:config_manager": {
      "title_key": "node.config_manager.name",
      "description_key": "node.config_manager.description",
      "parent": "route:home",
      "items": [
        {"action": "action:config.import", "shortcut": "I"},
        {"action": "action:config.export", "shortcut": "E"},
        {"action": "action:config.library", "shortcut": "M"}
      ]
    },
    "route:settings": {
      "title_key": "node.settings.name",
      "description_key": "node.settings.description",
      "parent": "route:home",
      "items": [
        {"action": "action:settings.edit", "shortcut": "E"},
        {"action": "action:settings.view", "shortcut": "V"},
        {"action": "action:settings.check_l10n", "shortcut": "C"}
      ]
    }
  },
  "actions": {
    "action:image.read_info": {
      "label_key": "node.read_image_info.name",
      "description_key": "node.read_image_info.description"
    },
    "action:image.sign": {
      "label_key": "node.sign_images.name",
      "description_key": "node.sign_images.description"
    },
    "action:config.import": {
      "label_key": "node.import_config.name",
      "description_key": "node.import_config.description"
    },
    "action:config.export": {
      "label_key": "node.export_config.name",
      "description_key": "node.export_config.description"
    },
    "action:config.library": {
      "label_key": "node.config_library.name",
      "description_key": "node.config_library.description"
    },
    "action:view_current_config": {
      "label_key": "home.action.view_current_config_info",
      "description_key": ""
    },
    "action:settings.edit": {
      "label_key": "settings.action.edit",
      "description_key": ""
    },
    "action:settings.view": {
      "label_key": "settings.action.view",
      "description_key": ""
    },
    "action:settings.check_l10n": {
      "label_key": "settings.action.check_l10n",
      "description_key": ""
    }
  }
}
```

Navigation rules:
- `route:*` items navigate to a sub-route (rendered as a menu entry).
- `action:*` items dispatch to a use case (rendered as a menu entry).
- Every route has `parent` (except root). TUI router maintains a route stack.
- `shortcut` is a single uppercase letter, unique within the containing route.
- `B` is always "Back", `E` (on root) is always "Exit" — auto-injected by router.
- A view (leaf page like `action:image.sign`) is not a route; it opens a screen, does its work, and returns to the parent route.

---

## 5. Phase Breakdown

### Phase 0: Project Skeleton

**Goal:** Package installs, tests run, CI-lint passes, avbtool.py vendored and patched.

Tasks:
1. Create `pyproject.toml` with build metadata, deps, entry points, tool config.
2. Create package skeleton (`avbpowertool/__init__.py`, all `__init__.py` files).
3. Copy `avbtool.py` into project root (vendored).
4. Patch `avbtool.py`: in `generate_fec_data()`, add fallback import of `avbpowertool.vendor.fec_encoder.generate_fec_data` when the external `fec` binary is not found.
5. Create `tests/conftest.py` with `tmp_workspace` fixture and `FakeAvbTool`.
6. Create `tests/fixtures/avbtool_output/` with sample text outputs (hash, hashtree, vbmeta with chains, no-footer stderr).
7. Set up ruff, pyright config in `pyproject.toml`.
8. Create `.gitignore` (add `*.pyc`, `__pycache__`, `*.egg-info`, `dist/`, `profiles/`, `Logs/`, `locale/*/LC_MESSAGES/*.mo`).
9. Verify: `uv sync`, `pytest` (empty), `ruff check`, `pyright`.

**Deliverables:** Installable package, zero tests pass, lint clean.

---

### Phase 1: Domain Layer

**Goal:** Pure domain models, validation, signing planner, dependency graph.

Tasks:

**1.1 `domain/models.py`**
- All frozen dataclasses as specified in Section 3.
- `DescriptorType.from_avbtool_label(label: str)` classmethod.
- `SigningAlgorithm` enum with avbtool string values.
- `OperationIssue` with `error_code` and `message`.

**1.2 `domain/errors.py`**
- `AvbError(Exception)` base with `error_code`.
- `ValidationError`, `ConfigError`, `WorkspaceError`, `ToolExecutionError`, `SigningError`.
- Each carries a default `error_code` string.

**1.3 `domain/validation.py`**
- `validate_profile(profile: AvbProfile) -> list[OperationIssue]`: check schema_version, non-empty partitions, valid algorithm, key_id referenced.
- `validate_partition(name: str, config: PartitionConfig) -> list[OperationIssue]`: image non-empty, descriptor valid, algorithm valid for descriptor type.
- `validate_key_manifest(manifest: dict) -> list[OperationIssue]`: every key_id has at least a private key file.

**1.4 `domain/signing_plan.py`**
- `SigningPlanBuilder` class.
  - `__init__(self, profile: AvbProfile, image_dir: Path, key_dir: Path, staging_dir: Path)`.
  - `build(self, partition_names: tuple[str, ...]) -> SigningPlan`: pure planner.
  - Resolves image paths, key paths.
  - Orders non-vbmeta first, vbmeta last (using `dependency_graph`).
  - For each step, builds the avbtool command arg list (without python/script prefix).
  - Catches missing images/keys into `OperationIssue`, never raises.
  - Zero writes to filesystem.

**1.5 `domain/dependency_graph.py`**
- `resolve_vbmeta_order(partitions: dict[str, PartitionConfig]) -> tuple[tuple[str, ...], tuple[OperationIssue, ...]]`.
- Topological sort of vbmeta chain dependencies.
- Detects cycles (returns `config.cycle_detected` issue).
- Detects missing referenced partitions.

**Tests:**
- `tests/unit/test_models.py`: construction, enum conversion, frozen behavior.
- `tests/unit/test_validation.py`: valid profile passes, missing key_id caught, bad descriptor caught.
- `tests/unit/test_signing_plan.py`: hash step, hashtree step, vbmeta step, missing partition issue, missing image issue, missing key issue, deterministic ordering.
- `tests/unit/test_dependency_graph.py`: simple chain, nested chain, cycle detection, missing node.

---

### Phase 2: Infrastructure — avbtool Adapter

**Goal:** Subprocess avbtool calls, output parsing, command building.

Tasks:

**2.1 `application/ports.py`**
- `AvbToolResult` (returncode, stdout, stderr, command_summary).
- `AvbToolPort(Protocol)`: `inspect_image`, `erase_footer`, `add_hash_footer`, `add_hashtree_footer`, `make_vbmeta_image`, `extract_public_key`.
- `ProgressSink(Protocol)`: `on_event(event)`.
- `NULL_PROGRESS` sentinel.

**2.2 `infrastructure/avbtool/runner.py`**
- `SubprocessAvbTool(AvbToolPort)`.
  - `__init__(self, avbtool_script: Path, python_exe: str | None = None)`.
  - Each method builds arg list, calls `subprocess.run([python, script] + args, ...)`.
  - Returns `AvbToolResult`.
  - Command summary sanitizes key paths (redacts in logs).
  - Timeout handling (configurable, default 300s per call).

**2.3 `infrastructure/avbtool/output_parser.py`**
- `parse_info_image(text: str) -> dict[str, Any]`: indentation-based parser.
  - Returns `{"header": {...}, "descriptors": [{"type": str, "fields": dict}], "props": [(k,v)]}`.
  - Pure function, no I/O.

**2.4 `infrastructure/avbtool/command_builder.py`**
- `build_inspect_command(image_path: Path) -> list[str]`.
- `build_erase_footer_command(image_path: Path) -> list[str]`.
- `build_hash_footer_command(step: SigningStep) -> list[str]`.
- `build_hashtree_footer_command(step: SigningStep) -> list[str]`.
- `build_vbmeta_command(step: SigningStep) -> list[str]`.
- `build_extract_public_key_command(key_path: Path, output_path: Path) -> list[str]`.
- All return arg lists (without python + script prefix).

**Tests:**
- `tests/unit/test_output_parser.py`: contract tests against fixture files (hash, hashtree, vbmeta no descriptors, vbmeta with chains, empty, blank lines).
- `tests/unit/test_command_builder.py`: deterministic output, no key material in inspect commands.

---

### Phase 3: Infrastructure — Filesystem & Config

**Goal:** Workspace, profile repository, key repository, atomic writer, FEC.

Tasks:

**3.1 `infrastructure/filesystem/workspace.py`**
- `WorkspacePaths` frozen dataclass: `root`, `profiles_dir`, `active_profile_link`, `logs_dir`, `staging_dir`, `avbtool_script`.
- `WorkspacePaths.discover(root: Path | None = None) -> WorkspacePaths`: resolve from given path or `cwd`.
- `resolve_profile_dir(profile_id: str) -> Path`.
- `resolve_image_path(image_name: str, profile_dir: Path) -> Path` with path-escape guard.
- `ensure_dirs()`: create runtime directories.

**3.2 `infrastructure/filesystem/atomic_writer.py`**
- `AtomicWriter` context manager.
  - `__init__(self, target_dir: Path, staging_dir: Path)`.
  - On enter: creates temp staging subdirectory.
  - Provides `write(filename, data)` that writes to staging.
  - On exit (success): `os.replace()` each file from staging to target.
  - On exit (exception): cleans up staging, target unchanged.
  - Handles cross-device moves (copy + delete fallback for Windows).

**3.3 `infrastructure/persistence/profile_codec.py`**
- `encode_profile(profile: AvbProfile) -> dict`: domain model to v2 JSON dict.
- `decode_profile(data: dict) -> AvbProfile`: v2 JSON dict to domain model. Raises `ConfigError` on invalid schema.
- `PROFILE_JSON_SCHEMA_V2`: dict literal for validation reference.
- Deterministic key ordering on encode.

**3.4 `infrastructure/persistence/profile_repository.py`**
- `ProfileRepository`.
  - `__init__(self, workspace: WorkspacePaths)`.
  - `load(profile_id: str) -> AvbProfile`.
  - `save(profile: AvbProfile) -> None`: atomic write.
  - `list_profiles() -> tuple[str, ...]`.
  - `delete(profile_id: str) -> None`.
  - `activate(profile_id: str) -> None`: update `active_profile_link`.
  - `get_active_profile_id() -> str | None`.

**3.5 `infrastructure/persistence/key_repository.py`**
- `KeyRepository`.
  - `__init__(self, profile_dir: Path)`.
  - `load_manifest() -> dict[KeyId, KeyEntry]`: read `keys/manifest.json`.
  - `save_manifest(manifest: dict) -> None`.
  - `resolve_key_path(key_id: KeyId) -> Path`: return private key file path.
  - `discover_keys() -> list[tuple[str, Path]]`: scan `*.pem` in key dir.
  - `generate_manifest_from_files() -> dict`: build manifest by scanning files and extracting public keys via avbtool.

**3.6 `infrastructure/persistence/archive_repository.py`**
- `ArchiveRepository`.
  - `export_profile(profile_id: str, output_path: Path) -> None`: create ZIP with `manifest.json`, profile.json, key files.
  - `import_profile(archive_path: Path, new_profile_id: str | None = None) -> str`: extract, validate manifest, import. Returns profile_id.
  - `validate_archive(archive_path: Path) -> list[OperationIssue]`: check manifest, file integrity.
  - Archive `manifest.json` format:
    ```json
    {
      "format_version": 1,
      "profile_id": "example",
      "schema_version": 2,
      "files": [
        {"path": "profile.json", "sha256": "..."},
        {"path": "keys/testkey.pem", "sha256": "..."}
      ]
    }
    ```

**3.7 `infrastructure/fec/encoder.py`**
- Copy from old project's `FecEncoder.py`, adapt to new logging.
- `calc_fec_data_size(image_size: int, num_roots: int) -> int`.
- `generate_fec_data(image_filename: str, num_roots: int) -> bytes`.
- Priority: external `fec` binary > numpy > reedsolo.

**3.8 avbtool.py patch**
- In `generate_fec_data()` function (~line 4380 of avbtool.py), after the existing `fec` binary check, add:
  ```python
  # PATCH: AVBPowerTool2 — fallback to Python FEC encoder
  try:
      from avbpowertool.vendor.fec_encoder import generate_fec_data as _py_fec
      return _py_fec(image_filename, num_roots)
  except ImportError:
      pass
  ```
- Similarly for `calc_fec_data_size()`.

**Tests:**
- `tests/unit/test_profile_codec.py`: round-trip encode/decode, invalid schema detection.
- `tests/unit/test_profile_repository.py`: save/load/list/delete/activate in tmp workspace.
- `tests/unit/test_key_repository.py`: manifest load/save, key resolution, discovery.
- `tests/unit/test_archive_repository.py`: export/import round-trip, invalid archive rejection, path traversal rejection.
- `tests/unit/test_atomic_writer.py`: success commits files, failure leaves target clean, cross-device.
- `tests/unit/test_workspace.py`: discover, resolve paths, path escape guard, ensure_dirs.

---

### Phase 4: Application Layer (Use Cases)

**Goal:** All use cases callable from Python code, no CLI/TUI dependency.

Tasks:

**4.1 `application/commands.py`**
- Request/result frozen dataclasses for each use case:
  - `InspectImagesRequest` / `InspectImagesResult`
  - `SignImagesRequest` / `SignImagesResult`
  - `ConfigShowRequest` / `ConfigShowResult`
  - `ConfigValidateRequest` / `ConfigValidateResult`
  - `ProfileListRequest` / `ProfileListResult`
  - `ProfileActivateRequest` / `ProfileActivateResult`
  - `ConfigImportRequest` / `ConfigImportResult`
  - `ConfigExportRequest` / `ConfigExportResult`

**4.2 `application/events.py`**
- Progress event types:
  - `PlanCreated(plan: SigningPlan)`
  - `StepStarted(step: SigningStep, index: int, total: int)`
  - `StepCompleted(step: SigningStep, success: bool)`
  - `SigningCompleted(success_count: int, fail_count: int, skip_count: int)`

**4.3 `application/services/inspect_images.py`**
- `InspectImagesUseCase(workspace, avb_tool)`.
- `execute(request) -> InspectImagesResult`.
- For each image: resolve path, run `avbtool info_image`, parse output, build `ImageInspection`.
- Non-vbmeta images get `ImageInspection` with descriptor type, partition name, etc.
- vbmeta images get `ImageInspection` with chain/hash/hashtree info.
- Errors become `OperationIssue`, never raise to caller.

**4.4 `application/services/sign_images.py`**
- `SignImagesUseCase(workspace, avb_tool, progress_sink)`.
- `execute(request: SignImagesRequest) -> SignImagesResult`:
  1. Load active profile.
  2. Build `SigningPlan` via `SigningPlanBuilder`.
  3. If `dry_run`: return plan only.
  4. If `remove_existing_footers`: erase footers first.
  5. Execute steps in order using staging directory.
  6. For each step: emit `StepStarted`, run avbtool, emit `StepCompleted`.
  7. On all success: atomic replace from staging to target.
  8. On partial failure: report which succeeded/failed, staging remains for inspection.
  9. Emit `SigningCompleted`.

**4.5 `application/services/manage_configs.py`**
- `ConfigShowUseCase(workspace) -> ConfigShowResult`: load profile, present typed partitions.
- `ConfigValidateUseCase(workspace) -> ConfigValidateResult`: check all images exist, all keys exist.
- `ConfigImportUseCase(workspace, archive_repo)`: import from ZIP.
- `ConfigExportUseCase(workspace, archive_repo)`: export to ZIP.

**4.6 `application/services/manage_profiles.py`**
- `ProfileListUseCase(workspace) -> ProfileListResult`: list all profiles, indicate active.
- `ProfileActivateUseCase(workspace)`: activate a profile by ID.

**4.7 `application/services/manage_keys.py`**
- `KeyDiscoveryUseCase(workspace)`: scan key dir, generate/update manifest.
- `KeyValidationUseCase(workspace)`: verify all key_ids in profile exist in manifest and on disk.

**Tests:**
- `tests/integration/test_inspect_images.py`: with `FakeAvbTool`, verify correct parsing and issue generation.
- `tests/integration/test_sign_images.py`: with `FakeAvbTool`, verify plan generation, step ordering, staging, dry-run.
- `tests/integration/test_manage_configs.py`: config show/validate with fixture profiles.
- `tests/integration/test_manage_keys.py`: key discovery with fixture key files.
- `tests/integration/test_manage_profiles.py`: list/activate cycle.

---

### Phase 5: CLI

**Goal:** Full CLI with subcommands, `--json` output, stable exit codes.

Tasks:

**5.1 `presentation/actions.py`**
- `ActionId(str, Enum)`:
  ```
  IMAGE_READ_INFO = "image.read_info"
  IMAGE_SIGN = "image.sign"
  CONFIG_SHOW = "config.show"
  CONFIG_VALIDATE = "config.validate"
  CONFIG_IMPORT = "config.import"
  CONFIG_EXPORT = "config.export"
  CONFIG_ACTIVATE = "config.activate"
  CONFIG_LIST = "config.list"
  SETTINGS_VIEW = "settings.view"
  SETTINGS_EDIT = "settings.edit"
  SETTINGS_CHECK_L10N = "settings.check_l10n"
  VIEW_CURRENT_CONFIG = "view_current_config"
  ```
- `ActionRegistry`: maps `ActionId` to handler callable. Startup validation: every ID in navigation.json exists in registry, every localized key exists in default `.po`.

**5.2 `presentation/cli/parser.py`**
- argparse tree:
  ```
  avbpowertool image inspect [IMAGE...]
  avbpowertool image sign [IMAGE...] [--dry-run] [--remove-footers] [--yes] [--json]
  avbpowertool config show [--json]
  avbpowertool config validate [--json]
  avbpowertool config list [--json]
  avbpowertool config activate PROFILE [--json]
  avbpowertool config import ARCHIVE [--json]
  avbpowertool config export PROFILE [--output PATH] [--json]
  avbpowertool settings view
  avbpowertool settings check-l10n
  avbpowertool about
  ```
- Old command aliases with deprecation warnings:
  ```
  avbpowertool read   -> avbpowertool image inspect
  avbpowertool sign   -> avbpowertool image sign
  avbpowertool get_all_config -> avbpowertool config list
  avbpowertool check_l10n     -> avbpowertool settings check-l10n
  ```
- If no command given: launch TUI (Phase 6).

**5.3 `presentation/cli/handlers.py`**
- Each handler:
  1. Builds typed request from args.
  2. Creates workspace and use case via composition root.
  3. Calls use case.
  4. Renders result (text or JSON).
  5. Returns exit code.

**5.4 `presentation/cli/renderer.py`**
- `render_inspect_result(result, as_json) -> str`.
- `render_signing_result(result, as_json) -> str`.
- `render_config_show(result, as_json) -> str`.
- `render_profile_list(result, as_json) -> str`.
- Exit codes: 0 = success, 1 = input invalid, 2 = environment missing, 3 = operation failed, 4 = partial success.

**5.5 `pyproject.toml` entry point**
```toml
[project.scripts]
avbpowertool = "avbpowertool.presentation.cli.parser:main"
```

**Tests:**
- `tests/integration/test_cli_contract.py`:
  - `avbpowertool --help` exits 0.
  - `avbpowertool image inspect --help` exits 0.
  - `avbpowertool image inspect boot --json` with fixture workspace returns valid JSON.
  - Deprecated aliases emit warnings.
  - Exit codes match spec.

---

### Phase 6: TUI

**Goal:** curses-based interactive mode preserving old navigation experience.

Tasks:

**6.1 `presentation/tui/router.py`**
- `NavigationNode` dataclass: `id`, `title_key`, `description_key`, `items`, `parent`.
- `Router`:
  - `__init__(self, nav_file: Path)`: load and validate `navigation.json`.
  - `current_route() -> NavigationNode`.
  - `push(route_id: str)`: navigate deeper.
  - `pop()`: go back to parent.
  - `get_items() -> list[NavigationItem]`: items for current route, with resolved localized labels.
  - `validate()`: check all routes/actions referenced exist.

**6.2 `presentation/tui/widgets.py`**
- `SelectorWidget`: curses-based single/multi selector with keyboard navigation (up/down/enter/escape/space).
  - Infinite scroll (wrap around).
  - Visual indicators: `->` cursor, `[x]` / `[ ]` for multi-select.
  - Title bar, instruction bar, status bar.
- `ConfirmWidget`: Yes/No dialog.
- `InputWidget`: Text input field.
- `MessageWidget`: Scrollable message display.
- `ProgressWidget`: Step progress display.

**6.3 `presentation/tui/app.py`**
- `App`:
  - `__init__(self, workspace, router, use_cases)`.
  - `run()`: main curses loop.
  - Route rendering: for route nodes, show selector with items.
  - Action dispatch: when user selects an action item, call the corresponding view.
  - Back/Exit handling: `B` pops route stack, `E` (on root) exits.
  - Screen clearing between pages.

**6.4 Views (`presentation/tui/views/`)**
Each view is a function or class that:
1. Receives the curses `stdscr`, workspace, and use cases.
2. Renders its UI using widgets.
3. Calls use cases.
4. Returns to router when done.

- **`home.py`**: No special view (router handles the menu).
- **`read_image_info.py`**: Multi-select images from `Images/` dir, call `InspectImagesUseCase`, display results.
- **`config_manager.py`**: No special view (router handles the sub-menu).
- **`import_config.py`**: File selector for `.zip` files, call `ConfigImportUseCase`, show result.
- **`export_config.py`**: Profile selector, call `ConfigExportUseCase`, show result.
- **`config_library.py`**: Profile list with actions (activate, rename, delete), call `ProfileActivateUseCase` etc.
- **`sign_images.py`**: Multi-select images, confirm dialog, call `SignImagesUseCase`, show progress and result.
- **`settings.py`**: Settings list with edit/view/check-l10n actions.
- **`display_avb_info.py`**: Show current config info using `ConfigShowUseCase`.

**6.5 i18n (`locale/`)**
- Generate `.pot` template from all `_("...")` calls in code.
- Create `en/LC_MESSAGES/avbpowertool.po` (default).
- Create `zh/LC_MESSAGES/avbpowertool.po` (translated from old `strings.xml`).
- Compile `.po` to `.mo` at build time.
- Initialization: `gettext.bindtextdomain('avbpowertool', locale_dir)`, `gettext.textdomain('avbpowertool')`.
- Use `_()` function throughout presentation layer.
- The `settings view` command lists current settings.
- The `settings check-l10n` command compares `.po` files for missing translations.

**6.6 Composition root**
- `presentation/__init__.py` or a `bootstrap.py` module.
- Creates `WorkspacePaths`, `SubprocessAvbTool`, all repositories, all use cases.
- CLI handler and TUI `App` both use this composition root.
- No global singletons; everything wired at startup.

**Tests:**
- `tests/integration/test_tui_router.py`:
  - Navigation tree loads and validates.
  - Every action referenced in routes exists in `ActionId`.
  - Push/pop navigation works.
  - Back on root triggers exit.
- `tests/contract/test_navigation_schema.py`:
  - All `title_key` values exist in default `.po` file.
  - All shortcuts unique within each route.
  - No orphan routes (unreachable from root).
  - No dead references (routes/actions that don't exist).

---

## 6. Dependency Summary

### Required (pyproject.toml `[project.dependencies]`)
```
# none — stdlib only for core functionality
```

### Optional
```toml
[project.optional-dependencies]
windows = ["windows-curses"]
dev = ["pytest>=7", "ruff", "pyright"]
fec = ["numpy>=1.20,<3.0", "reedsolo>=1.7,<3.0"]
```

Note: `numpy` + `reedsolo` are needed for FEC encoding on platforms where the `fec` binary is unavailable. They should be optional deps with graceful fallback.

### Build
```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
```

---

## 7. Implementation Order Summary

```
Phase 0  Project skeleton, avbtool.py patch, test infra          ~0.5 day
Phase 1  Domain models, validation, signing plan, dep graph      ~1 day
Phase 2  avbtool adapter (runner, parser, command builder)        ~1 day
Phase 3  Filesystem & config (workspace, profiles, keys, FEC)    ~1.5 days
Phase 4  Application use cases (inspect, sign, config, keys)     ~1.5 days
Phase 5  CLI (argparse, handlers, renderer, old aliases)          ~1 day
Phase 6  TUI (curses, router, widgets, views, i18n)              ~2 days
─────────────────────────────────────────────────────────────────
Total                                                            ~8.5 days
```

---

## 8. Quality Gates (per phase)

Every phase must pass before the next begins:

1. `ruff check` — zero warnings
2. `pyright` — zero errors in `avbpowertool/`
3. `pytest` — all tests pass
4. `pytest --cov=avbpowertool --cov-report=term-missing` — domain/application coverage ≥ 90%
5. Navigation schema contract test (Phase 6)
6. i18n completeness check (Phase 6)
