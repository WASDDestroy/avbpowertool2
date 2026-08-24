"""CLI output renderers — text and JSON formatters."""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from avbpowertool.application.commands import (
    ConfigEditResult,
    ConfigExportResult,
    ConfigImportResult,
    ConfigMigrateResult,
    ConfigShowResult,
    ConfigValidateResult,
    InspectImagesResult,
    KeyDiscoveryResult,
    LegacyImportResult,
    ProfileActivateResult,
    ProfileListResult,
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
                "manifest_entries": [
                    {"key_id": k, "filename": f} for k, f in result.manifest_entries
                ],
                "issues": _issues_to_dicts(result.issues),
            },
            out,
        )
        return

    _emit_text(f"Discovered {result.discovered_count} key(s):", out)
    for key_id, filename in result.manifest_entries:
        _emit_text(f"  {key_id}: {filename}", out)
    for iss in result.issues:
        _emit_text(f"  [{iss.error_code}] {iss.message}", out)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _named_partitions(result: ConfigShowResult) -> list[tuple[str, Any]]:
    """Return [(name, partition_config), ...] for display."""
    return [(p.partition_name, p) for p in result.partitions]


def exit_code_from_issues(issues: tuple[OperationIssue, ...]) -> int:
    """Map issues to a stable exit code."""
    if not issues:
        return 0
    codes = {i.error_code.split(".")[0] for i in issues}
    if "tool" in codes or "signing" in codes:
        return 3
    if "config" in codes or "keys" in codes:
        return 1
    if "image" in codes:
        return 1
    return 0
