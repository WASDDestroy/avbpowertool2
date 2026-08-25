# AVBPowerTool2

A configuration-driven Python wrapper for AOSP `avbtool.py`. Provides CLI and TUI for Android Verified Boot image signing, inspection, and config management.

## Features

- **Image Inspection**: Read AVB metadata from boot, system, vbmeta images
- **Image Signing**: Sign images with hash/hashtree footers, generate vbmeta images
- **Config Management**: Profile-based configuration with import/export via ZIP archives
- **Legacy Config Import**: Auto-convert v1 (AVBPowerTool 1.x) config ZIPs to v2 (Settings page or `config import-legacy`)
- **Key Management**: Per-profile key stores with manifest-based key resolution
- **CLI Mode**: Full-featured command-line interface with `--json` output
- **TUI Mode**: Curses-based interactive terminal UI with keyboard navigation
- **i18n**: English and Chinese localization via gettext
- **Cross-Platform**: Windows, Linux, macOS (with WSL support)

## Quick Start

### Prerequisites

- Python 3.11+
- For key operations (signing, public-key extraction), one of:
  - the optional `crypto` extra (recommended — no external tools needed), or
  - an `openssl` executable on PATH

The vendored `avbtool.py` uses the in-process
[cryptography](https://cryptography.io/) package when it is installed and
automatically falls back to the `openssl` command-line tool otherwise (a
one-time notice is printed when this happens). Set `AVB_CRYPTO_BACKEND=openssl`
to force the fallback path.

### Install

```shell
# Clone the repository
git clone https://github.com/WASDDestroy/AVBPowerTool2.git
cd AVBPowerTool2

# Install with uv (recommended)
uv sync

# Recommended: pure-Python key operations, no OpenSSL required
uv sync --extra crypto

# Or install every optional feature (Windows TUI, FEC encoder, crypto backend)
uv sync --all-extras

# Or install with pip
pip install -e .[crypto]
```

### CLI Usage

```shell
# Inspect image AVB metadata
avbpowertool image inspect boot vbmeta

# Plan signing (dry-run)
avbpowertool image sign boot --dry-run

# Execute signing
avbpowertool image sign boot --execute --yes

# Config management
avbpowertool config list
avbpowertool config show
avbpowertool config validate
avbpowertool config activate myprofile
avbpowertool config import myconfig.zip
avbpowertool config import-legacy mylegacy_v1.zip   # auto-convert legacy v1 config to v2
avbpowertool config export myprofile

# About
avbpowertool about
```

All commands support `--json` for machine-readable output.

### TUI Usage

```shell
# Launch interactive mode (default when no command given)
avbpowertool
```

## Project Structure

```
avbpowertool/
  domain/           Pure models, validation, signing plan (no I/O)
  application/      Use cases, ports (Protocol interfaces)
  infrastructure/   avbtool subprocess, filesystem, persistence, FEC
  presentation/     CLI (argparse) and TUI (curses)
  resources/        Navigation config
  locale/           gettext translations (.po)
  vendor/           Vendored FEC encoder
tests/
  unit/             Unit tests
  integration/      Integration tests
  contract/         Contract/schema tests
  fixtures/         Test fixtures
```

## Architecture

Four-layer hexagonal architecture:

```
CLI / TUI
    |
    v
Application (use cases, request/result types, progress events)
    |
    v
Domain (models, validation, signing plan, dependency graph)
    ^
    |
Infrastructure (avbtool subprocess, filesystem, persistence, FEC)
```

- `domain/` never imports from other layers
- `application/` depends only on domain and ports (Protocols)
- `infrastructure/` implements ports
- `presentation/` calls application use cases only

## Configuration

### Profile Structure

```
profiles/
  <profile_id>/
    profile.json      v2 schema config
    keys/
      manifest.json   key_id -> filename mapping
      *.pem           key files
```

### Config v2 Schema

```json
{
  "schema_version": 2,
  "profile": {"id": "example", "name": "Example"},
  "key_store_path": "keys",
  "partitions": {
    "boot": {
      "image": "boot.img",
      "descriptor": "hash",
      "algorithm": "SHA256_RSA4096",
      "key_id": "release_rsa4096",
      "partition_name": "boot",
      "rollback_index": 0,
      "salt": "abcdef123456"
    }
  }
}
```

## Development

See [AGENTS.md](../AGENTS.md) for development guidelines.

## Documentation

- [Implementation Plan](IMPLEMENTATION_PLAN.md) — architecture and phase breakdown
- [Backend API Reference](BACKEND_API.md) — use the backend from Python
- [Adding Navigation](FRONTEND_NAVIGATION.md) — add entries to the TUI navigation tree
- [Editing Pages](FRONTEND_PAGES.md) — create or modify TUI views
- [Legacy Config Import](LEGACY_CONFIG_IMPORT.md) — v1 → v2 conversion design and implementation

## License

See [LICENSE](../LICENSE).
