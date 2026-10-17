"""CLI output renderers — text and JSON formatters."""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from avbpowertool.application.commands import (
    CheckChainsResult,
    ConfigCreateFromImagesResult,
    ConfigCreateResult,
    ConfigEditResult,
    ConfigExportResult,
    ConfigImportResult,
    ConfigMigrateResult,
    ConfigShowResult,
    ConfigValidateResult,
    InspectImagesResult,
    KeyAddResult,
    KeyDiscoveryResult,
    KeyEnsurePublicResult,
    KeyListResult,
    KeyRemoveResult,
    LegacyImportResult,
    PluginInstallResult,
    PluginListResult,
    PluginPackResult,
    PluginRunResult,
    PluginUninstallResult,
    ProfileActivateResult,
    ProfileDeleteResult,
    ProfileListResult,
    ProfileRenameResult,
    SignImagesResult,
)
from avbpowertool.domain.models import OperationIssue


def _emit_json(data: Any, out: TextIO = sys.stdout) -> None:
    """Print JSON to stdout."""
    json.dump(data, out, indent=2, ensure_ascii=False, sort_keys=False)
    print(file=out)


def _emit_text(text: str, out: TextIO = sys.stdout) -> None:
    """Print text to stdout."""
    print(text, file=out)


def _issues_to_dicts(issues: tuple[OperationIssue, ...]) -> list[dict[str, str]]:
    return [{"error_code": i.error_code, "message": i.message} for i in issues]


# ---------------------------------------------------------------------------
# Inspect
# ---------------------------------------------------------------------------


def render_inspect(result: InspectImagesResult, as_json: bool, out: TextIO = sys.stdout) -> None:
    if as_json:
        _emit_json(
            {
                "images": [
                    {
                        "image_name": img.image_name,
                        "image_path": img.image_path,
                        "descriptor": img.descriptor.value if img.descriptor else None,
                        "algorithm": img.algorithm,
                        "partition_name": img.partition_name,
                        "public_key_sha1": img.public_key_sha1,
                        "rollback_index": img.rollback_index,
                        "salt": img.salt,
                        "digest": img.digest,
                        "flags": img.flags,
                        "props": [{"key": k, "value": v} for k, v in img.props],
                        "included_partitions": list(img.included_partitions),
                        "chain_partitions": [
                            {
                                "partition_name": c.partition_name,
                                "rollback_index_location": c.rollback_index_location,
                                "public_key_sha1": c.public_key_sha1,
                            }
                            for c in img.chain_descriptors
                        ],
                        "extensions": [{"key": k, "value": v} for k, v in img.raw_extensions],
                    }
                    for img in result.images
                ],
                "issues": _issues_to_dicts(result.issues),
            },
            out,
        )
        return

    for img in result.images:
        _emit_text(f"[{img.image_name}]", out)
        _emit_text(f"  Path:            {img.image_path}", out)
        _emit_text(f"  Descriptor:      {img.descriptor.value if img.descriptor else 'N/A'}", out)
        if img.algorithm:
            _emit_text(f"  Algorithm:       {img.algorithm}", out)
        if img.partition_name:
            _emit_text(f"  Partition Name:  {img.partition_name}", out)
        if img.public_key_sha1:
            _emit_text(f"  Public Key SHA1: {img.public_key_sha1}", out)
        if img.rollback_index is not None:
            _emit_text(f"  Rollback Index:  {img.rollback_index}", out)
        if img.salt:
            _emit_text(f"  Salt:            {img.salt}", out)
        if img.digest:
            _emit_text(f"  Digest:          {img.digest}", out)
        if img.flags:
            _emit_text(f"  Flags:           {img.flags}", out)
        for k, v in img.props:
            _emit_text(f"  Prop:            {k} -> {v}", out)
        if img.included_partitions:
            _emit_text(f"  Included:        {', '.join(img.included_partitions)}", out)
        for chain in img.chain_descriptors:
            _emit_text(
                f"  Chain:           {chain.partition_name} "
                f"slot={chain.rollback_index_location} "
                f"pubkey={chain.public_key_sha1 or 'N/A'}",
                out,
            )
        for k, v in img.raw_extensions:
            _emit_text(f"  {k}:  {v}", out)
        _emit_text("", out)
    for iss in result.issues:
        _emit_text(f"  [{iss.error_code}] {iss.message}", out)


