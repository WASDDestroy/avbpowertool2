# Key Management

How signing keys work in AVBPowerTool2 and how to set them up.

## How Key Resolution Works

When AVBPowerTool2 signs an image, it needs to find the private key file for each partition's `key_id`. The resolution chain is:

```
profile.json partition.key_id
    -> keys/manifest.json lookup
        -> keys/<filename>.pem on disk
```

### Step by step:

1. The profile's `profile.json` contains a `key_id` for each partition (e.g. `"key_id": "release_rsa4096"`).
2. The tool reads `keys/manifest.json` and looks up that `key_id`.
3. The manifest entry maps the key_id to a `.pem` filename (e.g. `"release_rsa4096.pem"`).
4. The tool resolves the path to `profiles/<profile>/keys/<filename>.pem`.

If any step fails, signing reports a `config.key_missing` error.

## manifest.json Format

```json
{
  "release_rsa4096": {
    "private_key": "release_rsa4096.pem",
    "public_key": "release_rsa4096_pub.bin"
  },
  "test_rsa2048": {
    "private_key": "test_rsa2048.pem"
  }
}
```

- **key_id** (dict key): The stable identifier referenced by `profile.json` partitions.
- **private_key** (required): Filename of the `.pem` private key file in the `keys/` directory.
- **public_key** (optional): Filename of the extracted public key binary (an
  `extract_public_key` product, usually `<private_key>.pem.bin`).
- **public_key_sha1** (optional): Cached SHA1 of the public key, used for chain
  partition matching. `keys discover --merge` keeps both cached fields only
  while the entry still points at the same `private_key` filename; `--replace`
  drops them all.

## Setting Up Keys

### Method 1: Auto-Discovery (Recommended for new profiles)

1. Place your `.pem` files in the profile's `keys/` directory:

```
profiles/my_device/keys/
  release_rsa4096.pem
  test_rsa2048.pem
```

2. Run auto-discovery via TUI (`Config Manager > Manage Keys > Auto-discover keys`) or API:

```python
from avbpowertool.application.commands import KeyDiscoveryRequest
from avbpowertool.application.services.manage_keys import KeyDiscoveryUseCase

uc = KeyDiscoveryUseCase(ws)
result = uc.execute(KeyDiscoveryRequest(profile_id="my_device"))
print(f"Discovered {result.discovered_count} keys")
for key_id, filename in result.manifest_entries:
    print(f"  {key_id} -> {filename}")
```

3. **Auto-discovery naming rule**: Each `.pem` filename (minus the `.pem` extension) becomes the `key_id`. For example:
   - `release_rsa4096.pem` -> key_id `release_rsa4096`
   - `test.pem` -> key_id `test`
   - `my_custom_key.pem` -> key_id `my_custom_key`

4. **Important**: The `key_id` in `profile.json` must match the key_id in the manifest. If you rename a `.pem` file, you must re-run discovery or update the manifest manually.

### Method 2: Manual Setup

1. Place your `.pem` files in `profiles/<profile>/keys/`.

2. Create or edit `profiles/<profile>/keys/manifest.json`:

```json
{
  "my_key_id": {
    "private_key": "any_filename.pem"
  }
}
```

The key_id does NOT need to match the filename. You can use any stable identifier.

3. In `profile.json`, reference the key_id:

```json
{
  "key_id": "my_key_id",
  "partition_name": "boot"
}
```

### Method 3: TUI Key Management

Navigate to `Config Manager > Manage Keys` in the TUI. From there you can:

- **List keys**: View all registered keys (from manifest) and unregistered `.pem` files on disk.
- **Auto-discover keys**: Scan `keys/` for `.pem` files and rebuild the manifest (filename = key_id).
- **Add key manually**: Specify a key_id and filename. Useful when the filename doesn't match the desired key_id.
- **Remove key**: Remove an entry from the manifest (does NOT delete the `.pem` file).

### Method 4: CLI (`keys` subcommands)

