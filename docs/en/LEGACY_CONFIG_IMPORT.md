# Implementation Plan: v1 Config Import in the v2 TUI Settings Page (auto-convert to v2) + v2 NONE signing support

> Status: ✅ implemented (see the section 10 order)  ·  Target schema_version: 2  ·  Reference code: `references/AVBPowerTool/`

## 1. Goals & Locked Decisions

1. **Integration point**: add a dedicated action `action:settings.import_legacy` (shortcut `I`) to the v2 TUI **Settings page** (`route:settings`) that imports v1 (AVBPowerTool 1.x) config ZIP archives and **automatically converts them to v2**.
2. **NONE algorithm**: make v2 fully support `SigningAlgorithm.NONE` (unsigned footers / no-key signing), because real v1 configs use `Algorithm: NONE` extensively (10 of 15 partitions in the `ZUXOS_411` sample).
3. The existing v2 import path (`action:config.import` / `ConfigImportUseCase` / `ArchiveRepository`) **stays v2-only and untouched**; the new feature uses a separate pipeline.

## 2. Prerequisite: v2 NONE signing support

The vendored `avbtool.py` confirms: `--algorithm` defaults to `NONE`, `--key` is optional, and when the algorithm is `NONE` hash/signature computation is skipped (`if algorithm_name != 'NONE'` in `generate_vbmeta_blob`). So "NONE signing" = **omit `--algorithm` and `--key`** from footer/vbmeta commands (hash/hashtree still pass `--hash_algorithm`), matching v1 behavior.

### 2.1 `domain/validation.py`
- Add `SigningAlgorithm.NONE` to `_VALID_SIGNING_ALGORITHMS` (valid for hash/hashtree/vbmeta).
- `validate_partition`: require a non-empty `key_id` only when `algorithm != NONE` (currently it unconditionally reports `config.key_missing`); allow `key_id == ""` for NONE partitions.
- Keep the `config.vbmeta_no_contents` rule (a NONE vbmeta still needs included/chain contents).