# ---------------------------------------------------------------------------
# Sign
# ---------------------------------------------------------------------------


def render_sign(result: SignImagesResult, as_json: bool, out: TextIO = sys.stdout) -> None:
    if as_json:
        _emit_json(
            {
                "executed": result.executed,
                "success_count": result.success_count,
                "fail_count": result.fail_count,
                "plan": {
                    "profile_id": result.plan.profile_id,
                    "steps": [
                        {
                            "partition_name": s.partition_name,
                            "operation": s.operation,
                            "command": list(s.command),
                            "input_path": s.input_path,
                            "output_path": s.output_path,
                            "order": s.order,
                        }
                        for s in result.plan.steps
                    ],
                    "vbmeta_order": list(result.plan.vbmeta_order),
                },
                "issues": _issues_to_dicts(result.issues),
            },
            out,
        )
        return

    if result.executed:
        _emit_text(
            f"Signing complete: {result.success_count} succeeded, {result.fail_count} failed",
            out,
        )
    else:
        _emit_text(f"Signing Plan [DRY-RUN] — profile={result.plan.profile_id}", out)
        _emit_text("", out)

    for step in result.plan.steps:
        _emit_text(f"  [{step.order}] {step.operation} {step.partition_name}", out)
        _emit_text(f"       input : {step.input_path}", out)
        _emit_text(f"       output: {step.output_path}", out)
        _emit_text(f"       cmd   : {' '.join(step.command)}", out)
        _emit_text("", out)

    for iss in result.issues:
        _emit_text(f"  [{iss.error_code}] {iss.message}", out)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def render_config_show(result: ConfigShowResult, as_json: bool, out: TextIO = sys.stdout) -> None:
    if as_json:
        _emit_json(
            {
                "config_name": result.config_name,
                "partitions": [
                    {
                        "image_name": name,
                        "image": p.image,
                        "descriptor": p.descriptor.value,
                        "algorithm": p.algorithm.value,
                        "key_id": p.key_id,
                        "partition_name": p.partition_name,
                        "rollback_index": p.rollback_index,
                        "partition_size": p.partition_size,
                        "dynamic_partition_size": p.dynamic_partition_size,
                        "rollback_index_location": p.rollback_index_location,
                        "salt": p.salt,
                        "hash_algorithm": p.hash_algorithm,
                        "flags": p.flags,
                        "props": [[k, v] for k, v in p.props],
                        "included_partitions": list(p.included_partitions),
                        "include_descriptors_from_image": list(p.include_descriptors_from_image),
                        "chain_partitions": list(p.chain_partitions),
                        "chain_partitions_do_not_use_ab": list(p.chain_partitions_do_not_use_ab),
                    }
                    for name, p in _named_partitions(result)
                ],
                "issues": _issues_to_dicts(result.issues),
            },
            out,
        )
        return

    _emit_text(f"Config: {result.config_name}", out)
    for p in result.partitions:
        _emit_text(
            f"  [{p.partition_name}] descriptor={p.descriptor.value} "
            f"algorithm={p.algorithm.value} key={p.key_id}",
            out,
        )
    for iss in result.issues:
        _emit_text(f"  [{iss.error_code}] {iss.message}", out)


def render_config_validate(
    result: ConfigValidateResult, as_json: bool, out: TextIO = sys.stdout
) -> None:
    if as_json:
        _emit_json(
            {
                "config_name": result.config_name,
                "missing_images": list(result.missing_images),
                "missing_keys": list(result.missing_keys),
                "issues": _issues_to_dicts(result.issues),
            },
            out,
        )
        return

    _emit_text(f"Config: {result.config_name}", out)
    if result.missing_images:
        _emit_text(f"  Missing images: {', '.join(result.missing_images)}", out)
    if result.missing_keys:
        _emit_text(f"  Missing keys:   {', '.join(result.missing_keys)}", out)
    for iss in result.issues:
        _emit_text(f"  [{iss.error_code}] {iss.message}", out)


