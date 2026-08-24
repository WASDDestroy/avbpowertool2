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
- **public_key** (optional): Filename of the extracted public key binary.

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

## Directory Structure

```
profiles/my_device/
  profile.json          # v2 config, references key_id per partition
  keys/
    manifest.json       # key_id -> filename mapping
    release.pem         # PEM private key files
    test.pem
    release_pub.bin     # Optional: extracted public keys
```

## Key File Requirements

- Keys must be RSA private keys in PEM format.
- The key size must match the signing algorithm:
  - `SHA256_RSA2048` / `SHA512_RSA2048` -> 2048-bit RSA key
  - `SHA256_RSA4096` / `SHA512_RSA4096` -> 4096-bit RSA key
  - `SHA256_RSA8192` / `SHA512_RSA8192` -> 8192-bit RSA key
- Keys are NOT stored in the profile archive by default (use `config export` to include them).

## Troubleshooting

| Error | Meaning | Fix |
|---|---|---|
| `config.key_missing` | Key ID not found in manifest | Run auto-discovery or add key manually |
| `keys.manifest_not_found` | `manifest.json` doesn't exist | Run auto-discovery |
| `keys.file_not_found` | `.pem` file referenced by manifest doesn't exist | Place the file in `keys/` or fix the manifest |
| `keys.directory_not_found` | `keys/` directory doesn't exist | Create it: `mkdir -p profiles/<id>/keys` |

## API Reference

```python
from avbpowertool.application.services.manage_keys import (
    KeyListUseCase,        # List keys in a profile
    KeyDiscoveryUseCase,   # Auto-discover .pem files
    KeyAddUseCase,         # Add key entry manually
    KeyRemoveUseCase,      # Remove key entry
)
```