```shell
avbpowertool keys list          [--profile ID] [--json]
avbpowertool keys discover      [--profile ID] [--merge|--replace] [--json]
avbpowertool keys ensure-public [--profile ID] [--json]
avbpowertool keys add    <KEY_ID> --file <NAME.pem> [--profile ID] [--json]
avbpowertool keys remove <KEY_ID> [--profile ID] [--json]
```

- `--profile` defaults to `current`: a literal id is tried first, and a
  `current`/empty request falls back to the profile `.active-profile` points at.
  (The key-store use cases resolve leniently: a non-empty request that cannot be
  resolved is used literally and the use case reports
  `keys.directory_not_found`.)
- **`keys list`**: lists the keys registered in the manifest plus the `.pem`
  files on disk that are **not registered yet**.
- **`keys discover`**: scans the `.pem` files in `keys/` and writes them into
  `manifest.json`, using the filename minus `.pem` as the key_id.
  - `--merge` (**default**): the manifest already on disk is the baseline. Each
    discovered `.pem` updates its own entry's `private_key`; the cached
    `public_key` / `public_key_sha1` are kept **only while the entry still
    points at the same private-key filename** (a renamed file means the cache
    belongs to a different key). Entries whose `.pem` no longer exists on disk
    are **left untouched**, never deleted.
  - `--replace`: the historical behaviour — the manifest is rebuilt from the
    discovered `.pem` files only, so **every cached `public_key` is dropped**.
    Run `ensure-public` afterwards to re-extract them.