def render_config_create(
    result: ConfigCreateResult, as_json: bool, out: TextIO = sys.stdout
) -> None:
    if as_json:
        _emit_json(
            {
                "profile_id": result.profile_id,
                "created": result.created,
                "issues": _issues_to_dicts(result.issues),
            },
            out,
        )
        return

    if result.created:
        _emit_text(f"Created profile '{result.profile_id}'.", out)
    for iss in result.issues:
        _emit_text(f"  [{iss.error_code}] {iss.message}", out)


def render_config_create_from_images(
    result: ConfigCreateFromImagesResult, as_json: bool, out: TextIO = sys.stdout
) -> None:
    """Render the result of ``config create --from-images``."""
    if as_json:
        _emit_json(
            {
                "profile_id": result.profile_id,
                "created": result.created,
                "partition_count": result.partition_count,
                "chain_count": result.chain_count,
                "scanned_images": list(result.scanned_images),
                "skipped_images": list(result.skipped_images),
                "missing_keys": list(result.missing_keys),
                "issues": _issues_to_dicts(result.issues),
                "chain_issues": _issues_to_dicts(result.chain_issues),
            },
            out,
        )
        return

    if result.created:
        _emit_text(
            f"Created profile '{result.profile_id}' with {result.partition_count} partition(s) "
            f"and {result.chain_count} chain entr(ies).",
            out,
        )
    else:
        _emit_text(f"Profile '{result.profile_id}' was not created.", out)
    if result.scanned_images:
        _emit_text(f"  Scanned images: {', '.join(result.scanned_images)}", out)
    if result.skipped_images:
        _emit_text(f"  Skipped images: {', '.join(result.skipped_images)}", out)
    if result.missing_keys:
        _emit_text(f"  Missing keys:   {', '.join(result.missing_keys)}", out)
    for iss in result.issues:
        _emit_text(f"  [{iss.error_code}] {iss.message}", out)
    if result.chain_issues:
        # Informational only: the chains can be hardcoded later (that is what
        # plugins/testkey_config_gen/make-testkey-config does), so these never fail the command.
        _emit_text("Chain keys not resolved (informational):", out)
        for iss in result.chain_issues:
            _emit_text(f"  [{iss.error_code}] {iss.message}", out)
        _emit_text("  These entries do not affect the creation result or the exit code.", out)


# ---------------------------------------------------------------------------
# Import / Export
# ---------------------------------------------------------------------------


def render_import(result: ConfigImportResult, as_json: bool, out: TextIO = sys.stdout) -> None:
    if as_json:
        _emit_json(
            {"profile_id": result.profile_id, "issues": _issues_to_dicts(result.issues)},
            out,
        )
        return

    if result.profile_id:
        _emit_text(f"Successfully imported profile: {result.profile_id}", out)
    for iss in result.issues:
        _emit_text(f"  [{iss.error_code}] {iss.message}", out)


def render_export(result: ConfigExportResult, as_json: bool, out: TextIO = sys.stdout) -> None:
    if as_json:
        _emit_json(
            {"output_path": result.output_path, "issues": _issues_to_dicts(result.issues)},
            out,
        )
        return

    if not any(i.error_code.startswith("config.export") for i in result.issues):
        _emit_text(f"Exported to: {result.output_path}", out)
    for iss in result.issues:
        _emit_text(f"  [{iss.error_code}] {iss.message}", out)


def render_legacy_import(
    result: LegacyImportResult, as_json: bool, out: TextIO = sys.stdout
) -> None:
    if as_json:
        _emit_json(
            {
                "profile_id": result.profile_id,
                "partition_count": result.partition_count,
                "key_count": result.key_count,
                "issues": _issues_to_dicts(result.issues),
            },
            out,
        )
        return

    if result.profile_id:
        _emit_text(
            f"Imported legacy profile: {result.profile_id} "
            f"({result.partition_count} partitions, {result.key_count} keys)",
            out,
        )
    for iss in result.issues:
        _emit_text(f"  [{iss.error_code}] {iss.message}", out)


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


