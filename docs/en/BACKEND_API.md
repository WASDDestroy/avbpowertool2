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

## Domain Models

### AvbProfile

```python
from avbpowertool.domain.models import AvbProfile, PartitionConfig, DescriptorType, SigningAlgorithm

profile = AvbProfile(
    id="myprofile",
    name="My Profile",
    schema_version=2,
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

| Code | Meaning |
|---|---|
| `config.not_found` | Profile or config not found |
| `config.parse_error` | Invalid config format |
| `config.key_missing` | Key file not found |
| `config.partition_missing` | Partition not in profile |
| `config.invalid_schema_version` | Wrong schema version |
| `image.not_found` | Image file not found |
| `image.no_vbmeta_structure` | Image has no AVB footer |
| `signing.step_failed` | A signing step failed |
| `tool.execution_failed` | avbtool returned non-zero |
| `keys.manifest_not_found` | Key manifest missing |
| `workspace.path_escape` | Path escapes workspace |