### 2.2 `domain/signing_plan.py` (the actual execution path)
- `_build_non_vbmeta_step`: when `algorithm == NONE`, skip `_resolve_key_path` (`key_path = None`); otherwise as today.
- `_build_hash_command` / `_build_hashtree_command`: `key_path: Path | None = None`; append `--algorithm`/`--key` only when non-NONE and `key_path` is present; always append `--hash_algorithm` (NONE partitions must pass `sha256` explicitly to avoid avbtool's sha1-fallback warning).
- `_build_vbmeta_step`: same — `key_path = None` and omit `--algorithm`/`--key` when NONE; everything else (`--rollback_index`, flags, included, chain, props) unchanged.
- **Fix a latent v2 gap — chain public-key path resolution**: in `_build_vbmeta_step`, for each `chain_partitions` entry, if the third field (public key file) is not absolute, resolve it against `self._key_dir` and rebuild the `"name:loc:resolved_keyfile"` entry. This makes converted `"boot:3:testkey_rsa4096_pub.bin"` entries resolvable.

### 2.3 `application/ports.py` + `infrastructure/avbtool/runner.py`
- Change `key_path: Path` to `key_path: Path | None = None` on `add_hash_footer` / `add_hashtree_footer` / `make_vbmeta_image`.
- In the runner, append `--algorithm <alg> --key <path>` only when `key_path is not None`; omit both for NONE (identical to v1).

### 2.4 `infrastructure/avbtool/command_builder.py`
- `build_hash_footer_command` / `build_hashtree_footer_command` / `build_vbmeta_command`: make `key_path` optional and omit `--algorithm`/`--key` for NONE (module is exercised by unit tests; keep it consistent).

### 2.5 `tests/conftest.py` `FakeAvbTool`
- Update the three method signatures to `key_path: Path | None = None` (it only records calls; no logic change).

### 2.6 Verification
- `uv run pytest tests/unit/test_validation.py tests/unit/test_signing_plan.py tests/unit/test_runner.py tests/unit/test_command_builder.py tests/integration/test_sign_images.py -q`

## 3. New: v1 → v2 conversion codec

### New file `avbpowertool/infrastructure/persistence/v1_profile_codec.py`
(Same layer as `profile_codec.py`; pure functions first, I/O confined to the unpack function.)

```python
V1_ARCHIVE_FLAG = "this_is_a_config_file_of_avbpowertool"
V1_BATCH_FLAG = "BATCH_CONFIG_AVBPOWERTOOL"
V1_RENAME_FLAG = "RENAME_REQUIRED"

def detect_v1_archive(archive_path: Path) -> str:
    """Returns "single" | "batch" | "none" (detected from flag files inside the zip)."""

def extract_v1_archive(archive_path: Path, staging_dir: Path) -> Path:
    """Validate path safety (reuse the _validate_archive_path approach) then unpack;
    returns the dir containing Configs/ and Keys/. Batch archives are intercepted upstream."""

def decode_v1_image_info(raw: dict[str, Any], config_id: str) -> tuple[AvbProfile, list[OperationIssue]]:
    """Pure conversion of a v1 imageInfo.json dict into a v2 AvbProfile (with warning issues)."""

def build_key_manifest(keys_dir: Path, key_cache: Path | None) -> tuple[dict[str, dict[str, str]], list[OperationIssue]]:
    """Scan *.pem -> manifest; read keyCache.cache to fill public_key_sha1; copy _pub.bin as public_key."""
```

### 3.1 v1 → v2 field mapping

| v1 (imageInfo.json entry) | v2 `PartitionConfig` | Notes |
|---|---|---|
| entry key / `Partition Name` | partitions key + `partition_name` | prefer `Partition Name` |
| `Image File` | `image` | |
| filename contains `vbmeta` OR entry has `Chain` key → VBMETA; else `Descriptor Type` | `descriptor` | v1 vbmeta entries have no `Descriptor Type`; heuristic detection |
| `Algorithm` | `algorithm` | `NONE` → `SigningAlgorithm.NONE` (now supported by v2) |
| `Public key file` (strip `.pem`) | `key_id` | `NOT_FOUND`/missing → warn `import.legacy.key_not_found` |
| `Rollback Index` (string) | `rollback_index: int` | |
| `Salt` | `salt` | |
| `Flags` (string) | `flags: int` | |
| `Props` (dict) | `props: tuple[tuple[str,str], ...]` | |
| `Hash Algorithm` | `hash_algorithm` | default `sha256` |
| `Data Block Size` / `Hash Block Size` (strip `" bytes"`) | `data_block_size` / `hash_block_size` | default 4096 |
| vbmeta: `Hash` + `Hashtree` concatenated | `included_partitions` | |
| vbmeta: `Chain[i]` + `Chain partition key[i]` | `chain_partitions` → `f"{name}:{loc}:{pubbin}"` | complete the partial v1 triple into a v2 triple; length mismatch → warn `import.legacy.partial_chain` |
| `Root Digest`, `Version of dm-verity`, `Image size` | (no v2 field; dropped) | informational only; `Image size` — see §9 |

### 3.2 Keys & manifest
- Copy all `*.pem` from v1 `Keys/` into `profiles/<id>/keys/`; copy `_pub.bin` files too.
- `manifest`: `key_id = pem name minus .pem` → `{"private_key": "...", "public_key": "..._pub.bin", "public_key_sha1": "..."}` (sha1 from `keyCache.cache`, empty if missing).
- Output shape matches v2 `KeyDiscoveryUseCase`, so the imported profile can be re-checked via the Manage Keys page.

### 3.3 Config name / ID derivation
User-supplied `new_profile_id` → v1 `config_info.cfg` `name` → zip filename minus `.zip`; sanitize (strip illegal chars, avoid overwriting existing profiles). `config.cfg`/`config_info.cfg` are **not required** (absent in the real sample).

## 4. New: `LegacyConfigImportUseCase` (application layer)

### `application/commands.py`
```python
@dataclass(frozen=True)
class LegacyImportRequest:
    archive_path: str
    new_profile_id: str | None = None
    activate: bool = True

@dataclass(frozen=True)
class LegacyImportResult:
    profile_id: str
    partition_count: int
    key_count: int
    issues: tuple[OperationIssue, ...] = ()
```

### `application/services/manage_configs.py`
Add `LegacyConfigImportUseCase.execute()`:
1. `detect_v1_archive` → anything but `single` returns `config.invalid_archive` (clear message for batch packages).
2. `extract_v1_archive` into `ws.staging` (reuse path-traversal checks).
3. Read `Configs/imageInfo.json` + `Keys/`; `decode_v1_image_info` + `build_key_manifest` produce `AvbProfile` + manifest (collect conversion warnings).
4. Target-id conflict → `config.profile_exists` (or auto-suffix; UI decision).
5. `ProfileRepository.save(profile)`; copy pem/pub.bin; `KeyRepository.save_manifest`; `ProfileRepository.activate` if requested.
6. Return `LegacyImportResult` (partition/key counts + issues). Clean up staging on failure.

## 5. TUI Settings page integration

### 5.1 `resources/navigation.json`
- Append `{"action": "action:settings.import_legacy", "shortcut": "I"}` to `route:settings.items` (E/V/C/I are unique within settings).
- Add to `actions`:
```json
"action:settings.import_legacy": {
  "label_key": "settings.action.import_legacy",
  "description_key": "settings.action.import_legacy_description"
}
```

### 5.2 `presentation/tui/views/settings.py`
Add `show_import_legacy(stdscr, ws, avb)`; interaction flow (reuse existing widgets, modeled on `import_config.show`):
1. Scan root for `*.zip`; if none → `message_screen` and return.
2. `SelectorWidget` to pick an archive.
3. `input_prompt` for new profile id (Enter = derive from archive name); then `input_prompt` for display name (Enter = use id).
4. `confirm_dialog` to confirm convert-and-import (optionally ask about activation).
5. Call `LegacyConfigImportUseCase` → `message_screen` showing imported id, partition/key counts, and all issues.

### 5.3 `presentation/tui/app.py`
Register `"action:settings.import_legacy": settings.show_import_legacy` in `view_map`.

### 5.4 i18n (`avbpowertool.po` in `locale/en` and `locale/zh`)
`settings.action.import_legacy`, `settings.action.import_legacy_description`, `settings.import_legacy.title`, `settings.import_legacy.select_archive`, `settings.import_legacy.enter_profile_id`, `settings.import_legacy.enter_profile_name`, `settings.import_legacy.confirm`, `settings.import_legacy.activate`, `settings.import_legacy.success`, `settings.import_legacy.failed`, `settings.import_legacy.not_legacy`, `settings.import_legacy.batch_not_supported`, `settings.import_legacy.no_zip_found`, `settings.import_legacy.key_not_found`, `settings.import_legacy.partial_chain`, `settings.import_legacy.profile_exists`, etc.

## 6. CLI (optional, recommended)

- `ActionId.CONFIG_IMPORT_LEGACY = "config.import_legacy"` in `presentation/actions.py`.
- `parser.py`: `config import-legacy <archive> [--profile ID] [--name NAME] [--no-activate] [--json]`.
- `handlers.py` + `renderer.py` reuse the same use case, giving TUI/CLI/API parity.

## 7. Test plan

- **unit `tests/unit/test_v1_profile_codec.py`**: use `tests/fixtures/legacy/` (static copy of `references/AVBPowerTool/Configs/ZUXOS_411/`; tests must **not** read references directly) to assert: per-partition field mapping, vbmeta `included_partitions`/`chain_partitions` completion, NONE conversion, `NOT_FOUND` key warning, `Data/Hash Block Size` suffix stripping, and `Chain` length-mismatch warning.
- **unit `tests/unit/test_legacy_archive.py`**: flag-file detection (single/batch/none) and path-traversal rejection.
- **unit extensions**: `test_validation.py` (NONE valid; no key_id required), `test_signing_plan.py` (NONE commands omit `--algorithm`/`--key`; chain public-key resolved against key_dir), `test_runner.py` / `test_command_builder.py` (NONE command shape).
- **integration `tests/integration/test_legacy_import.py`**: build a v1 zip (`Configs/`+`Keys/`+flag) → run the use case → assert `profiles/<id>/profile.json` round-trips through `decode_profile`, pem/pub.bin copied, manifest correct, activation works; and that the same v1 zip is rejected by the existing `ConfigImportUseCase` (proving the two paths don't interfere).
- **contract**: existing `tests/contract/test_navigation_schema.py` covers the new nav item.
- **manual**: `uv run avbpowertool` → Settings → import v1 zip → review result/issues; `uv run avbpowertool config import-legacy ...` (if CLI is implemented).

## 8. Acceptance pipeline (per AGENTS.md)

```
1. Edit code
2. uv run pytest tests/
3. uv run ruff check avbpowertool
4. uv run ruff format avbpowertool
5. uv run pyright avbpowertool
6. git add + git commit
```

## 9. Known limitations (recorded; out of scope for this iteration)

- **`--partition_size` (v1 `Image size`)**: v2 `PartitionConfig` has no such field, so it is not preserved; v2 signing does not pass `--partition_size`. Could be a follow-up enhancement.
- **v1 BATCH archives**: this iteration's Settings-page import supports single-config packages only; batch packages are rejected with a clear message.
- **`config.cfg` / `config_info.cfg` / `imageList.txt`**: not required; name fallback chain per §3.3; `imageList.txt` is not migrated (v2 uses the partitions dict).
- **vbmeta detection**: heuristic based on "filename contains `vbmeta`" or "entry has a `Chain` key".
- **Archive picking**: follows the existing import view's pattern of scanning project-root `*.zip` files only.
- **Conversion is non-destructive**: it only reads the v1 package and writes a new profile directory; it never modifies the v1 source.

## 10. Implementation order (Definition of Done)

1. NONE support (§2.1–§2.5) → related tests green.
2. v1 codec (§3) → unit tests green.
3. `LegacyConfigImportUseCase` + commands (§4) → integration tests green.
4. TUI Settings integration (§5: nav / view / app / i18n).
5. CLI (§6, optional).
6. Docs updates (README, `docs/en|zh/CONFIG_CREATION.md` noting NONE support and legacy import).
7. Full pipeline (§8) green, then commit.
