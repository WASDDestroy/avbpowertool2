# Backend API Reference

Use the AVBPowerTool2 backend directly from Python without going through CLI or TUI.

## Installation

```python
from avbpowertool.bootstrap import bootstrap
```

## Quick Start

```python
from pathlib import Path
from avbpowertool.bootstrap import bootstrap
from avbpowertool.infrastructure.avbtool.runner import SubprocessAvbTool
from avbpowertool.application.commands import InspectImagesRequest, SignImagesRequest
from avbpowertool.application.services.inspect_images import InspectImagesUseCase
from avbpowertool.application.services.sign_images import SignImagesUseCase

# Initialize workspace
ws = bootstrap(root=Path("/path/to/project"))
avb = SubprocessAvbTool(ws.avbtool_script)

# Inspect an image
uc = InspectImagesUseCase(ws, avb)
result = uc.execute(InspectImagesRequest(image_names=("boot", "vbmeta")))
for img in result.images:
    print(f"{img.image_name}: {img.descriptor}, {img.algorithm}")

# Sign images (dry-run)
uc = SignImagesUseCase(ws, avb)
result = uc.execute(SignImagesRequest(image_names=("boot",), dry_run=True))
print(f"Plan: {len(result.plan.steps)} steps")
```

## Workspace

```python
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths

# Auto-discover from cwd
ws = WorkspacePaths.discover()

# Explicit root
ws = WorkspacePaths.discover(Path("/my/project"))

# Key paths
ws.root                        # Path: project root
ws.profiles                    # Path: profiles/ directory
ws.resolve_profile_dir("test") # Path: profiles/test/
ws.resolve_key_dir("test")     # Path: profiles/test/keys/
ws.staging                     # Path: .avbpowertool-staging/
ws.avbtool_script              # Path: avbtool.py
ws.ensure_dirs()               # Create runtime directories
```

## Use Cases

### InspectImagesUseCase

Read AVB metadata from image files.

```python
from avbpowertool.application.commands import InspectImagesRequest

uc = InspectImagesUseCase(ws, avb)
result = uc.execute(InspectImagesRequest(
    image_names=("boot", "system", "vbmeta"),
    profile_id="current",  # optional, default "current"
))

# Result
result.images   # tuple[ImageInspection, ...]
result.issues   # tuple[OperationIssue, ...]
```

**ImageInspection fields:**
- `image_name: str` — logical name
- `image_path: str` — resolved path
- `descriptor: DescriptorType | None` — HASH, HASHTREE, VBMETA, or None
- `algorithm: str | None` — e.g. "SHA256_RSA4096"
- `partition_name: str | None`
- `public_key_sha1: str | None`
- `rollback_index: str | None`
- `salt: str | None`
- `digest: str | None`
- `flags: str | None`
- `props: tuple[tuple[str, str], ...]`
- `raw_extensions: tuple[tuple[str, str], ...]`

### SignImagesUseCase

Sign images with staging and atomic replace.

```python
from avbpowertool.application.commands import SignImagesRequest

uc = SignImagesUseCase(ws, avb)

# Dry-run (plan only)
result = uc.execute(SignImagesRequest(
    image_names=("boot", "vbmeta"),
    profile_id="current",
    dry_run=True,
))

# Execute signing
result = uc.execute(SignImagesRequest(
    image_names=("boot", "vbmeta"),
    profile_id="current",
    dry_run=False,
    remove_existing_footers=False,
))

# Result
result.plan           # SigningPlan
result.executed       # bool
result.success_count  # int
result.fail_count     # int
result.issues         # tuple[OperationIssue, ...]
```

**SigningPlan fields:**
- `profile_id: str`
- `steps: tuple[SigningStep, ...]`
- `vbmeta_order: tuple[str, ...]`
- `issues: tuple[OperationIssue, ...]`

**SigningStep fields:**
- `partition_name: str`
- `operation: str` — "add_hash_footer", "add_hashtree_footer", "make_vbmeta_image"
- `command: tuple[str, ...]` — avbtool arg list
- `input_path: str`
- `output_path: str`
- `order: int`

### ConfigShowUseCase

Show the active configuration.

```python
from avbpowertool.application.commands import ConfigShowRequest

uc = ConfigShowUseCase(ws)
result = uc.execute(ConfigShowRequest(profile_id="current"))

result.config_name  # str
result.partitions   # tuple[PartitionConfig, ...]
result.issues       # tuple[OperationIssue, ...]
```

### ConfigValidateUseCase

