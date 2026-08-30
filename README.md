# AVBPowerTool2

> English | [中文版](/docs/zh/README.md)

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

All local patches carried by the vendored `avbtool.py` (crypto backend,
pure-Python FEC) are recorded in
[VENDORED_AVBTOOL_PATCHES.md](docs/en/VENDORED_AVBTOOL_PATCHES.md); use it to
re-apply patches when upgrading upstream avbtool.

### Install

```shell
# Clone the repository
git clone https://github.com/WASDDestroy/AVBPowerTool2.git
cd AVBPowerTool2

# Install with uv (recommended)
uv sync

# Install dev tools (tests, linting, type checking)
uv sync --all-extras
```

#### Install with pip3 (no uv required)

`uv` is optional — the package installs and runs with the standard Python
toolchain (`python3` + `pip3`). The crypto, FEC, and (on Windows) TUI
dependencies are core dependencies, so `pip3` pulls them in automatically.

```shell
# 1) Create and activate a virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate            # Linux / macOS
# .venv\Scripts\Activate.ps1         # Windows (PowerShell)
# .venv\Scripts\activate.bat         # Windows (cmd)

# 2) Upgrade pip and install the package (editable install from the checkout)
python -m pip install --upgrade pip
python -m pip install -e .
# or, to install a regular copy into site-packages:
# python -m pip install .

# 3) Verify
python -m avbpowertool about
```

> **PATH not set up?** `pip3` puts the `avbpowertool` executable in your
> Python environment's `bin`/`Scripts` directory. If that directory is not
> on your `PATH`, run everything with `python -m avbpowertool` instead — it
> behaves identically and never depends on `PATH`.

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

> Without `uv`, or when the console script is not on `PATH`, prefix any
> command with `python -m`:
>
> ```shell
> python -m avbpowertool image inspect boot vbmeta
> python -m avbpowertool config list
> ```

### TUI Usage

```shell
# Launch interactive mode (default when no command given)
avbpowertool
# or, without a PATH entry for the console script:
python -m avbpowertool
```

### Backend API (call from Python)

The package can also be imported and driven directly from Python code — no
console entry point involved. After the pip3 install above, run from the
project root (the current directory becomes the workspace root, where
`avbtool.py`, `Images/`, and `profiles/` live):

```python
# inspect.py — run with: python inspect.py
from avbpowertool.bootstrap import bootstrap
from avbpowertool.infrastructure.avbtool.runner import SubprocessAvbTool
from avbpowertool.application.commands import InspectImagesRequest
from avbpowertool.application.services.inspect_images import InspectImagesUseCase

ws = bootstrap()  # workspace root = current directory
avb = SubprocessAvbTool(ws.avbtool_script)
result = InspectImagesUseCase(ws, avb).execute(
    InspectImagesRequest(image_names=("boot", "vbmeta"))
)
for img in result.images:
    print(f"{img.image_name}: {img.descriptor}, {img.algorithm}")
```

Or as a one-liner from the shell:

```shell
python -c "from avbpowertool.bootstrap import bootstrap; print(bootstrap().root)"
```

See the [Backend API Reference](docs/en/BACKEND_API.md) for the full reference.

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

See [AGENTS.md](AGENTS.md) for development guidelines.

## Documentation

- [Implementation Plan](docs/en/IMPLEMENTATION_PLAN.md) — architecture and phase breakdown
- [Backend API Reference](docs/en/BACKEND_API.md) — use the backend from Python
- [Adding Navigation](docs/en/FRONTEND_NAVIGATION.md) — add entries to the TUI navigation tree
- [Editing Pages](docs/en/FRONTEND_PAGES.md) — create or modify TUI views
- [Legacy Config Import](docs/en/LEGACY_CONFIG_IMPORT.md) — v1 → v2 conversion design and implementation
- [Architecture](docs/en/ARCHITECTURE.md) — layers, data flow, and module responsibilities
- [Internationalization](docs/en/I18N.md) — add and use localized string resources
- [中文文档](docs/zh/README.md) — Chinese docs (ARCHITECTURE.md / I18N.md included)

## License

See [LICENSE](../LICENSE).