- **`keys ensure-public`**: materialises the missing public-key files for every
  manifest entry (`avbtool extract_public_key` into `<private_key>.pem.bin`, or
  the entry's existing `public_key` name) and writes `public_key` back into the
  manifest. Entries whose private key is missing are skipped and report
  `keys.private_key_missing`; an extraction failure reports
  `keys.public_key_extract_failed`.
- **`keys add <KEY_ID> --file <NAME.pem>`**: adds a mapping to the manifest.
  `--file` is a private-key filename **inside the key store**; **no** file is
  copied from elsewhere.
- **`keys remove <KEY_ID>`**: removes the entry from the manifest (**without
  deleting the `.pem` file**).

```shell
# Typical flow: drop the .pem files in, discover, then extract public keys
avbpowertool keys discover      --profile my_device --json
avbpowertool keys ensure-public --profile my_device --json
avbpowertool keys list          --profile my_device
```

Full arguments and `--json` output keys:
[CLI_REFERENCE.md](CLI_REFERENCE.md#keys-subcommands).

## Directory Structure

```
profiles/my_device/
  profile.json          # v3 config, references key_id per partition
  keys/
    manifest.json       # key_id -> filename mapping
    release.pem         # PEM private key files
    test.pem
    release.pem.bin     # Optional: extracted public keys (extract_public_key output)
```

## Key File Requirements

- Keys must be RSA private keys in PEM format.
- The key size must match the signing algorithm:
  - `SHA256_RSA2048` / `SHA512_RSA2048` -> 2048-bit RSA key
  - `SHA256_RSA4096` / `SHA512_RSA4096` -> 4096-bit RSA key
  - `SHA256_RSA8192` / `SHA512_RSA8192` -> 8192-bit RSA key
- Keys are NOT stored in the profile archive by default (use `config export` to include them).

## Chain Partition Public Keys (Important)

A vbmeta chain-partition entry is the triple `PART:SLOT:KEYFILE`, where
`KEYFILE` is a **public-key file** resolved against the key store
(`profiles/<id>/keys/`).

**`KEYFILE` must be an `extract_public_key` product** (`*.pem.bin`) — the file
`keys ensure-public` generates, or the one you get from
`avbtool extract_public_key --key <name>.pem --output <name>.pem.bin`.
The reason is that avbtool reads the third field of `--chain_partition` as
**raw bytes** and embeds them in the vbmeta: handing it a PEM text file corrupts
the vbmeta (the chain key no longer matches the real key, so verification can
only fail). `keys discover` / `keys ensure-public` write the public key to
`<name>.pem.bin` by default, so just reference that:

```json
{
  "key_id": "mykey_rsa4096",
  "private_key": "mykey_rsa4096.pem",
  "public_key": "mykey_rsa4096.pem.bin"
}
```

```
chain_partitions: ["vbmeta_system:2:mykey_rsa2048.pem.bin"]   # correct
chain_partitions: ["vbmeta_system:2:mykey_rsa2048.pem"]       # wrong: corrupts the vbmeta
```

**Use `config check-chains` to find a mismatch.** It is read-only and walks
every `chain_partitions` entry of the profile, checking that the partition
exists, that the chained partition is not unsigned (NONE), that the key file
exists, and that **the SHA1 of the chain entry's public key equals the SHA1 of
the public key of the key the chained partition is actually signed with** — the
last one is exactly the "chain entry public key disagrees with the actual
signing key" detection, reported as `chain.key_mismatch` (this repository's real
profile currently hits it):

```shell
$ avbpowertool config check-chains --profile my_device --json
{
  "profile_id": "my_device",
  "checked": 3,
  "issues": [
    {
      "error_code": "chain.key_mismatch",
      "message": "Partition 'vbmeta': chain entry 'vbmeta_system:2:mykey_rsa2048.pem.bin' uses 'mykey_rsa2048.pem.bin' (sha1 cdbb7717...), but 'vbmeta_system' is signed with key id 'mykey_rsa4096' (public key 'mykey_rsa4096.pem.bin', sha1 2597c218...)"
    }
  ]
}
```

The fix is to make the two agree: either switch the chained partition's `key_id`
to the key the chain entry names
(`config edit <PART> --set key_id=... --set algorithm=...`), or replace the chain
entry with the public key that partition really uses
(`config edit <vbmeta> --append chain_partitions=PART:SLOT:KEYFILE`, which
replaces the entry in place by partition name).

## Troubleshooting

| Error | Meaning | Fix |
|---|---|---|
| `config.key_missing` | Key ID not found in manifest | Run auto-discovery or add key manually |
| `keys.manifest_not_found` | `manifest.json` doesn't exist | Run auto-discovery |
| `keys.file_not_found` | `.pem` file referenced by manifest doesn't exist | Place the file in `keys/` or fix the manifest |
| `keys.directory_not_found` | `keys/` directory doesn't exist | Create it: `mkdir -p profiles/<id>/keys` |
| `keys.already_exists` | The `keys add` key_id is already in the manifest | Pick another key_id, or `keys remove` first |
| `keys.not_found` | The `keys remove` key_id is not in the manifest | Use `keys list` to see the real entries |
| `keys.private_key_missing` | An entry's private-key file is missing during `ensure-public` | Put the `.pem` back, or `keys remove` the entry |
| `keys.public_key_extract_failed` | Public-key extraction failed (corrupt key / not an RSA PEM) | Check the key format, or run `avbtool extract_public_key` by hand |
| `chain.key_file_missing` | The public-key file a chain entry points at is not in the key store | Run `keys ensure-public`, or fix the filename in the chain entry |
| `chain.key_mismatch` | The chain entry's public key is not the key the chained partition is signed with | See "Chain Partition Public Keys" above |
| `chain.malformed_entry` | A chain entry is not `PART:SLOT:KEYFILE` (SLOT must be a number >= 1) | Rewrite the entry as a full triple |

## API Reference

```python
from avbpowertool.application.services.manage_keys import (
    KeyListUseCase,        # List keys in a profile
    KeyDiscoveryUseCase,   # Auto-discover .pem files (merge / replace)
    KeyEnsurePublicUseCase,# Extract missing public keys and update the manifest
    KeyAddUseCase,         # Add key entry manually
    KeyRemoveUseCase,      # Remove key entry
)
```

The merge semantics of `KeyDiscoveryUseCase` come from
`KeyDiscoveryRequest(merge=...)` (default `True`); `KeyEnsurePublicUseCase`
needs an `AvbToolPort` and returns
`KeyEnsurePublicResult(extracted, skipped, issues)`. Request/result fields and a
minimal example are in [BACKEND_API.md](BACKEND_API.md).
