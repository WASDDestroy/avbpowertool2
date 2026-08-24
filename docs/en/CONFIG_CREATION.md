# Creating a Configuration

How to create a new AVB signing profile (configuration).

## Overview

A profile (config) defines how AVB images should be signed. It contains:
- A profile ID and display name
- One or more partition configurations (image, descriptor type, algorithm, key, etc.)
- An associated key store (`keys/` directory with PEM files and manifest)

## Quick Start

### Using the TUI (Interactive)

```shell
avbpowertool
# Navigate to: Config Manager > Create Config
# Follow the wizard prompts
```

The wizard will guide you through:
1. **Profile ID** — unique identifier (e.g. `my_device`)
2. **Profile name** — display name (e.g. "My Device ROM")
3. **Partitions** — add one or more partitions with their signing settings

### Using the API (Python)

```python
from pathlib import Path
from avbpowertool.bootstrap import bootstrap
from avbpowertool.application.commands import ConfigCreateRequest
from avbpowertool.application.services.manage_configs import ConfigCreateUseCase
from avbpowertool.domain.models import PartitionConfig, DescriptorType, SigningAlgorithm

ws = bootstrap(root=Path("/path/to/project"))
uc = ConfigCreateUseCase(ws)

result = uc.execute(ConfigCreateRequest(
    profile_id="my_device",
    profile_name="My Device ROM",
    partitions=(
        PartitionConfig(
            image="boot.img",
            descriptor=DescriptorType.HASH,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="release_rsa4096",
            partition_name="boot",
        ),
        PartitionConfig(
            image="vbmeta.img",
            descriptor=DescriptorType.VBMETA,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="release_rsa4096",
            partition_name="vbmeta",
            included_partitions=("boot",),
        ),
    ),
    activate=True,
))

if result.issues:
    for iss in result.issues:
        print(f"[{iss.error_code}] {iss.message}")
else:
    print(f"Created profile: {result.profile_id}")
```

## After Creating a Profile

### 1. Place Image Files

Copy your `.img` files into the profile directory:

```
profiles/my_device/
  boot.img
  vbmeta.img
```

### 2. Place Key Files

Copy your PEM private key files into the profile's `keys/` directory:

```
profiles/my_device/keys/
  release_rsa4096.pem
```

Then register them in the manifest. **Auto-discovery** is the easiest way — it scans all `.pem` files in `keys/` and uses the filename (minus `.pem`) as the `key_id`. For example, `release_rsa4096.pem` becomes key_id `release_rsa4096`.

**Via TUI**: Navigate to `Config Manager > Manage Keys > Auto-discover keys`.

**Via API**:

```python
from avbpowertool.application.commands import KeyDiscoveryRequest
from avbpowertool.application.services.manage_keys import KeyDiscoveryUseCase

uc = KeyDiscoveryUseCase(ws)
result = uc.execute(KeyDiscoveryRequest(profile_id="my_device"))
print(f"Discovered {result.discovered_count} keys")
for key_id, filename in result.manifest_entries:
    print(f"  {key_id} -> {filename}")
```

**Important**: The `key_id` in `profile.json` partitions must match a key_id in the manifest. If you use auto-discovery, name your `.pem` files to match the key_ids you specified during config creation (e.g. `release_rsa4096.pem` for key_id `release_rsa4096`).

For full details on key management (manual setup, manifest format, troubleshooting), see [KEY_MANAGEMENT.md](KEY_MANAGEMENT.md).

### 3. Validate

```python
from avbpowertool.application.commands import ConfigValidateRequest
from avbpowertool.application.services.manage_configs import ConfigValidateUseCase

uc = ConfigValidateUseCase(ws)
result = uc.execute(ConfigValidateRequest(profile_id="my_device"))

if result.missing_images:
    print(f"Missing images: {result.missing_images}")
if result.missing_keys:
    print(f"Missing keys: {result.missing_keys}")
```

### 4. Sign

```shell
avbpowertool image sign boot vbmeta --dry-run  # Preview
avbpowertool image sign boot vbmeta --execute --yes  # Execute
```

## Partition Types

### Hash Partition

For small images (boot, init_boot, dtbo). Uses `add_hash_footer`.

```python
PartitionConfig(
    image="boot.img",
    descriptor=DescriptorType.HASH,
    algorithm=SigningAlgorithm.SHA256_RSA4096,
    key_id="my_key",
    partition_name="boot",
    rollback_index=0,
    salt="optional_hex_salt",
)
```

### Hashtree Partition

For large images (system, vendor, product). Uses `add_hashtree_footer` with dm-verity and FEC.

```python
PartitionConfig(
    image="system.img",
    descriptor=DescriptorType.HASHTREE,
    algorithm=SigningAlgorithm.SHA256_RSA4096,
    key_id="my_key",
    partition_name="system",
    data_block_size=4096,
    hash_block_size=4096,
)
```

### VBMeta Partition

Meta-partition that includes descriptors from other images. Uses `make_vbmeta_image`.

```python
PartitionConfig(
    image="vbmeta.img",
    descriptor=DescriptorType.VBMETA,
    algorithm=SigningAlgorithm.SHA256_RSA4096,
    key_id="my_key",
    partition_name="vbmeta",
    included_partitions=("boot", "system"),
    chain_partitions=("vbmeta_system:1:system_key.pem",),
)
```

## Profile Directory Structure

After creation, the profile looks like:

```
profiles/my_device/
  profile.json        # v2 config schema
  keys/
    manifest.json     # key_id -> filename mapping
    release.pem       # key files (you add these)
  boot.img            # image files (you add these)
  vbmeta.img
```

## Config v2 Schema Reference

```json
{
  "schema_version": 2,
  "profile": {
    "id": "my_device",
    "name": "My Device ROM"
  },
  "key_store_path": "keys",
  "partitions": {
    "boot": {
      "image": "boot.img",
      "descriptor": "hash",
      "algorithm": "SHA256_RSA4096",
      "key_id": "release_rsa4096",
      "partition_name": "boot",
      "rollback_index": 0,
      "salt": "",
      "flags": 0,
      "props": []
    }
  }
}
```