def render_profile_list(result: ProfileListResult, as_json: bool, out: TextIO = sys.stdout) -> None:
    if as_json:
        _emit_json(
            {
                "profiles": [
                    {
                        "profile_id": p.profile_id,
                        "name": p.name,
                        "is_active": p.is_active,
                        "partition_count": p.partition_count,
                    }
                    for p in result.profiles
                ],
                "active_profile_id": result.active_profile_id,
                "issues": _issues_to_dicts(result.issues),
            },
            out,
        )
        return

    if not result.profiles:
        _emit_text("No profiles found.", out)
        return

    for p in result.profiles:
        active = " (active)" if p.is_active else ""
        _emit_text(f"  {p.profile_id}: {p.name} [{p.partition_count} partitions]{active}", out)
    for iss in result.issues:
        _emit_text(f"  [{iss.error_code}] {iss.message}", out)


def render_profile_activate(
    result: ProfileActivateResult, as_json: bool, out: TextIO = sys.stdout
) -> None:
    if as_json:
        _emit_json(
            {"profile_id": result.profile_id, "issues": _issues_to_dicts(result.issues)},
            out,
        )
        return

    if not result.issues:
        _emit_text(f"Activated profile: {result.profile_id}", out)
    for iss in result.issues:
        _emit_text(f"  [{iss.error_code}] {iss.message}", out)


def render_config_rename(
    result: ProfileRenameResult,
    as_json: bool,
    out: TextIO = sys.stdout,
    active_profile_id: str | None = None,
) -> None:
    """Render the result of ``config rename``.

    ``active_profile_id`` is the workspace's active profile *after* the
    call; the text output uses it to show whether ``.active-profile``
    followed the rename.
    """
    if as_json:
        _emit_json(
            {
                "old_profile_id": result.old_profile_id,
                "profile_id": result.profile_id,
                "renamed": result.renamed,
                "name_changed": result.name_changed,
                "issues": _issues_to_dicts(result.issues),
            },
            out,
        )
        return

    if not result.issues:
        if result.renamed:
            _emit_text(f"Renamed profile '{result.old_profile_id}' to '{result.profile_id}'.", out)
        else:
            _emit_text(f"Profile '{result.profile_id}' kept its directory name.", out)
        _emit_text(f"  Display name:   {'changed' if result.name_changed else 'unchanged'}", out)
        if active_profile_id is not None:
            _emit_text(f"  Active profile: {active_profile_id}", out)
    for iss in result.issues:
        _emit_text(f"  [{iss.error_code}] {iss.message}", out)


def render_config_delete(
    result: ProfileDeleteResult, as_json: bool, out: TextIO = sys.stdout
) -> None:
    """Render the result of ``config delete``.

    The JSON contract is exactly ``profile_id`` / ``deleted`` /
    ``deleted_files`` / ``deleted_bytes`` / ``issues``.
    """
    if as_json:
        _emit_json(
            {
                "profile_id": result.profile_id,
                "deleted": result.deleted,
                "deleted_files": result.deleted_files,
                "deleted_bytes": result.deleted_bytes,
                "issues": _issues_to_dicts(result.issues),
            },
            out,
        )
        return

    if not result.issues:
        _emit_text(f"Deleted profile: {result.profile_id}", out)
        _emit_text(f"  Files: {result.deleted_files}", out)
        _emit_text(f"  Bytes: {result.deleted_bytes}", out)
    for iss in result.issues:
        _emit_text(f"  [{iss.error_code}] {iss.message}", out)


