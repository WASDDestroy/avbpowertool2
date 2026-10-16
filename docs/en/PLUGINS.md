# Plugin System

An AVBPowerTool2 plugin is **a directory under the workspace's `plugins/<id>/`**: a
manifest XML plus an entry script. A plugin can be a packaged shell script, or any
program that drives this tool back through its CLI.

> This page documents the contract shared by plugin *authors* and plugin *users*.
> For the command-by-command syntax see the `plugin` subcommands in section 4 of the
> [CLI Reference](CLI_REFERENCE.md).

## Contents

- [1. Directory Layout](#1-directory-layout)
- [2. Manifest XML Format](#2-manifest-xml-format)
- [3. Packaging and Installation](#3-packaging-and-installation)
- [4. Entry Types and Dispatch](#4-entry-types-and-dispatch)
- [5. The Plugin ↔ Tool Contract](#5-the-plugin--tool-contract)
- [6. Calling the Tool from a Plugin](#6-calling-the-tool-from-a-plugin)
- [7. Install / Uninstall / Run Examples](#7-install--uninstall--run-examples)
- [8. TUI](#8-tui)
- [9. Security](#9-security)

---

## 1. Directory Layout

```
<workspace root>/
  plugins/
    testkey_config_gen/                    <- one plugin = one directory
      avbpowertool_plugin_config.xml       <- the manifest (fixed file name)
      make-testkey-config.cmd              <- the entry script (entry)
      make-testkey-config.ps1              <- other files the entry uses
      keys/
        testkey_rsa2048.pem                <- bundled material, travels with the plugin
        testkey_rsa4096.pem
      README.md
```

- The plugin id is the directory name. An id may only contain letters, digits, `_`,
  `-`, and `.`, and must be a **direct child** of `plugins/` — path separators are
  rejected (`a/b`, `..`, absolute paths, …).
- **The development location is the installation location.** `plugins/<id>/` is both
  the directory you develop a plugin in and the directory it is installed into;
  `plugin install` copies a directory or zip from **elsewhere** into it, and
  `plugin uninstall` deletes it. Writing a plugin straight into the repository's
  `plugins/` therefore means it is already installed.
- A sub-directory without a manifest is **not** a plugin and `plugin list` ignores
  it. A sub-directory *with* a broken manifest is **reported** (in `issues[]`),
  never silently dropped.
- The manifest file name is fixed: `avbpowertool_plugin_config.xml`.

## 2. Manifest XML Format

The ready-made example in this repository
(`plugins/testkey_config_gen/avbpowertool_plugin_config.xml`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<avbpowertool_plugin schema_version="1">
  <id>testkey_config_gen</id>
  <entry>make-testkey-config.cmd</entry>
  <names>
    <name lang="en">Test-key config generator</name>
    <name lang="zh">测试密钥配置生成</name>
  </names>
  <description lang="zh">按旗标表生成 testkey 打包配置并导出 zip</description>
  <description lang="en">Generate a testkey packaging config from the selected image set and export it as a zip</description>
</avbpowertool_plugin>
```

| Element / attribute | Required | Notes |
|---|---|---|
| Root element `avbpowertool_plugin` | yes | A different root name gives `plugin.manifest_invalid` |
| `schema_version` (attribute) | no | Omitted means `1` (the only supported version). A non-number or anything but `1` gives `plugin.manifest_invalid` |
| `<id>` | yes | The plugin id; it **must match the installation directory name** (`plugin install` uses it to pick the target directory). Empty gives `plugin.manifest_invalid`; illegal characters give `plugin.id_invalid` |
| `<entry>` | yes | A **bare file name** of the entry script, inside the plugin directory. Empty gives `plugin.entry_missing`; a `/` or `\` (an attempt to point outside) gives `plugin.entry_invalid` |
| `<names><name lang="…">` | yes | The localized display names, at least one. **Declaring none gives `plugin.manifest_invalid`** |
| `<description lang="…">` | no | Localized description; the CLI does not show it today, the TUI / future list views use it |

**Language resolution** (`PluginManifest.name_for`):

1. exact (case-insensitive) match on the requested language, e.g. `zh` hits `lang="zh"`;
2. fall back to the primary subtag, e.g. `zh_CN` hits `lang="zh"`;
3. fall back to `lang="en"`;
4. fall back to the first non-empty name in the manifest;
5. fall back to the plugin id.

A blank entry is not a translation and never shadows a later fallback. The
localization in the manifest is deliberately **not** routed through gettext: a
plugin ships its own translations and the tool only picks one.

The current language comes from the workspace `settings.json` (`language`, default
`en`) and is injected by `bootstrap()`, so the `name` reported by `plugin list` is
already resolved for it.

## 3. Packaging and Installation

```shell
avbpowertool plugin install <SOURCE> [--force] [--json]
```

`SOURCE` is either:

1. **A directory** — the manifest and the entry sit directly in it, e.g.
   `.\my_plugin\`. When that directory **is** `plugins/<id>/` itself (an in-place
   install), the copy is a no-op rather than an error.
2. **A zip archive** — two layouts are supported:
   - **root layout**: the manifest is at the archive root
     (`avbpowertool_plugin_config.xml`, `run.cmd`, …);
   - **exactly one directory level**: every file lives under **one** top-level
     directory (`demo/avbpowertool_plugin_config.xml`, …) — exactly what
     `Compress-Archive <dir>` produces. That level is stripped on extraction.

   More than one manifest in the archive (say one at the root and one in a
   sub-directory) gives `plugin.manifest_invalid`; none at all gives
   `plugin.manifest_missing`.

Packaging examples:

```powershell
# Windows PowerShell: produce a zip in the "exactly one directory level" layout
Compress-Archive -Path .\my_plugin -DestinationPath .\my_plugin.zip -Force
avbpowertool plugin install .\my_plugin.zip --json
```

```shell
# POSIX: run this in the plugin directory's PARENT so the zip carries the directory name
cd /path/to/parent
zip -r my_plugin.zip my_plugin
avbpowertool plugin install ./my_plugin.zip --json
```

Install behaviour:

- an existing `plugins/<id>/` without `--force` gives `plugin.exists` (exit code 1)
  and **overwrites nothing**;
- with `--force` the install overwrites (`copytree(dirs_exist_ok=True)`);
- a zip is validated **before a single byte is extracted**: absolute paths, drive
  letters, `:` (NTFS ADS), and any `..` component are refused
  (`plugin.install_failed`), so there is never a half-extracted directory and no
  file lands outside the target directory;
- a `SOURCE` that is neither a directory nor a valid zip gives
  `plugin.install_failed`.

Uninstall:

```shell
avbpowertool plugin uninstall <PLUGIN_ID> --yes [--json]
```

`--yes` is a **hard gate**: without it the tool only prints

```
This deletes the plugin directory including any bundled files. Use --yes to confirm.
```

to stderr and exits 1, removing **nothing** (a plugin directory can carry key
material, so there is no interactive prompt — only an explicit confirmation). With
`--yes`, `removed_files` / `removed_bytes` describe the regular files counted
**before** the removal. An illegal id gives `plugin.id_invalid`; a missing directory
gives `plugin.not_found`; a failing removal (a locked file on Windows, for instance)
gives `plugin.uninstall_failed`.

## 4. Entry Types and Dispatch

The `entry` suffix picks the interpreter
(`infrastructure/plugins/runner.py`):

| Suffix | Command actually executed |
|---|---|
| `.py` | `sys.executable <entry> <args…>` — the interpreter **currently running this tool**, so the plugin sees the virtualenv's dependencies |
| `.ps1` | `pwsh -NoProfile -File <entry> <args…>` |
| `.cmd` | `cmd /c <entry> <args…>` |
| `.bat` | `cmd /c <entry> <args…>` |
| `.sh` | `sh <entry> <args…>` — **nominally only**: the code path exists but has never been verified on Windows |
| anything else | unsupported → `plugin.run_failed` (`exit_code` is `-1`) |

A missing interpreter (no `pwsh`, for example) gives `plugin.run_failed`.

## 5. The Plugin ↔ Tool Contract

The plugin process is started directly by this tool, with this contract:

| Item | Value |
|---|---|
| Working directory (cwd) | The **workspace root** (`WorkspacePaths.root`). Relative paths such as `Images/`, `Logs/`, `profiles/` mean exactly what they mean to the tool itself |
| `AVBPOWERTOOL_ROOT` | Absolute path of the workspace root |
| `AVBPOWERTOOL_PLUGIN_DIR` | Absolute path of the plugin's own directory (`plugins/<id>/`) |
| `AVBPOWERTOOL_PLUGIN_ID` | The plugin id |
| `AVBPOWERTOOL_LANG` | The current language code (`en` / `zh`, …) — the same value `plugin list` resolves display names with |
| `AVBPOWERTOOL_CLI` | The command prefix recommended for calling this tool back; currently `uv run avbpowertool` |
| stdio | **Inherited**: stdout / stderr / stdin are never captured, so a plugin may print progress and may prompt interactively |
| Exit code | **Passed through unchanged.** A plugin exiting 3 makes `avbpowertool plugin run` exit 3; a non-zero status is **not** an error and leaves `issues[]` empty |
| Arguments | Everything after `--` is appended to the entry script verbatim, not one character altered |

The environment variables are layered **on top of** the parent environment (`PATH`,
`HOME`, … stay visible); they do not replace it.

`exit_code` is `-1` only when the plugin **never started** (illegal id, missing
plugin, missing `entry` file, missing interpreter, invalid manifest); in that case
`issues[]` is always non-empty. **Scripts should gate on whether `issues[]` is
empty, not on `exit_code` alone** — a plugin may itself exit with a non-zero status,
and that is the plugin's verdict rather than a tool error.

Argument pass-through (specific to `plugin run`):

```shell
avbpowertool plugin run testkey_config_gen --json             # --json goes to avbpowertool
avbpowertool plugin run testkey_config_gen -- --json          # --json goes to the plugin
avbpowertool plugin run testkey_config_gen -- --core --8e --no_prompt
```

- everything before the first **standalone** `--` is parsed by this tool's argparse
  (`plugin_id`, `--json`);
- everything after `--` is handed to the plugin verbatim;
- in text mode a successful run makes this tool print **nothing extra** (so the
  plugin's own output is never polluted); only `--json` prints a result line;
- this is deliberately not `argparse.REMAINDER`: REMAINDER would also swallow the
  `--json` in `plugin run <id> --json`, so it cannot express both meanings. The
  actual implementation splits argv at the first `--` inside `main()` (see
  `avbpowertool/presentation/cli/parser.py::_split_plugin_passthrough`).

## 6. Calling the Tool from a Plugin

**Recommended: go through the CLI.** Use `$AVBPOWERTOOL_CLI` (or spell out
`uv run --project "$AVBPOWERTOOL_ROOT" avbpowertool …`) to start a fresh tool
process:

```powershell
# PowerShell snippet inside a plugin
$root = $env:AVBPOWERTOOL_ROOT
uv run --project "$root" avbpowertool config create --id "$id" --from-images --json
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

```python
# Python snippet inside a plugin
import json
import os
import subprocess

root = os.environ["AVBPOWERTOOL_ROOT"]
proc = subprocess.run(
    ["uv", "run", "--project", root, "avbpowertool", "plugin", "list", "--json"],
    cwd=root,
    capture_output=True,
    text=True,
)
data = json.loads(proc.stdout)
```

The command surface is documented, has an exit-code convention and a `--json` mode,
and that is where the stability promise lives.

**The alternative: `import avbpowertool`** and call the use cases / domain models
directly:

```python
import os
import sys

sys.path.insert(0, os.environ["AVBPOWERTOOL_ROOT"])
from avbpowertool.application.commands import PluginListRequest
from avbpowertool.application.services.manage_plugins import PluginListUseCase
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths

workspace = WorkspacePaths.discover(os.environ["AVBPOWERTOOL_ROOT"])
result = PluginListUseCase(workspace, language=os.environ["AVBPOWERTOOL_LANG"]).execute(
    PluginListRequest()
)
```

> **Unstable interface — a shortcut, not a contract.** Python module paths, class
> names, constructor signatures, and request/result fields carry no compatibility
> promise and may be refactored at any time; only the CLI command surface is stable.
> Prefer the CLI approach above unless the CLI genuinely cannot express what you need
> (reusing already-loaded objects inside one process, say). It also means the plugin
> shares this tool's interpreter environment, so dependency conflicts are yours.

## 7. Install / Uninstall / Run Examples

```shell
# List installed plugins (name already resolved for the current language)
avbpowertool plugin list
avbpowertool plugin list --json

# Install from a directory
avbpowertool plugin install ./my_plugin --json

# Install from a zip (add --force when it already exists)
avbpowertool plugin install ./my_plugin.zip --force --json

# Run: everything after -- belongs to the plugin
avbpowertool plugin run testkey_config_gen -- --core --8e --no_prompt
avbpowertool plugin run testkey_config_gen --json
avbpowertool plugin run testkey_config_gen --json -- --core

# Uninstall (--yes is a hard gate)
avbpowertool plugin uninstall my_plugin --yes --json
```

`--json` output shapes:

| Command | Top-level keys |
|---|---|
| `plugin list` | `plugins[]` (`plugin_id` / `name` / `entry` / `path`), `issues[]` |
| `plugin install` | `plugin_id`, `installed`, `file_count`, `issues[]` |
| `plugin uninstall` | `plugin_id`, `removed`, `removed_files`, `removed_bytes`, `issues[]` |
| `plugin run` | `plugin_id`, `exit_code`, `issues[]` |

> The `--json` of `plugin run` describes only what **this tool** saw: the plugin's own
> stdout/stderr still goes straight to the terminal and never enters the JSON. When
> you need machine-readable plugin output, have the plugin write a file or print to
> stderr itself.

## 8. TUI

The TUI has a **plugins page** that does exactly two things: list and run. Path to it:

```
Home
  [O] Other Features          <- route:misc
        [P] Plugins           <- action:plugin.manage
```

- **Selecting runs it**: every row is `display name (plugin_id)` (the display name is
  resolved from the manifest for the current language — see the resolution rules in
  section 2). Choosing a row asks for one confirmation and then runs that plugin.
- **An interactive plugin takes over the terminal**: curses is suspended before the run
  (`def_prog_mode` + `endwin`) and the terminal belongs entirely to the plugin — it may
  print progress and ask questions. When it exits, the curses state is restored
  (`reset_prog_mode` + redraw) and the plugins page comes back. No TUI borders or help
  bar are visible while the plugin runs; that is expected.
- **The TUI cannot pass arguments**: the argument list is always empty when a plugin is
  run from the TUI. Use the CLI when arguments are needed:

  ```shell
  avbpowertool plugin run testkey_config_gen -- --core --8e --no_prompt
  ```

- **Install / uninstall are CLI-only**: the TUI has no install or uninstall entry (both
  need a source path and an explicit confirmation — see section 3). With no plugins
  installed, the page points at `avbpowertool plugin install <dir|zip>`.
- **Plugins with a broken manifest**: a directory whose manifest cannot be parsed is
  never dropped silently — it is listed, as `[error_code] message` lines, both in the
  list screen and on the result screen. Those rows are not runnable plugins; choosing
  one only shows those messages.
- **The result screen**: it shows the plugin name/id, the `exit code`, and every issue
  (if any). **A non-zero exit code is not a tool error** — it is the plugin's own
  verdict; only a non-empty `issues[]` means the plugin never started.

## 9. Security

**This tool performs no security check on plugins at all**: no signature, no
permission model, no sandbox, no provenance check. `plugin install` merely copies a
directory/archive into `plugins/<id>/` and `plugin run` merely starts a subprocess
with an interpreter — the plugin gets your user's privileges and can read and write
everything in the workspace, including the private keys under `profiles/`.

What *is* enforced is **correctness** only:

- an archive member can never escape the target directory (absolute paths, drive
  letters, `:`, and `..` are refused);
- a plugin id is always a single directory name under `plugins/`;
- `entry` is always a bare file name inside the plugin directory, so a manifest can
  never address a script outside its own package.

Therefore: **only install and run plugins you trust; security is the user's
responsibility.**

---

## See Also

- [CLI Reference](CLI_REFERENCE.md) — syntax, flags, and exit codes of the `plugin` subcommands
- [Architecture](ARCHITECTURE.md) — layers and dependency direction (where the plugin code lives)
- [Backend API Reference](BACKEND_API.md) — call the same use cases from Python
- [Key Management](KEY_MANAGEMENT.md) — the key-store conventions a config-generating plugin relies on
