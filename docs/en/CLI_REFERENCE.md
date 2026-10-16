# CLI Reference

The complete reference for the AVBPowerTool2 command line: command surface,
argument semantics, exit codes, and error codes.

> Every command, flag, default, and usage string on this page was taken from
> the real `uv run avbpowertool <cmd> --help` output and checked against the
> implementation. Keep both language versions in sync when the command surface
> changes.

## Contents

- [1. Runtime and Conventions](#1-runtime-and-conventions)
- [2. Exit Codes](#2-exit-codes)
- [3. `--profile` and Profile Resolution](#3---profile-and-profile-resolution)
- [4. Command Reference](#4-command-reference)
  - [`image inspect` / `image sign`](#image-inspect--image-sign)
  - [`config show` / `config validate`](#config-show--config-validate)
  - [`config list` / `config activate`](#config-list--config-activate)
  - [`config create`](#config-create)
  - [`config edit`](#config-edit)
  - [`config check-chains`](#config-check-chains)
  - [`config rename`](#config-rename)
  - [`config delete`](#config-delete)
  - [`config import` / `config import-legacy` / `config export` / `config migrate`](#config-import--config-import-legacy--config-export--config-migrate)
  - [`keys` subcommands](#keys-subcommands)
  - [`about`](#about)
- [5. Error Code List](#5-error-code-list)
- [6. End-to-End Example](#6-end-to-end-example)

---

## 1. Runtime and Conventions

The CLI and the TUI share one entry point: with arguments it runs the CLI,
without arguments it launches the TUI.

```shell
avbpowertool image inspect boot vbmeta   # with arguments -> CLI
avbpowertool                             # no arguments   -> TUI
```

- **The workspace root is the current working directory.** `avbtool.py`,
  `Images/`, `profiles/`, `Logs/`, `.active-profile`, and
  `.avbpowertool-staging/` are all resolved relative to it. Every example on
  this page assumes you run it from the repository root.
- When the console script is not installed (or not on `PATH`), use
  `python -m avbpowertool ...` instead — it behaves identically.
- **`--json`**: supported by every subcommand except `about`. The output can be
  fed straight into PowerShell `ConvertFrom-Json`; failures are expressed as
  JSON too (`issues[].error_code` + `issues[].message`) together with a
  non-zero exit code.
- **Image name resolution**: the positional arguments of `image inspect` /
  `image sign` are **logical image names**, resolved to `<name>.img` under the
  workspace `Images/`. `config create --images` accepts both `boot` and
  `boot.img` (the `.img` suffix is stripped; duplicates keep their first
  position).
- **Read-only vs. writing**: `config show` / `config validate` /
  `config check-chains` / `image inspect` / `keys list` and every `--help` are
  read-only and never rewrite a file. `config edit` / `config create` /
  `config rename` / `config delete` / `keys ...` write to disk. Note that
  **every `save` rewrites the whole `profile.json` through `encode_profile`,
  reordering it and omitting default values**, so hand-formatted JSON is not
  preserved.
- **Deprecated aliases**: `read` / `sign` / `get_all_config` / `check_l10n` are
  still accepted, but they print a deprecation warning and forward to the new
  command; their behaviour is no longer guaranteed separately.

---

## 2. Exit Codes

| Exit code | Triggered by |
|---|---|
| `0` | Success. Also used for issues whose error-code prefix is in none of the classes below — an unknown prefix never turns a success into a failure |
| `1` | Any issue prefixed `config.*` / `keys.*` / `image.*` / `chain.*`; plus three explicit cases: `config validate` reporting `missing_images` / `missing_keys`; `image sign --execute` without `--yes` (stderr: `This will modify image files. Use --yes to confirm.`); `config delete` without `--yes` (stderr: `This deletes the profile directory including its private keys. Use --yes to confirm.`) |
| `2` | argparse usage error: unknown command or flag, missing required argument, mutually exclusive flags given together (`--from-images` + `--allow-empty`, `--activate` + `--no-activate`, `--merge` + `--replace`), and `config create --overwrite` without `--from-images` |
| `3` | Any issue prefixed `tool.*` / `signing.*` (an avbtool subprocess failure, a failed signing step) |

The mapping lives in
`avbpowertool/presentation/cli/renderer.py::exit_code_from_issues`: if **any**
issue belongs to a higher-priority class, that class's exit code wins
(`tool` / `signing` outrank `config` / `keys` / `chain` / `image`).

Typical use in a script:

```powershell
avbpowertool config check-chains --profile my_config --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "chain check failed" }
```

---

## 3. `--profile` and Profile Resolution

`config show` / `config validate` / `config check-chains` / `image sign` accept
`--profile PROFILE`, defaulting to `current`. Resolution is **literal-first**,
in this fixed order:

```
1. PROFILE is non-empty and profiles/<PROFILE>/profile.json exists -> use PROFILE
2. PROFILE is "current" (or empty) and .active-profile points at an existing
   profile                                                          -> use that id
3. Otherwise -> ConfigError:
     - a current/empty request with no active profile -> config.no_active_profile
     - anything else                                  -> config.not_found
```

Key points:

- **Literal-first** means a profile that is really named `current` always works
  (`profiles/current/profile.json` wins over `.active-profile`). This is kept
  for backward compatibility.
- `.active-profile` holds a profile id; pointing at a directory that does not
  exist counts as "no active profile".
- "Exists" means `profiles/<id>/profile.json` exists — a bare directory without
  `profile.json` is not a profile.
- **The no-active-profile failure** (measured):

  ```shell
  $ avbpowertool config show --json
  {
    "config_name": "current",
    "partitions": [],
    "issues": [
      {
        "error_code": "config.no_active_profile",
        "message": "No active profile; use 'config activate' or pass an explicit --profile"
      }
    ]
  }
  # exit 1
  ```

- **Key-store use cases resolve leniently**: `keys list` / `keys discover` /
  `keys ensure-public` / `keys add` / `keys remove` apply the same
  "literal-first + current→active" resolution, but **a non-empty request that
  fails to resolve is used literally** and the use case reports
  `keys.directory_not_found` itself. That is what lets the create wizard prepare
  `profiles/<id>/keys/` before `profile.json` is written. Only an empty request
  with no active profile reports `config.no_active_profile` directly.
- `config edit` / `config migrate` also default `--profile` to `current` and use
  the strict resolution above (`config.no_active_profile` when there is no
  active profile). Their `--help` text only says `(default: current)`; the
  behaviour matches the table.
- `config export` / `config rename` / `config delete` / `config import-legacy`
  do **not** accept `--profile`: they take the id as a positional argument (a
  script always knows the id).

---

## 4. Command Reference

### `image inspect` / `image sign`

```
avbpowertool image inspect [-h] [--cert] [--json] images [images ...]
avbpowertool image sign    [-h] [--dry-run] [--execute] [--yes] [--profile PROFILE]
                              [--remove-footers] [--json] images [images ...]
```

`image inspect` (read-only, **the only command that does not need a profile**)

| Argument | Meaning |
|---|---|
| `images` (one or more, required) | Logical image names, resolved to `Images/<name>.img` |
| `--cert` | Also read the certificate (passed to avbtool as `--cert`) |
| `--json` | JSON output |

Top-level `--json` keys: `images[]`, `issues[]`. Each `images[]` entry has
`image_name` / `image_path` / `descriptor` / `algorithm` / `partition_name` /
`public_key_sha1` / `rollback_index` / `salt` / `digest` / `flags` / `props[]` /
`included_partitions[]` / `chain_partitions[]` (with `partition_name`,
`rollback_index_location`, `public_key_sha1`) / `extensions[]`.
A `null` `descriptor` means the image has no AVB structure
(`image.no_vbmeta_structure`).

`image sign`

| Argument | Meaning |
|---|---|
| `images` (one or more, required) | Logical image names |
| `--dry-run` | Build the signing plan without executing. **This is already the default** (`store_true` + `default=True`); passing it explicitly is only for readability |
| `--execute` | Actually sign (requires `--yes`). Passing it overrides `--dry-run` to false |
| `--yes` | Confirm execution. Without it, `--execute` only prints a notice and exits with code 1, **modifying nothing** |
| `--profile PROFILE` | Profile id, default `current` (resolved to the active profile per section 3) |
| `--remove-footers` | Remove existing footers first |
| `--json` | JSON output |

Top-level `--json` keys: `executed` / `success_count` / `fail_count` / `plan`
(with `profile_id` / `steps[]` / `vbmeta_order[]`) / `issues[]`.
`plan.steps[]` is the **plan**; under `--dry-run`, `executed` is `false`.

### `config show` / `config validate`

```
avbpowertool config show     [-h] [--profile PROFILE] [--json]
avbpowertool config validate [-h] [--profile PROFILE] [--json]
```

Both are **read-only**.

- `config show --json` top-level keys: `config_name`, `partitions[]`, `issues[]`.
  Each partition has `image_name` / `image` / `descriptor` / `algorithm` /
  `key_id` / `partition_name` / `rollback_index` / `partition_size` /
  `dynamic_partition_size` / `rollback_index_location` / `salt` /
  `hash_algorithm` / `flags` / `props[]` (array of `[key, value]` pairs) /
  `included_partitions[]` / `include_descriptors_from_image[]` /
  `chain_partitions[]` / `chain_partitions_do_not_use_ab[]`.
- `config validate --json` top-level keys: `config_name`, `missing_images[]`,
  `missing_keys[]`, `issues[]`. **Non-empty `missing_images` / `missing_keys`
  also make the exit code 1** (they are returned as data, not as issues), so a
  script only needs to test the exit code.

### `config list` / `config activate`

```
avbpowertool config list     [-h] [--json]
avbpowertool config activate [-h] [--json] profile
```

- `config list --json`: `profiles[]` (`profile_id` / `name` / `is_active` /
  `partition_count`), `active_profile_id` (`null` when nothing is active),
  `issues[]`.
- `config activate <profile>` writes `<profile>` into `.active-profile`.
  An unknown id gives `config.not_found`; a write failure gives
  `config.activate_failed`. Deleting the active profile is refused
  (`config.active_delete_forbidden`).

### `config create`

```
avbpowertool config create [-h] --id PROFILE_ID [--name PROFILE_NAME]
                           [--from-images [DIR] | --allow-empty]
                           [--images NAMES] [--key KEY_ID]
                           [--no-chain-resolve] [--include-fallback]
                           [--skip-non-avb] [--overwrite]
                           [--activate | --no-activate] [--json]
```

| Argument | Meaning |
|---|---|
| `--id PROFILE_ID` (required) | New profile id, also the directory name. Must contain only letters, digits, `_`, `-`, `.`, otherwise `config.invalid_profile_id` (it is **never** silently rewritten) |
| `--name PROFILE_NAME` | Display name, defaulting to the value of `--id` |
| `--from-images [DIR]` | Generate the partitions from images. **Without a value = the workspace `Images/`**; with a value = that directory |
| `--allow-empty` | Allow creating a profile with no partitions (`config.no_partitions` is filtered out) |
| `--images NAMES` | Comma-separated image names (`boot,dtbo` or `boot.img`), repeatable; only meaningful with `--from-images` |
| `--key KEY_ID` | Use one key_id for every generated partition; by default it is chosen automatically |
| `--no-chain-resolve` | Do not resolve the chain partitions read from the vbmeta images (resolving **is** the default) |
| `--include-fallback` | Fall back to "every other scanned partition" when the embedded descriptors were all pruned (off by default, see below) |
| `--skip-non-avb` | Skip images without an AVB structure instead of failing |
| `--overwrite` | Reuse an existing profile directory (its `keys/` are kept, its partitions replaced); requires `--from-images`, otherwise exit code 2 |
| `--activate` / `--no-activate` | Whether to write `.active-profile`. **The default is not to activate** (`--no-activate` is the default) |
| `--json` | JSON output |

**`--allow-empty` and `--from-images` are mutually exclusive**: argparse rejects
the combination with exit code 2:

```
avbpowertool config create: error: argument --from-images: not allowed with argument --allow-empty
```

(Note: the plan document said this conflict maps to
`config.invalid_option_combination`; the implementation is an argparse mutually
exclusive group, exit code 2, with no issue produced.)

The `--allow-empty` path (`ConfigCreateUseCase`)

- Writes `profiles/<id>/profile.json` (empty `partitions`),
  `profiles/<id>/keys/`, and an empty `keys/manifest.json` **only when none
  exists yet** (it never overwrites discovered keys).
- An existing id gives `config.profile_exists`.
- `--overwrite` **requires `--from-images`**: on this path — and on the plain
  path where neither `--from-images` nor `--allow-empty` is given — it is
  rejected with `error: --overwrite requires --from-images` on stderr and exit
  code 2, and nothing is written.
- Top-level `--json` keys: `profile_id`, `created`, `issues[]`.

The `--from-images` path (`ConfigCreateFromImagesUseCase`) — the order is fixed
and every early return **leaves the workspace untouched**:

1. the id must already be valid, otherwise `config.invalid_profile_id`;
2. an existing `profiles/<id>/` without `--overwrite` gives
   `config.profile_exists`;
3. **every explicitly requested `--images` entry must exist**, otherwise
   `image.not_found` (and nothing is created). An empty `--images` scans every
   `*.img` in the directory (sorted by name);
4. each image is inspected with `info_image`;
5. **an image without AVB structure is fatal by default**: it produces
   `image.no_vbmeta_structure` and the command fails; only `--skip-non-avb`
   skips it, recording it in `skipped_images`;
6. if no partition could be generated at all, `config.no_partitions` (use
   `--allow-empty` when you really want an empty profile);
7. the profile is written (`--overwrite` keeps the existing `keys/`); a chain
   resolution failure **does not block creation**: when the chain public keys
   cannot be found in the key store they are recorded in `chain_issues`
   (informational), which **does not influence the exit code** — `created`
   stays `true`, the exit code stays 0 and the note is still printed in full;
8. the new profile is validated once and `missing_keys` is merged into the
   result (**informational only — missing keys never fail the creation**).

`--include-fallback` semantics: when a vbmeta's embedded descriptors are all
pruned from the scanned set, the CLI **keeps the pruned result by default**
(possibly empty); if that vbmeta ends up with neither `included_partitions` nor
`chain_partitions`, `config.vbmeta_no_contents` is reported (exit code 1, but
the profile **is still created**). Only `--include-fallback` restores the TUI
wizard's historical behaviour of falling back to "every other scanned non-vbmeta
partition". (The "report `config.vbmeta_no_contents`" note in the plan document
is exactly the validation issue above, not a separate failure branch.)

Top-level `--json` keys: `profile_id`, `created`, `partition_count`,
`chain_count`, `scanned_images[]`, `skipped_images[]`, `missing_keys[]`,
`issues[]`, and `chain_issues[]` (the same `{error_code, message}` shape as
`issues[]`; failed chain resolutions appear **only** there and never in
`issues[]`, so they cannot change the exit code).

Top-level `--json` keys: `profile_id`, `created`, `partition_count`,
`chain_count`, `scanned_images[]`, `skipped_images[]`, `missing_keys[]`,
`issues[]`.

### `config edit`

```
avbpowertool config edit [-h] [--profile PROFILE] [--set FIELD=VALUE]
                         [--unset FIELD] [--append FIELD=ITEM]
                         [--remove FIELD=ITEM] [--json] partition
```

Edits the fields of **one partition**; `partition` is a positional argument
(the partition name, e.g. `boot`).

| Argument | Meaning |
|---|---|
| `--profile PROFILE` | Profile id, default `current` |
| `--set FIELD=VALUE` | Set a field, **replacing the whole field**. Repeatable. Booleans are `true`/`false` (also accepts `1`/`yes`/`on`) |
| `--unset FIELD` | Reset a field to its empty value: `str -> ''`, `int -> 0`, `bool -> false`, `tuple -> ()`. Repeatable |
| `--append FIELD=ITEM` | Append one item to a **tuple field**. Repeatable |
| `--remove FIELD=ITEM` | Remove matching items from a **tuple field**. Repeatable |
| `--json` | JSON output |

**Editable field whitelist** (the whitelist is the only entry point; any other
field gives `config.invalid_field`):

| Kind | Fields |
|---|---|
| Integers | `partition_size`, `rollback_index`, `rollback_index_location`, `flags`, `block_size`, `fec_num_roots`, `padding_size` |
| Booleans | `dynamic_partition_size`, `do_not_generate_fec`, `calc_max_image_size`, `do_not_append_vbmeta_image`, `no_hashtree`, `check_at_most_once`, `setup_as_rootfs_from_kernel`, `use_persistent_digest`, `do_not_use_ab`, `set_hashtree_disabled_flag`, `set_verification_disabled_flag`, `print_required_libavb_version` |
| Strings | `salt`, `hash_algorithm`, `output_vbmeta_image`, `setup_rootfs_from_kernel`, `signing_helper`, `signing_helper_with_files`, `public_key_metadata`, `append_to_release_string`, **`key_id`** |
| Algorithm enum | **`algorithm`** (through `SigningAlgorithm.from_str`; an invalid value gives `config.invalid_algorithm`) |
| Image file | **`image`** (must end in `.img`, otherwise `config.invalid_field`) |
| Tuples | `kernel_cmdlines`, `chain_partitions`, `chain_partitions_do_not_use_ab`, `included_partitions`, `include_descriptors_from_image`, **`props`**, **`prop_from_file`** |

(The bold entries are the ones added by this CLI extension: `key_id` /
`algorithm` / `image` / `props` / `prop_from_file`.)

Value syntax:

- Tuple fields are **comma-separated**: `--set kernel_cmdlines=a,b`,
  `--set included_partitions=boot,system`. `--set` replaces the whole tuple.
- `props` / `prop_from_file` are `KEY:VALUE` / `KEY:PATH` pairs, also
  comma-separated: `--set props=key1:val1,key2:val2`. A value may contain `:`
  (only the first `:` separates key and value); an empty key or a missing `:`
  gives `config.invalid_field`.
- `--append props=key:value` accepts **exactly one** `KEY:VALUE` pair at a time.
- `key_id` may be set to the empty string (NONE partitions): `--set key_id=` is
  valid.
- `--unset image` / `--unset algorithm` are refused (they do not accept empty
  values), reporting `config.invalid_field` / `config.invalid_algorithm`
  respectively; `--unset key_id` and `--unset props` work.

**`--append` / `--remove` tuple semantics**

- Plain tuple fields: append one item / remove the exact match.
- `chain_partitions` / `chain_partitions_do_not_use_ab` (the chain fields):
  - `--append` requires **a full `PART:SLOT:KEYFILE` triple**, with a plain
    numeric `SLOT >= 1` and a non-empty `KEYFILE`; a bare `boot:3` is rejected
    with `config.invalid_field`. `KEYFILE` may itself contain `:` (only the
    first two `:` are separators, so Windows paths work).
  - `--append` **merges by partition name, replacing in place**: if that
    partition is already chained, its entry is replaced and **keeps its
    position** — no duplicate is created, and unlike `--set` the other chains
    read back from the image are not wiped. This is exactly the
    "hardcode the chains + replace by name" semantics.
  - `--remove` **matches by partition name**: a bare partition name
    (`--remove chain_partitions=vbmeta_vendor`) or a full triple both work.
- Order of application: every `--remove` first, then every `--append`; the order
  within one invocation is stable.

**Conflict rejection**: the same field cannot be given in both the
whole-field form (`--set` / `--unset`) and the item form (`--append` /
`--remove`); that reports `config.invalid_option_combination` and **leaves the
disk untouched**:

```
[config.invalid_option_combination] Field(s) chain_partitions given in both
--set/--unset and --append/--remove; use one form per field
[config.invalid_option_combination] Field(s) flags given in both --set and --unset;
use one form per field
```

The conflict is **per field**: `--set flags=1 --append chain_partitions=...`
touches two different fields and is allowed.

**Other failures**: a partition that is not in the profile gives
`config.partition_missing`; a directory whose name disagrees with the
`profile.id` inside `profile.json` gives `config.profile_id_mismatch` (writing is
refused so nothing lands in a different profile); a write failure gives
`config.save_failed`. **Any issue means nothing is written** (parsing and
validation happen first, `save` last).

Top-level `--json` keys: `profile_id`, `partition_name`, `issues[]`.

### `config check-chains`

```
avbpowertool config check-chains [-h] [--profile PROFILE] [--json]
```

A **read-only** check (the only file it may create is a temporary public key
under `.avbpowertool-staging/check-chains/`). It walks **every `chain_partitions`
entry of every partition** and reports all problems at once instead of stopping
at the first. Checks:

1. entry format: `PART:SLOT:KEYFILE` with a numeric `SLOT >= 1` — otherwise
   `chain.malformed_entry`;
2. is `PART` in the profile? — otherwise `config.missing_included_partition`
   (and the check returns, since nothing can be compared);
3. is the chained partition **unsigned** (`algorithm = NONE`)? — then
   `chain.chained_partition_unsigned` (a chain check is meaningless; returns);
4. does `KEYFILE` exist in the key store (relative paths resolve against
   `profiles/<id>/keys/`)? — otherwise `chain.key_file_missing`;
5. is the chained partition's `key_id` in the manifest? — otherwise
   `config.key_missing`; a public key that cannot be read or extracted gives
   `keys.public_key_extract_failed`;
6. **does the SHA1 of `KEYFILE` equal the SHA1 of the public key of the key the
   chained partition is actually signed with?** — if not, `chain.key_mismatch`
   (this is the check that finds a "chain entry public key disagrees with the
   actual signing key", and it is the current failure of this repository's real
   profile).

Public keys come from the manifest's cached `public_key` file when it exists;
otherwise `avbtool extract_public_key` is used into the staging directory
(**never** into the key store).

Top-level `--json` keys: `profile_id`, `checked` (number of entries checked),
`issues[]`, `entries[]` (each with `partition_name` / `entry` / `ok`). The text
mode looks like:

```
Profile: e2e
  FAIL [vbmeta] vbmeta_system:2:testkey_rsa2048.pem.bin
Checked 1 chain entr(ies): 0 OK, 1 failed.
  [chain.key_mismatch] Partition 'vbmeta': chain entry '...' uses '...' (sha1 ...), but '...' is signed with key id '...' (public key '...', sha1 ...)
```

### `config rename`

```
avbpowertool config rename [-h] [--name NEW_NAME] [--json] OLD NEW
```

| Argument | Meaning |
|---|---|
| `OLD` (required) | Current profile id (directory name) |
| `NEW` (required) | New profile id (directory name). **Use the same value as `OLD` to only set the display name** |
| `--name NEW_NAME` | New display name, defaulting to the current one |
| `--json` | JSON output |

Order of operations (every failure returns before anything else is written):

1. `NEW` must pass the id check unchanged, otherwise `config.invalid_profile_id`;
2. `profiles/<OLD>/profile.json` must exist (a bare directory does not count),
   otherwise `config.not_found`;
3. `profiles/<NEW>` must not already exist (unless it is the old profile
   itself), otherwise `config.profile_exists`;
4. the directory is moved; an `OSError` (a locked directory on Windows, for
   instance) triggers a best-effort rollback and then `config.rename_failed`, so
   no half-renamed profile is left behind;
5. `profile.json` is rewritten with `profile.id = NEW` (and `profile.name` when
   `--name` was given), preserving the "directory name == profile.id" invariant;
6. `.active-profile` follows the rename when it pointed at `OLD`.

With `OLD == NEW` no directory move happens (`renamed` is `false`) and only the
display name is written — plus the embedded id when it disagreed with the
directory.

Top-level `--json` keys: `old_profile_id`, `profile_id`, `renamed`,
`name_changed`, `issues[]`.

### `config delete`

```
avbpowertool config delete [-h] [--yes] [--force] [--json] profile
```

A **destructive** command: it removes the whole `profiles/<profile>/`
directory, **including the private keys** under `keys/`. There is no recycle
bin, no soft delete, and no "clean up by prefix/timestamp" batching — one
explicit id per invocation.

| Argument | Meaning |
|---|---|
| `profile` (required) | Profile id (directory name) to delete |
| `--yes` | **Hard gate**: without it nothing is deleted; it prints `This deletes the profile directory including its private keys. Use --yes to confirm.` to stderr and returns exit code `1` |
| `--force` | Allow deleting the **active** profile; `.active-profile` is cleared afterwards when it pointed at the deleted id |
| `--json` | JSON output |

Order of operations (every failure returns before anything is removed):

1. **the `--yes` gate**: without it the message above goes to stderr with exit
   code `1`, and no use case is even constructed;
2. **id safety check**: an empty id, `.` / `..`, or an id containing a path
   separator (`/`, `\`) gives `config.invalid_profile_id`; it then confirms that
   `profiles/<id>` resolves to a **direct** child of `profiles/`, and otherwise
   reports `config.invalid_profile_id` too (this keeps `rmtree` from escaping
   into the workspace or above it);
3. `profiles/<profile>/profile.json` must exist (a bare directory does not
   count), otherwise `config.not_found`;
4. the **active** profile is refused with `config.active_delete_forbidden`
   unless `--force` is given, and the directory stays untouched;
5. the regular files and bytes under the directory are **counted before the
   removal**, so `deleted_files` / `deleted_bytes` describe what was deleted;
6. the directory is removed; an `OSError` (a locked file on Windows, for
   instance) reports `config.delete_failed`, with `deleted` staying `false`;
7. when step 4 was forced and `.active-profile` holds **exactly** the deleted
   id, that file is unlinked (a missing file is ignored); a pointer to
   **another** profile is left alone.

Top-level `--json` keys: `profile_id`, `deleted`, `deleted_files`,
`deleted_bytes`, `issues[]`. On success `deleted` is `true`; the text mode
looks like:

```
Deleted profile: my_testkey_config
  Files: 12
  Bytes: 40960
```

> The TUI agrees with the default: its config manager refuses to delete the
> active profile too (`config.active_delete_forbidden`). `--force` exists in
> the CLI only.

### `config import` / `config import-legacy` / `config export` / `config migrate`

```
avbpowertool config import        [-h] [--json] archive
avbpowertool config import-legacy [-h] [--name PROFILE_ID] [--no-activate] [--json] archive
avbpowertool config export        [-h] [--output OUTPUT] [--json] profile
avbpowertool config migrate       [-h] [--profile PROFILE] [--json]
```

- `config import <archive>`: import a profile from a ZIP archive. A missing
  archive gives `config.not_found`; an invalid ZIP gives `config.invalid_archive`;
  an existing profile with the same name gives `config.profile_exists`.
  `--json` keys: `profile_id`, `issues[]`.
- `config import-legacy <archive>`: import a v1 (AVBPowerTool 1.x) config and
  convert it to the current schema. `--name PROFILE_ID` sets the new id (by
  default it is derived from the archive); `--no-activate` skips activation
  (the default **does** activate). v1 BATCH archives are rejected explicitly
  (`import.legacy.batch_not_supported`). `--json` keys: `profile_id`,
  `partition_count`, `key_count`, `issues[]`.
- `config export <profile>`: export to a ZIP; `--output` defaults to
  `<profile>.zip`. `--json` keys: `output_path`, `issues[]`. The archive holds
  `manifest.json` + `profile.json` + `keys/**` (both `.pem` and `.pem.bin`) and
  **no images**.
- `config migrate [--profile ID]`: upgrade an on-disk v2 profile to v3. A v2
  profile is already migrated in memory when read (the file is untouched); this
  command is what writes v3 back. `--json` keys: `profile_id`, `migrated`,
  `issues[]`.

### `keys` subcommands

```
avbpowertool keys list          [-h] [--profile PROFILE] [--json]
avbpowertool keys discover      [-h] [--profile PROFILE] [--merge | --replace] [--json]
avbpowertool keys ensure-public [-h] [--profile PROFILE] [--json]
avbpowertool keys add           [-h] --file NAME.pem [--profile PROFILE] [--json] key_id
avbpowertool keys remove        [-h] [--profile PROFILE] [--json] key_id
```

All five accept `--profile PROFILE` (default `current`, resolved per section 3
in its **lenient** form). A missing key-store directory reports
`keys.directory_not_found`.

**`keys list`** — lists the keys registered in the manifest plus the `.pem`
files on disk that are **not registered yet**. `--json` keys: `keys[]`
(`key_id` / `filename`), `unregistered_pem_files[]`, `issues[]`.

**`keys discover`** — scans the `.pem` files in `keys/` and writes them into
`manifest.json`, using the filename minus `.pem` as the key_id. Two mutually
exclusive modes:

| Flag | Semantics |
|---|---|
| `--merge` (**default**) | The manifest already on disk is the baseline. Each discovered `.pem` updates its own entry's `private_key`; the cached `public_key` / `public_key_sha1` are kept **only while the entry still points at the same private-key filename** (a renamed file means the cache belongs to a different key). Entries whose `.pem` no longer exists on disk are **left untouched**, never deleted |
| `--replace` | The historical behaviour: the manifest is rebuilt from the discovered `.pem` files only, dropping every cached `public_key` |

`--json` keys: `discovered_count`, `retained_count` (entries kept that have no
matching `.pem`), `merged`, `manifest_entries[]` (`key_id` / `filename`),
`issues[]`.

**`keys ensure-public`** — materialises the missing public-key files for every
manifest entry (`avbtool extract_public_key` into `<private_key>.pem.bin`, or
the entry's existing `public_key` name) and writes `public_key` back into the
manifest. An entry whose private key file is missing is recorded in `skipped`
and reports `keys.private_key_missing`; an extraction failure reports
`keys.public_key_extract_failed`. `--json` keys: `extracted[]` (`key_id` /
`public_key`), `skipped[]`, `issues[]`.

**`keys add <key_id> --file NAME.pem`** — adds a `key_id -> filename` mapping to
the manifest. `--file` is a private-key filename **inside the key store**
(**no** file is copied from elsewhere). A missing file gives
`keys.file_not_found`; an existing key_id gives `keys.already_exists`.
`--json` keys: `key_id`, `issues[]`.

**`keys remove <key_id>`** — removes the entry from the manifest (**without
deleting the `.pem` file**). An unknown key_id gives `keys.not_found`.
`--json` keys: `key_id`, `issues[]`.

> **Important**: the public-key file in a chain-partition entry must be an
> `extract_public_key` product (`*.pem.bin`). avbtool reads the third field of
> `chain_partition` as **raw bytes**, so passing a `.pem` corrupts the vbmeta.
> See [KEY_MANAGEMENT.md](KEY_MANAGEMENT.md).

### `about`

```
avbpowertool about [-h]
```

Prints the version string (e.g. `AVBPowerTool 2.0.0.dev0`) and exits 0. It does
not support `--json`.

---

## 5. Error Code List

Error codes are stable and dot-prefixed. Use cases return them as
`OperationIssue` tuples (**never** as exceptions). The "Exit" column is the
result of the `exit_code_from_issues` mapping.

### `config.*` → exit code 1

| Error code | Meaning |
|---|---|
| `config.not_found` | Profile (or archive) not found (`config delete` reports it for a missing target too) |
| `config.no_active_profile` | `current`/empty was requested but nothing is active |
| `config.invalid_profile_id` | The id contains illegal characters (only letters, digits, `_`, `-`, `.` are allowed); `config delete` also rejects an empty id, `.`, `..`, any path separator, and an id that does not resolve to a direct child of `profiles/` |
| `config.profile_exists` | A profile with that name already exists |
| `config.no_partitions` | The profile has no partitions |
| `config.invalid_field` | A `config edit` field is not whitelisted, or its value is invalid |
| `config.invalid_algorithm` | `algorithm` is not a valid signing algorithm |
| `config.invalid_option_combination` | The same field was given in both `--set/--unset` and `--append/--remove`; or `use_persistent_digest` without `do_not_use_ab` |
| `config.partition_missing` | Partition not in the profile |
| `config.profile_id_mismatch` | The directory name disagrees with the `profile.id` inside `profile.json`; the write is refused |
| `config.auto_dir_not_found` | The `--from-images DIR` directory does not exist |
| `config.missing_included_partition` | A vbmeta includes/chains a partition that is not in the profile |
| `config.missing_image` | The partition's `image` is empty |
| `config.missing_partition_name` | The partition has no `partition_name` |
| `config.missing_partition_size` | A hash partition has neither `partition_size` nor `dynamic_partition_size` |
| `config.invalid_partition_size` | `partition_size` is invalid (not positive / not a multiple of 4096 / too small) |
| `config.invalid_block_size` | `block_size` is not a positive power of 2 |
| `config.invalid_fec_num_roots` | `fec_num_roots` is outside 2..255 |
| `config.invalid_chain_partition` | A chain entry is not `PART:SLOT:KEY_PATH`, or SLOT < 1 |
| `config.invalid_prop` | A `props` / `prop_from_file` key is empty |
| `config.duplicate_rollback_slot` | Several chain partitions share one rollback slot |
| `config.vbmeta_no_contents` | A vbmeta has neither `included_partitions` nor `chain_partitions` |
| `config.cycle_detected` | The vbmeta dependency graph has a cycle |
| `config.missing_chain_partition` | A chain reference has no matching partition |
| `config.key_missing` | The partition's `key_id` is empty, or the key_id is not in the manifest |
| `config.missing_profile_id` / `config.missing_profile_name` | The profile id / name is missing |
| `config.invalid_schema_version` | Unsupported `schema_version` |
| `config.parse_error` | `profile.json` cannot be parsed |
| `config.invalid_archive` | Invalid archive format |
| `config.import_failed` / `config.export_failed` | Import / export failed |
| `config.create_failed` / `config.save_failed` / `config.migrate_failed` / `config.rename_failed` / `config.activate_failed` / `config.delete_failed` | The corresponding write operation failed (`config.delete_failed` is a failing `rmtree` in `config delete`, which leaves `deleted` at `false`) |
| `config.load_error` | Reading the profile failed |
| `config.active_delete_forbidden` | Refused to delete the active profile (`config delete` needs `--force` for that) |
| `config.unsupported_descriptor` | The signing plan met an unsupported descriptor type |

### `keys.*` → exit code 1

| Error code | Meaning |
|---|---|
| `keys.directory_not_found` | The key-store directory does not exist |
| `keys.file_not_found` | The private-key file named by `keys add` does not exist |
| `keys.not_found` | The `keys remove` key_id is not in the manifest |
| `keys.already_exists` | The `keys add` key_id already exists |
| `keys.private_key_missing` | An entry's private-key file is missing during `ensure-public` |
| `keys.public_key_extract_failed` | Public-key extraction failed (`ensure-public` / `check-chains`) |
| `keys.manifest_not_found` | `keys/manifest.json` does not exist |
| `keys.manifest_read_error` | Reading the manifest failed |
| `keys.invalid_request` | `keys add` is missing the key_id or the filename |
| `keys.invalid_entry` / `keys.empty_private_key` / `keys.empty_manifest` / `keys.missing_private_key` | Manifest validation problems |

### `image.*` → exit code 1

| Error code | Meaning |
|---|---|
| `image.not_found` | The image file does not exist |
| `image.no_vbmeta_structure` | The image has no AVB structure (no footer) |

### `chain.*` → exit code 1

| Error code | Meaning |
|---|---|
| `chain.malformed_entry` | A chain entry is not a valid `PART:SLOT:KEYFILE` |
| `chain.key_file_missing` | The public-key file a chain entry points at is not in the key store |
| `chain.key_mismatch` | The chain entry's public-key SHA1 differs from the SHA1 of the key the chained partition is actually signed with |
| `chain.chained_partition_unsigned` | The chained partition is NONE (unsigned), so a chain check is meaningless |
| `chain.key_not_found` | No key in the store matched the descriptor's public-key SHA1 during chain resolution (`config create --from-images` reports this code but does **not** block creation). There it is **informational**: it only appears in `chain_issues[]` (rendered as its own section in text output) and **never fails the command on its own**; in `config check-chains` and friends it still maps to exit code 1 |

### `tool.*` / `signing.*` → exit code 3

| Error code | Meaning |
|---|---|
| `tool.execution_failed` | The avbtool subprocess returned non-zero |
| `signing.step_failed` | A signing step failed |

### Others (exit code 0 unless an issue from the classes above is present too)

| Error code | Meaning |
|---|---|
| `workspace.root_not_found` | The workspace root does not exist |
| `workspace.path_escape` | A path escapes `Images/` |
| `import.legacy.*` | v1 legacy conversion (`batch_not_supported`, `key_not_found`, `invalid_entry`, `partial_chain`, `unsupported_algorithm`, `block_size_conflict`, `failed`) |

---

## 6. End-to-End Example

The complete flow below needs **zero hand-edited JSON**: generate a profile from
images → hardcode the chains, flags, key, and algorithm → check the chains →
rename → export. The example id is `my_testkey_config`.

```shell
# 1) Generate the profile and read the partitions back from the images
#    (a wrapper script computes the image set from its own flag table)
avbpowertool config create --id 20260101-120000_testkey --name testkey \
  --from-images \
  --images boot,dtbo,init_boot,pvmfw,recovery,vendor_boot,vbmeta,vbmeta_system \
  --json

# 1b) Keys: drop profiles/<id>/keys/*.pem in first, then discover + extract public keys
avbpowertool keys discover      --profile 20260101-120000_testkey --json
avbpowertool keys ensure-public --profile 20260101-120000_testkey --json

# 2) Hardcode the chains (merged by partition name) + vbmeta flags=1
avbpowertool config edit vbmeta --profile 20260101-120000_testkey --set flags=1 \
  --append chain_partitions=boot:3:testkey_rsa4096.pem.bin \
  --append chain_partitions=recovery:1:testkey_rsa4096.pem.bin \
  --append chain_partitions=vbmeta_system:2:testkey_rsa2048.pem.bin \
  --json

# 3) Switch vbmeta_system to a 2048 key + SHA256_RSA2048
avbpowertool config edit vbmeta_system --profile 20260101-120000_testkey \
  --set key_id=testkey_rsa2048 --set algorithm=SHA256_RSA2048 --json

# 4) Prune an embedded descriptor (--remove matches whole items on plain tuple fields)
avbpowertool config edit vbmeta --profile 20260101-120000_testkey \
  --remove included_partitions=odm --json

# 5) Check chain consistency (read-only)
avbpowertool config check-chains --profile 20260101-120000_testkey --json

# 6) Rename (directory id and display name)
avbpowertool config rename 20260101-120000_testkey my_testkey_config \
  --name "My testkey config" --json

# 7) Export
avbpowertool config export my_testkey_config --output my_testkey_config.zip --json

# 8) Activate it and preview the signing plan
avbpowertool config activate my_testkey_config
avbpowertool image sign boot vbmeta --dry-run --json

# 9) Clean up: delete the profile (destructive, --yes is mandatory;
#    an active profile additionally needs --force)
avbpowertool config delete my_testkey_config --yes --force --json
```

Every step can be gated on the exit code:

```powershell
function Invoke-Avb { param([string[]]$Args)
  & avbpowertool @Args
  if ($LASTEXITCODE -ne 0) { throw "avbpowertool failed: $($Args -join ' ') (exit $LASTEXITCODE)" }
}
Invoke-Avb @('config','check-chains','--profile','my_testkey_config','--json')
```

---

## See Also

- [Creating a Configuration](CONFIG_CREATION.md) — create profiles from the CLI / TUI / API
- [Key Management](KEY_MANAGEMENT.md) — key store, manifest, and public-key file requirements
- [Backend API Reference](BACKEND_API.md) — call the same use cases from Python
- [README](../../README.md) — installation and quick start