def render_config_check_chains(
    result: CheckChainsResult, as_json: bool, out: TextIO = sys.stdout
) -> None:
    """Render the result of ``config check-chains``.

    The JSON contract is exactly ``profile_id`` / ``checked`` / ``issues``;
    the text output lists every checked entry as OK or FAIL.
    """
    if as_json:
        _emit_json(
            {
                "profile_id": result.profile_id,
                "checked": result.checked,
                "issues": _issues_to_dicts(result.issues),
            },
            out,
        )
        return

    _emit_text(f"Profile: {result.profile_id}", out)
    if not result.entries:
        _emit_text("  No chain partitions to check.", out)
    for entry in result.entries:
        status = "OK  " if entry.ok else "FAIL"
        _emit_text(f"  {status} [{entry.partition_name}] {entry.entry}", out)
    failed = sum(1 for entry in result.entries if not entry.ok)
    _emit_text(
        f"Checked {result.checked} chain entr(ies): {result.checked - failed} OK, {failed} failed.",
        out,
    )
    for iss in result.issues:
        _emit_text(f"  [{iss.error_code}] {iss.message}", out)


# ---------------------------------------------------------------------------
# Config migrate / edit
# ---------------------------------------------------------------------------


def render_config_migrate(
    result: ConfigMigrateResult, as_json: bool, out: TextIO = sys.stdout
) -> None:
    if as_json:
        _emit_json(
            {
                "profile_id": result.profile_id,
                "migrated": result.migrated,
                "issues": _issues_to_dicts(result.issues),
            },
            out,
        )
        return

    if result.migrated and not result.issues:
        _emit_text(f"Migrated profile '{result.profile_id}' to schema v3.", out)
    elif not result.migrated and not result.issues:
        _emit_text(f"Profile '{result.profile_id}' is already up to date (v3).", out)
    for iss in result.issues:
        _emit_text(f"  [{iss.error_code}] {iss.message}", out)


def render_config_edit(result: ConfigEditResult, as_json: bool, out: TextIO = sys.stdout) -> None:
    if as_json:
        _emit_json(
            {
                "profile_id": result.profile_id,
                "partition_name": result.partition_name,
                "issues": _issues_to_dicts(result.issues),
            },
            out,
        )
        return

    if not result.issues:
        _emit_text(
            f"Updated partition '{result.partition_name}' in profile '{result.profile_id}'.",
            out,
        )
    for iss in result.issues:
        _emit_text(f"  [{iss.error_code}] {iss.message}", out)


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------


def render_key_discovery(
    result: KeyDiscoveryResult, as_json: bool, out: TextIO = sys.stdout
) -> None:
    if as_json:
        _emit_json(
            {
                "discovered_count": result.discovered_count,
                "retained_count": result.retained_count,
                "merged": result.merged,
                "manifest_entries": [
                    {"key_id": k, "filename": f} for k, f in result.manifest_entries
                ],
                "issues": _issues_to_dicts(result.issues),
            },
            out,
        )
        return

    mode = "merge" if result.merged else "replace"
    _emit_text(f"Discovered {result.discovered_count} key(s) ({mode}):", out)
    for key_id, filename in result.manifest_entries:
        _emit_text(f"  {key_id}: {filename}", out)
    if result.retained_count:
        _emit_text(
            f"  Retained {result.retained_count} manifest entry(ies) with no .pem on disk.", out
        )
    for iss in result.issues:
        _emit_text(f"  [{iss.error_code}] {iss.message}", out)


def render_key_list(result: KeyListResult, as_json: bool, out: TextIO = sys.stdout) -> None:
    if as_json:
        _emit_json(
            {
                "keys": [{"key_id": k, "filename": f} for k, f in result.manifest_entries],
                "unregistered_pem_files": list(result.pem_files_on_disk),
                "issues": _issues_to_dicts(result.issues),
            },
            out,
        )
        return

    if not result.manifest_entries:
        _emit_text("No keys registered.", out)
    for key_id, filename in result.manifest_entries:
        _emit_text(f"  {key_id}: {filename}", out)
    for filename in result.pem_files_on_disk:
        _emit_text(f"  (unregistered) {filename}", out)
    for iss in result.issues:
        _emit_text(f"  [{iss.error_code}] {iss.message}", out)