Validate config against workspace images and keys.

```python
from avbpowertool.application.commands import ConfigValidateRequest

uc = ConfigValidateUseCase(ws)
result = uc.execute(ConfigValidateRequest(profile_id="current"))

result.missing_images  # tuple[str, ...]
result.missing_keys    # tuple[str, ...]
result.issues          # tuple[OperationIssue, ...]
```

### ConfigImportUseCase / ConfigExportUseCase

```python
from avbpowertool.application.commands import ConfigImportRequest, ConfigExportRequest

# Import
uc = ConfigImportUseCase(ws)
result = uc.execute(ConfigImportRequest(archive_path="/path/to/archive.zip"))
result.profile_id  # str

# Export
uc = ConfigExportUseCase(ws)
result = uc.execute(ConfigExportRequest(
    profile_id="myprofile",
    output_path="/path/to/output.zip",  # optional
))
result.output_path  # str
```

### ProfileListUseCase / ProfileActivateUseCase

```python
from avbpowertool.application.commands import ProfileListRequest, ProfileActivateRequest

# List
uc = ProfileListUseCase(ws)
result = uc.execute(ProfileListRequest())
for p in result.profiles:
    print(f"{p.profile_id}: {p.name} (active={p.is_active}, {p.partition_count} partitions)")

# Activate
uc = ProfileActivateUseCase(ws)
result = uc.execute(ProfileActivateRequest(profile_id="myprofile"))
```

### KeyDiscoveryUseCase

Discover .pem files and update manifest.

```python
from avbpowertool.application.commands import KeyDiscoveryRequest

uc = KeyDiscoveryUseCase(ws)
result = uc.execute(KeyDiscoveryRequest(profile_id="current"))

result.discovered_count   # int
result.manifest_entries   # tuple[tuple[str, str], ...]  (key_id, filename)
```

