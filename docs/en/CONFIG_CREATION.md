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
3. **Choose mode** — manual or auto
4. **Prepare keys** (shared, BEFORE collecting images) — the wizard
   creates the key store `profiles/<id>/keys/`, asks you to drop your
   `.pem` private keys in it, then runs key discovery (filename minus
   `.pem` becomes the key_id). Manual mode can then pick key_ids from
   the discovered keys; auto mode's chain-partition public-key
   resolution has a populated manifest to match against.
5. **Partitions** — add one or more partitions with their signing settings

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

**TUI signing page**: when the selected images include a vbmeta
partition, an extra question asks whether to attach this config's props
to the generated vbmeta image — **default No**. avbtool does not filter
duplicate props, and the props read back from images (e.g.
`com.android.build.*`) usually duplicate what the sub-partitions carry;
leaving them out avoids vbmeta size bloat and redundant info. Choose
"Yes" when the props should be preserved (they come from the vbmeta
partition config's `props` field).

## Partition Types

### Hash Partition

For small images (boot, init_boot, dtbo). Uses `add_hash_footer`.
A hash footer requires `partition_size` (or `dynamic_partition_size`),
otherwise avbtool rejects the command.

```python
PartitionConfig(
    image="boot.img",
    descriptor=DescriptorType.HASH,
    algorithm=SigningAlgorithm.SHA256_RSA4096,
    key_id="my_key",
    partition_name="boot",
    partition_size=67108864,      # required: partition size in bytes, multiple of 4096
    rollback_index=0,
    salt="optional_hex_salt",     # empty salt -> avbtool generates a random one
)
```

### Hashtree Partition

For large images (system, vendor, product). Uses `add_hashtree_footer` with dm-verity and FEC.
Since v3 there is a single `block_size` (default 4096) instead of separate data/hash block sizes.

```python
PartitionConfig(
    image="system.img",
    descriptor=DescriptorType.HASHTREE,
    algorithm=SigningAlgorithm.SHA256_RSA4096,
    key_id="my_key",
    partition_name="system",
    block_size=4096,              # --block_size (default 4096)
    fec_num_roots=2,              # --fec_num_roots (default 2)
    do_not_generate_fec=False,    # True skips FEC generation
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

#### Auto-create: chain partitions and props

When auto-creating a config by scanning a directory of images:

- **Chain partitions**: `Chain Partition` descriptors embedded in a
  vbmeta image are recognized as that vbmeta's chain partitions (never
  mixed into `included_partitions`) and restored as `PART:SLOT:KEY_FILE`
  triples — SLOT from the descriptor's `Rollback Index Location`, KEY_FILE
  by matching the descriptor's `Public key (sha1)` against each key store
  entry's `avbtool extract_public_key` output (SHA1). When no key
  matches, the chain is **not** written to the config and a
  `chain.key_not_found` issue is shown (fill it in later with
  `config edit --set chain_partitions=...`).
- **Props**: props read back from images stay in the generated config
  (reviewable, editable), but by default are **not** written into a
  generated vbmeta at signing time — the signing page asks first (see
  "Sign" above). Manually created vbmeta partitions can also take props
  directly (comma-separated `key:value`).
- **Known limitation**: `info_image` output cannot distinguish
  `Chain Partition` from `Chain Partition (do not use ab)`, so auto
  creation restores standard `chain_partitions` only;
  `chain_partitions_do_not_use_ab` must be set manually.

## Profile Directory Structure

After creation, the profile looks like:

```
profiles/my_device/
  profile.json        # v3 config schema
  keys/
    manifest.json     # key_id -> filename mapping
    release.pem       # key files (you add these)
  boot.img            # image files (you add these)
  vbmeta.img
```

## Config v3 Schema Reference

```json
{
  "schema_version": 3,
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
      "partition_size": 67108864,
      "rollback_index": 0,
      "salt": "",
      "flags": 0,
      "props": []
    }
  }
}
```

## Migrating from v2 to v3

Main v3 changes: hash partitions gain `partition_size` / `dynamic_partition_size`;
`data_block_size` + `hash_block_size` collapse into `block_size`;
`kernel_cmdline` (string) becomes `kernel_cmdlines` (string array);
new fields for FEC, `calc_max_image_size`, `output_vbmeta_image`,
`use_persistent_digest`, `chain_partitions_do_not_use_ab`, `padding_size`,
`prop_from_file`, `signing_helper` / `signing_helper_with_files`,
`public_key_metadata`, `append_to_release_string`, and more.

v2 configs are auto-migrated in memory when read (the v2 file itself is untouched).
To upgrade a v2 file on disk in place, run:

```shell
avbpowertool config migrate [--profile ID]
```

### Quick single-field edits

```shell
# Change the boot partition size, rollback index, kernel cmdlines (comma-separated), etc.
avbpowertool config edit boot --profile current \
  --set partition_size=67108864 --set rollback_index=1 \
  --set kernel_cmdlines=androidboot.avb.test=1
```

Editable fields: integers — `partition_size`, `rollback_index`,
`rollback_index_location`, `flags`, `block_size`, `fec_num_roots`, `padding_size`;
strings — `salt`, `hash_algorithm`, `output_vbmeta_image`, `setup_rootfs_from_kernel`,
`signing_helper`, `signing_helper_with_files`, `public_key_metadata`,
`append_to_release_string`; booleans — `dynamic_partition_size`,
`do_not_generate_fec`, `calc_max_image_size`, `do_not_append_vbmeta_image`,
`no_hashtree`, `check_at_most_once`, `use_persistent_digest`, `do_not_use_ab`,
`set_hashtree_disabled_flag`, `set_verification_disabled_flag`,
`print_required_libavb_version`, `setup_as_rootfs_from_kernel`;
comma-separated arrays — `kernel_cmdlines`, `chain_partitions`,
`chain_partitions_do_not_use_ab`, `included_partitions`,
`include_descriptors_from_image`.

## Unsigned (NONE) Partitions

v3 supports `SigningAlgorithm.NONE`: the partition still gets its hash / hashtree footer
or vbmeta contents, but **no** `--algorithm` / `--key` are passed, so avbtool skips
hash/signature computation (equivalent to an unsigned image).
NONE hash partitions also need `partition_size` or `dynamic_partition_size`.

```python
PartitionConfig(
    image="dtbo.img",
    descriptor=DescriptorType.HASH,
    algorithm=SigningAlgorithm.NONE,   # unsigned
    key_id="",                          # no key_id required for NONE
    partition_name="dtbo",
    partition_size=4194304,             # NONE partitions also need a size
)
```

vbmeta `included_partitions` / `chain_partitions` may reference NONE partitions; chain
partition keys are resolved from the public-key filename in the `chain_partitions` triple.

## Importing Legacy v1 Configs

v1 (AVBPowerTool 1.x) config ZIP archives can be imported and automatically converted to v3:

- **TUI**: Settings page → `[I] Import v1 legacy config`, pick a v1 zip in the project root.
- **CLI**: `avbpowertool config import-legacy <archive> [--name ID] [--no-activate] [--json]`.

The conversion decodes `imageInfo.json` (preserving signing-relevant fields, mapping
`Algorithm: NONE` to `SigningAlgorithm.NONE`), completes vbmeta chain triples, and copies
`Keys/` pem/pub.bin files into a generated `manifest.json`. v1 BATCH archives are rejected
explicitly; conversion never modifies the v1 source files.

Full design: [LEGACY_CONFIG_IMPORT.md](LEGACY_CONFIG_IMPORT.md).