def render_key_ensure_public(
    result: KeyEnsurePublicResult, as_json: bool, out: TextIO = sys.stdout
) -> None:
    if as_json:
        _emit_json(
            {
                "extracted": [{"key_id": k, "public_key": f} for k, f in result.extracted],
                "skipped": list(result.skipped),
                "issues": _issues_to_dicts(result.issues),
            },
            out,
        )
        return

    if result.extracted:
        _emit_text(f"Extracted {len(result.extracted)} public key(s):", out)
        for key_id, filename in result.extracted:
            _emit_text(f"  {key_id}: {filename}", out)
    else:
        _emit_text("No public keys needed extraction.", out)
    if result.skipped:
        _emit_text(f"  Skipped {len(result.skipped)} key(s) without a private key.", out)
    for iss in result.issues:
        _emit_text(f"  [{iss.error_code}] {iss.message}", out)


def render_key_add(result: KeyAddResult, as_json: bool, out: TextIO = sys.stdout) -> None:
    if as_json:
        _emit_json(
            {"key_id": result.key_id, "issues": _issues_to_dicts(result.issues)},
            out,
        )
        return

    if not result.issues:
        _emit_text(f"Added key: {result.key_id}", out)
    for iss in result.issues:
        _emit_text(f"  [{iss.error_code}] {iss.message}", out)


def render_key_remove(result: KeyRemoveResult, as_json: bool, out: TextIO = sys.stdout) -> None:
    if as_json:
        _emit_json(
            {"key_id": result.key_id, "issues": _issues_to_dicts(result.issues)},
            out,
        )
        return

    if not result.issues:
        _emit_text(f"Removed key: {result.key_id}", out)
    for iss in result.issues:
        _emit_text(f"  [{iss.error_code}] {iss.message}", out)


# ---------------------------------------------------------------------------
# Plugins
# ---------------------------------------------------------------------------


def render_plugin_list(result: PluginListResult, as_json: bool, out: TextIO = sys.stdout) -> None:
    """Render the result of ``plugin list``.

    The JSON contract is exactly ``plugins`` (each with ``plugin_id`` /
    ``name`` / ``entry`` / ``version`` / ``version_name`` / ``path``) and
    ``issues``.  ``name`` is already resolved for the language the use case
    was built with.  Text mode appends ``v<version>`` — plus the optional
    ``version_name`` in parentheses — to the display name.
    """
    if as_json:
        _emit_json(
            {
                "plugins": [
                    {
                        "plugin_id": p.plugin_id,
                        "name": p.name,
                        "entry": p.entry,
                        "version": p.version,
                        "version_name": p.version_name,
                        "path": p.path,
                    }
                    for p in result.plugins
                ],
                "issues": _issues_to_dicts(result.issues),
            },
            out,
        )
        return

    if not result.plugins:
        _emit_text("No plugins installed.", out)
    for p in result.plugins:
        version = _plugin_version_label(p.version, p.version_name)
        _emit_text(f"{p.plugin_id}: {p.name} {version} [{p.entry}] ({p.path})", out)
    for iss in result.issues:
        _emit_text(f"  [{iss.error_code}] {iss.message}", out)


def render_plugin_pack(result: PluginPackResult, as_json: bool, out: TextIO = sys.stdout) -> None:
    """Render the result of ``plugin pack``.

    The JSON contract is exactly ``plugin_id`` / ``output_path`` /
    ``file_count`` / ``version`` / ``version_name`` /
    ``includes_key_material`` / ``issues``.  Text mode prints one line in the
    ``Packed <id> v<version> → <path> (<n> files)`` shape, plus a warning
    when the package carries key material (a ``keys/`` directory or a
    ``.pem``), because those files are packed like everything else.
    """
    if as_json:
        _emit_json(
            {
                "plugin_id": result.plugin_id,
                "output_path": result.output_path,
                "file_count": result.file_count,
                "version": result.version,
                "version_name": result.version_name,
                "includes_key_material": result.includes_key_material,
                "issues": _issues_to_dicts(result.issues),
            },
            out,
        )
        return

    if not result.issues:
        _emit_text(
            f"Packed {result.plugin_id} v{result.version} → "
            f"{result.output_path} ({result.file_count} files)",
            out,
        )
        if result.includes_key_material:
            _emit_text("包含密钥材料，会一起打包进 zip", out)
    for iss in result.issues:
        _emit_text(f"  [{iss.error_code}] {iss.message}", out)