`KeyDiscoveryRequest(merge=True)` (the default) keeps the cached `public_key` /
`public_key_sha1` entries, but only while an entry still points at the same
`private_key` filename; `merge=False` (the CLI's `--replace`) rebuilds the
manifest from scratch and drops the cache. The result also carries
`retained_count` (kept entries with no matching `.pem`) and `merged`.

### KeyEnsurePublicUseCase

Materialises the missing public-key files (`<private_key>.pem.bin`) and writes
`public_key` back into the manifest. Needs an `AvbToolPort`.

```python
from avbpowertool.application.commands import KeyEnsurePublicRequest
from avbpowertool.application.services.manage_keys import KeyEnsurePublicUseCase

uc = KeyEnsurePublicUseCase(ws, avb)
result = uc.execute(KeyEnsurePublicRequest(profile_id="current"))

result.extracted  # tuple[tuple[str, str], ...]  (key_id, public-key filename)
result.skipped    # tuple[str, ...]  key_ids skipped because the private key is missing
result.issues     # tuple[OperationIssue, ...]
```

### ConfigAutoCreateUseCase

Scans an image directory → inspects each image with `info_image` → builds the
partition configs. It **never writes to disk**; the create wizard and the CLI's
`config create --from-images` share it.

```python
from avbpowertool.application.commands import ConfigAutoCreateRequest
from avbpowertool.application.services.config_auto_create import ConfigAutoCreateUseCase

uc = ConfigAutoCreateUseCase(ws, avb)
result = uc.execute(ConfigAutoCreateRequest(
    image_dir=ws.images,                 # required
    image_names=("boot", "vbmeta"),      # empty = every *.img in the directory (sorted)
    key_id=None,                         # override the automatic key choice
    available_keys=("mykey_rsa4096",),   # candidates for the automatic choice
    default_key_id="default",
    profile_id="current",                # used for chain resolution
    resolve_chains=True,
    allow_fallback=True,                 # the TUI's historical behaviour; the CLI passes False
))

result.partitions      # tuple[PartitionConfig, ...]
result.scanned_images  # tuple[str, ...]  scanned image stems (sorted)
result.skipped_images  # tuple[str, ...]  images skipped for having no AVB structure
result.chain_issues    # tuple[OperationIssue, ...]  chain-resolution problems (never blocking)
result.issues          # tuple[OperationIssue, ...]  issues from the inspection phase
```

### ConfigCreateFromImagesUseCase

The use case behind `config create --from-images`: scan → build → **write** →
report the still-missing keys. Every early return **leaves the workspace
untouched**. Needs an `AvbToolPort`.

```python
from avbpowertool.application.commands import ConfigCreateFromImagesRequest
from avbpowertool.application.services.config_auto_create import ConfigCreateFromImagesUseCase

uc = ConfigCreateFromImagesUseCase(ws, avb)
result = uc.execute(ConfigCreateFromImagesRequest(
    profile_id="my_device",
    profile_name="",                     # empty -> the profile id
    image_dir=None,                      # None -> the workspace Images/
    image_names=("boot", "vbmeta"),      # empty -> every *.img in the directory
    key_id=None,
    resolve_chains=True,
    allow_fallback=False,                # CLI default; True restores the wizard's "include everything"
    skip_non_avb=False,                  # False makes an image without AVB structure fatal
    overwrite=False,
    activate=False,                      # not activated by default
))

result.created          # bool   whether the profile directory was written
result.partition_count  # int
result.chain_count      # int
result.scanned_images   # tuple[str, ...]
result.skipped_images   # tuple[str, ...]
result.missing_keys     # tuple[str, ...]  informational only, never fails the call
result.chain_issues     # tuple[OperationIssue, ...]  chain-resolution problems (informational, never fails the call)
result.issues           # tuple[OperationIssue, ...]  inspection problems + genuinely fatal errors
```

`ConfigCreateUseCase` covers the empty-profile path; its request additionally has
`allow_empty: bool = False` and `overwrite: bool = False`.

### ProfileRenameUseCase

```python
from avbpowertool.application.commands import ProfileRenameRequest
from avbpowertool.application.services.manage_profiles import ProfileRenameUseCase

uc = ProfileRenameUseCase(ws)
result = uc.execute(ProfileRenameRequest(
    profile_id="old_id",
    new_profile_id="new_id",   # same as profile_id = only change the display name
    new_name="New name",       # None = keep the current name
))

result.old_profile_id  # str
result.profile_id      # str   the new id
result.renamed         # bool  whether the directory was actually moved
result.name_changed    # bool
result.issues          # tuple[OperationIssue, ...]
```

### CheckChainsUseCase

The read-only chain consistency check. Needs an `AvbToolPort` (used to extract a
public key into the staging directory when the manifest has no usable
`public_key` — **never** into the key store).

```python
from avbpowertool.application.commands import CheckChainsRequest
from avbpowertool.application.services.check_chains import CheckChainsUseCase

uc = CheckChainsUseCase(ws, avb)
result = uc.execute(CheckChainsRequest(profile_id="current"))

result.profile_id  # str
result.checked     # int  number of chain entries checked
result.entries     # tuple[ChainCheckEntry, ...]  (partition_name, entry, ok)
result.issues      # tuple[OperationIssue, ...]  including chain.key_mismatch
```

### How `profile_id` is resolved

`profile_id` defaults to `"current"` and is resolved **literal-first**:

1. `profiles/<profile_id>/profile.json` exists → use the literal id;
2. the request is `"current"`/empty and `.active-profile` points at an existing
   profile → use that id;
3. otherwise `config.no_active_profile` (for a current/empty request) or
   `config.not_found`.

Affected use cases: `ConfigShowUseCase`, `ConfigValidateUseCase`,
`ConfigEditUseCase`, `ConfigMigrateUseCase`, `SignImagesUseCase`,
`CheckChainsUseCase`, `ResolveChainKeysUseCase`.

**The key-store use cases resolve leniently**: `KeyListUseCase` /
`KeyDiscoveryUseCase` / `KeyEnsurePublicUseCase` / `KeyAddUseCase` /
`KeyRemoveUseCase` go through `resolve_key_store_profile_id` — the same
literal-first + current→active mapping, but **a non-empty request that cannot be
resolved is used literally** and the use case reports
`keys.directory_not_found` itself. That is what lets the create wizard prepare
`profiles/<id>/keys/` before `profile.json` is written; only an empty request
with no active profile reports `config.no_active_profile` directly.

## Domain Models

### AvbProfile

```python
from avbpowertool.domain.models import AvbProfile, PartitionConfig, DescriptorType, SigningAlgorithm

profile = AvbProfile(
    id="myprofile",
    name="My Profile",
    schema_version=3,
    key_store_path="keys",
    partitions={
        "boot": PartitionConfig(
            image="boot.img",
            descriptor=DescriptorType.HASH,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="release_rsa4096",
            partition_name="boot",
            rollback_index=0,
            salt="abcdef",
            flags=0,
            props=(("key1", "val1"),),
        ),
    },
)
```

### OperationIssue

All use cases return `OperationIssue` tuples instead of raising exceptions.

```python
from avbpowertool.domain.models import OperationIssue

issue = OperationIssue(
    error_code="config.key_missing",
    message="Key 'testkey' not found in manifest",
)
```

## Progress Events

Subscribe to signing progress via a `ProgressSink`:

```python
from avbpowertool.application.ports import ProgressSink, ProgressEvent
from avbpowertool.application.events import StepStarted, StepCompleted, SigningCompleted

class MyProgress:
    def on_event(self, event: ProgressEvent) -> None:
        if isinstance(event, StepStarted):
            print(f"Signing {event.partition_name}...")
        elif isinstance(event, StepCompleted):
            print(f"  {'OK' if event.success else 'FAILED'}")
        elif isinstance(event, SigningCompleted):
            print(f"Done: {event.success_count} ok, {event.fail_count} failed")

uc = SignImagesUseCase(ws, avb, progress=MyProgress())
```

## Direct avbtool Calls

Use `SubprocessAvbTool` directly for raw avbtool operations:

```python
from pathlib import Path
from avbpowertool.infrastructure.avbtool.runner import SubprocessAvbTool

avb = SubprocessAvbTool(ws.avbtool_script)

# Inspect
result = avb.inspect_image(Path("/images/boot.img"))
print(result.stdout)

# Extract public key
result = avb.extract_public_key(
    Path("/keys/test.pem"),
    Path("/keys/test_pub.bin"),
)

# All methods: inspect_image, erase_footer, add_hash_footer,
# add_hashtree_footer, make_vbmeta_image, extract_public_key
```

## Error Codes

All use cases return `OperationIssue` tuples instead of raising exceptions.
Error codes are stable and dot-prefixed; the CLI maps them to exit codes as
`config.*` / `keys.*` / `image.*` / `chain.*` → 1, `tool.*` / `signing.*` → 3,
unknown prefix → 0. The full list is in
[CLI_REFERENCE.md](CLI_REFERENCE.md#5-error-code-list).

| Code | Meaning |
|---|---|
| `config.not_found` | Profile or config not found |
| `config.no_active_profile` | `current`/empty was requested but nothing is active |
| `config.parse_error` | Invalid config format |
| `config.invalid_profile_id` | The profile id contains illegal characters |
| `config.profile_exists` | A profile with that name already exists |
| `config.profile_id_mismatch` | The directory name disagrees with the id inside `profile.json`; the write is refused |
| `config.no_partitions` | The profile has no partitions |
| `config.invalid_field` | A field is not whitelisted for editing, or its value is invalid |
| `config.invalid_algorithm` | Not a valid signing algorithm |
| `config.invalid_option_combination` | The same field was given in both `--set/--unset` and `--append/--remove`; or an illegal option combination |
| `config.partition_missing` | Partition not in profile |
| `config.key_missing` | Key file not found / key_id not in the manifest |
| `config.missing_included_partition` | A vbmeta includes a partition that is not in the profile |
| `config.auto_dir_not_found` | The `--from-images DIR` directory does not exist |
| `config.vbmeta_no_contents` | A vbmeta has neither `included_partitions` nor `chain_partitions` |
| `config.invalid_schema_version` | Wrong schema version |
| `config.save_failed` / `config.rename_failed` / `config.activate_failed` | The corresponding write operation failed |
| `config.invalid_archive` | Invalid archive format |
| `image.not_found` | Image file not found |
| `image.no_vbmeta_structure` | Image has no AVB footer |
| `chain.malformed_entry` | A chain entry is not a valid triple |
| `chain.key_file_missing` | The chain entry's public-key file is not in the key store |
| `chain.key_mismatch` | The chain entry's public key differs from the key the chained partition is signed with |
| `chain.chained_partition_unsigned` | The chained partition is NONE (unsigned) |
| `chain.key_not_found` | No key matched the descriptor's public-key SHA1 during chain resolution |
| `signing.step_failed` | A signing step failed |
| `tool.execution_failed` | avbtool returned non-zero |
| `keys.directory_not_found` | The key-store directory does not exist |
| `keys.file_not_found` | The private-key file named by `keys add` does not exist |
| `keys.not_found` / `keys.already_exists` | The `keys remove` / `keys add` key_id state conflicts |
| `keys.private_key_missing` | An entry's private-key file is missing |
| `keys.public_key_extract_failed` | Public-key extraction failed |
| `keys.manifest_not_found` | Key manifest missing |
| `workspace.path_escape` | Path escapes workspace |