def render_plugin_install(
    result: PluginInstallResult, as_json: bool, out: TextIO = sys.stdout
) -> None:
    """Render the result of ``plugin install``.

    The JSON contract is exactly ``plugin_id`` / ``installed`` /
    ``file_count`` / ``version`` / ``version_name`` / ``issues``.  A refused
    downgrade prints the ``plugin.downgrade`` message verbatim, so it names
    both the installed and the incoming version.
    """
    if as_json:
        _emit_json(
            {
                "plugin_id": result.plugin_id,
                "installed": result.installed,
                "file_count": result.file_count,
                "version": result.version,
                "version_name": result.version_name,
                "issues": _issues_to_dicts(result.issues),
            },
            out,
        )
        return

    if result.installed and not result.issues:
        _emit_text(f"Installed plugin: {result.plugin_id}", out)
        _emit_text(f"  Version: {_plugin_version_label(result.version, result.version_name)}", out)
        _emit_text(f"  Files: {result.file_count}", out)
    for iss in result.issues:
        _emit_text(f"  [{iss.error_code}] {iss.message}", out)


def render_plugin_uninstall(
    result: PluginUninstallResult, as_json: bool, out: TextIO = sys.stdout
) -> None:
    """Render the result of ``plugin uninstall``.

    The JSON contract is exactly ``plugin_id`` / ``removed`` /
    ``removed_files`` / ``removed_bytes`` / ``issues``.
    """
    if as_json:
        _emit_json(
            {
                "plugin_id": result.plugin_id,
                "removed": result.removed,
                "removed_files": result.removed_files,
                "removed_bytes": result.removed_bytes,
                "issues": _issues_to_dicts(result.issues),
            },
            out,
        )
        return

    if result.removed and not result.issues:
        _emit_text(f"Removed plugin: {result.plugin_id}", out)
        _emit_text(f"  Files: {result.removed_files}", out)
        _emit_text(f"  Bytes: {result.removed_bytes}", out)
    for iss in result.issues:
        _emit_text(f"  [{iss.error_code}] {iss.message}", out)


def render_plugin_run(result: PluginRunResult, as_json: bool, out: TextIO = sys.stdout) -> None:
    """Render the result of ``plugin run``.

    The JSON contract is exactly ``plugin_id`` / ``exit_code`` / ``issues``.

    In text mode a successful run prints nothing at all: the plugin owns
    stdio (it is interactive), so anything this tool added would land in
    the middle of the plugin's own output.  Only issues — which mean the
    plugin never started — are reported.
    """
    if as_json:
        _emit_json(
            {
                "plugin_id": result.plugin_id,
                "exit_code": result.exit_code,
                "issues": _issues_to_dicts(result.issues),
            },
            out,
        )
        return

    for iss in result.issues:
        _emit_text(f"  [{iss.error_code}] {iss.message}", out)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _named_partitions(result: ConfigShowResult) -> list[tuple[str, Any]]:
    """Return [(name, partition_config), ...] for display."""
    return [(p.partition_name, p) for p in result.partitions]


def _plugin_version_label(version: int, version_name: str) -> str:
    """Render ``v<version>`` with the optional ``(<version_name>)`` suffix."""
    if version_name:
        return f"v{version} ({version_name})"
    return f"v{version}"


def exit_code_from_issues(issues: tuple[OperationIssue, ...]) -> int:
    """Map issues to a stable exit code.

    Prefix mapping: ``tool.*`` / ``signing.*`` -> 3, ``config.*`` /
    ``keys.*`` / ``chain.*`` / ``image.*`` / ``plugin.*`` -> 1.  Any other
    prefix keeps returning 0 (an unknown code must not turn a success into
    a failure).

    ``plugin run`` is the one command that does not *only* use this: a
    plugin that started and exited non-zero has no issue at all, and its
    own exit code is returned instead.
    """
    if not issues:
        return 0
    codes = {i.error_code.split(".")[0] for i in issues}
    if "tool" in codes or "signing" in codes:
        return 3
    if codes & {"config", "keys", "chain", "image", "plugin"}:
        return 1
    return 0
