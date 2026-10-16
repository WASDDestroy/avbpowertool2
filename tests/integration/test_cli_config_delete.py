"""CLI contract tests for ``config delete``."""

from __future__ import annotations

import json
import os
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

from avbpowertool.presentation.actions import ActionId
from avbpowertool.presentation.cli.parser import build_parser, main

_KEY_FILES: dict[str, bytes] = {
    "manifest.json": b'{"testkey_rsa4096": {"private_key": "testkey_rsa4096.pem"}}',
    "testkey_rsa4096.pem": b"-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n",
}


def _enter_workspace(root: Path) -> None:
    """Create an empty workspace layout and chdir into it."""
    (root / "Images").mkdir(exist_ok=True)
    (root / "profiles").mkdir(exist_ok=True)
    (root / "Logs").mkdir(exist_ok=True)
    (root / ".avbpowertool-staging").mkdir(exist_ok=True)
    (root / "avbtool.py").write_text("# placeholder", encoding="utf-8")
    os.chdir(root)


def _run(argv: list[str]) -> tuple[int, str]:
    out = StringIO()
    try:
        code = main(argv, out=out)
    except SystemExit as exc:  # --help exits through argparse
        code = exc.code if isinstance(exc.code, int) else 0
    return code, out.getvalue()


def _write_profile(root: Path, profile_id: str, *, name: str | None = None) -> None:
    """Create ``profiles/<id>/`` with a key store."""
    profile_dir = root / "profiles" / profile_id
    key_dir = profile_dir / "keys"
    key_dir.mkdir(parents=True, exist_ok=True)
    profile: dict[str, Any] = {
        "schema_version": 3,
        "profile": {"id": profile_id, "name": name if name is not None else profile_id},
        "key_store_path": "keys",
        "partitions": {
            "boot": {
                "image": "boot.img",
                "descriptor": "hash",
                "algorithm": "SHA256_RSA4096",
                "key_id": "testkey_rsa4096",
                "partition_name": "boot",
                "rollback_index": 0,
                "salt": "a1b2c3d4e5f6",
                "flags": 0,
            }
        },
    }
    (profile_dir / "profile.json").write_text(json.dumps(profile, indent=2), encoding="utf-8")
    for filename, payload in _KEY_FILES.items():
        (key_dir / filename).write_bytes(payload)


def _active_profile(root: Path) -> str | None:
    path = root / ".active-profile"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").strip()


class TestConfigDeleteParser:
    def test_parser_shape(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["config", "delete", "alpha", "--yes", "--force", "--json"])
        assert args.action_id == ActionId.CONFIG_DELETE
        assert args.profile == "alpha"
        assert args.yes is True
        assert args.force is True
        assert args.json is True

    def test_flags_default_to_false(self) -> None:
        args = build_parser().parse_args(["config", "delete", "alpha"])
        assert args.yes is False
        assert args.force is False
        assert args.json is False


class TestConfigDeleteCli:
    def test_without_yes_nothing_is_deleted(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            _write_profile(tmp_path, "alpha", name="Alpha")
            code, output = _run(["config", "delete", "alpha"])
        finally:
            os.chdir(old_cwd)

        assert code == 1
        assert output == ""
        assert (tmp_path / "profiles" / "alpha" / "profile.json").is_file()

    def test_without_yes_prints_the_gate_on_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            _write_profile(tmp_path, "alpha", name="Alpha")
            code, _output = _run(["config", "delete", "alpha"])
            err = capsys.readouterr().err
        finally:
            os.chdir(old_cwd)

        assert code == 1
        assert "This deletes the profile directory including its private keys." in err
        assert "Use --yes to confirm." in err
        assert (tmp_path / "profiles" / "alpha" / "profile.json").is_file()

    def test_yes_json_deletes_and_reports_stats(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            _write_profile(tmp_path, "alpha", name="Alpha")
            code, output = _run(["config", "delete", "alpha", "--yes", "--json"])
        finally:
            os.chdir(old_cwd)

        assert code == 0
        data = json.loads(output)
        assert set(data) == {
            "profile_id",
            "deleted",
            "deleted_files",
            "deleted_bytes",
            "issues",
        }
        assert data["profile_id"] == "alpha"
        assert data["deleted"] is True
        # profile.json + the two key-store files.
        assert data["deleted_files"] == 3
        assert data["deleted_bytes"] > 0
        assert data["issues"] == []
        assert not (tmp_path / "profiles" / "alpha").exists()

    def test_yes_text_output(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            _write_profile(tmp_path, "alpha", name="Alpha")
            code, output = _run(["config", "delete", "alpha", "--yes"])
        finally:
            os.chdir(old_cwd)

        assert code == 0
        assert "Deleted profile: alpha" in output
        assert "Files: 3" in output
        assert not (tmp_path / "profiles" / "alpha").exists()

    def test_yes_on_active_profile_is_forbidden(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            _write_profile(tmp_path, "alpha", name="Alpha")
            (tmp_path / ".active-profile").write_text("alpha", encoding="utf-8")
            code, output = _run(["config", "delete", "alpha", "--yes", "--json"])
        finally:
            os.chdir(old_cwd)

        assert code == 1
        data = json.loads(output)
        assert [i["error_code"] for i in data["issues"]] == ["config.active_delete_forbidden"]
        assert data["deleted"] is False
        assert (tmp_path / "profiles" / "alpha" / "profile.json").is_file()
        assert _active_profile(tmp_path) == "alpha"

    def test_force_deletes_active_profile_and_clears_pointer(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            _write_profile(tmp_path, "alpha", name="Alpha")
            (tmp_path / ".active-profile").write_text("alpha", encoding="utf-8")
            code, output = _run(["config", "delete", "alpha", "--yes", "--force", "--json"])
        finally:
            os.chdir(old_cwd)

        assert code == 0
        data = json.loads(output)
        assert data["deleted"] is True
        assert data["issues"] == []
        assert not (tmp_path / "profiles" / "alpha").exists()
        assert _active_profile(tmp_path) in (None, "")

    def test_force_keeps_a_pointer_to_another_profile(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            _write_profile(tmp_path, "alpha", name="Alpha")
            _write_profile(tmp_path, "beta", name="Beta")
            (tmp_path / ".active-profile").write_text("beta", encoding="utf-8")
            code, _output = _run(["config", "delete", "alpha", "--yes", "--force"])
        finally:
            os.chdir(old_cwd)

        assert code == 0
        assert not (tmp_path / "profiles" / "alpha").exists()
        assert _active_profile(tmp_path) == "beta"

    def test_missing_profile_exits_1(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            code, output = _run(["config", "delete", "missing", "--yes", "--json"])
        finally:
            os.chdir(old_cwd)

        assert code == 1
        data = json.loads(output)
        assert [i["error_code"] for i in data["issues"]] == ["config.not_found"]
        assert data["deleted"] is False

    def test_dot_dot_is_refused_and_workspace_survives(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            _write_profile(tmp_path, "alpha", name="Alpha")
            code, output = _run(["config", "delete", "..", "--yes", "--json"])
        finally:
            os.chdir(old_cwd)

        assert code == 1
        data = json.loads(output)
        assert [i["error_code"] for i in data["issues"]] == ["config.invalid_profile_id"]
        assert data["deleted"] is False
        # The workspace root and everything in it must still be there.
        assert tmp_path.is_dir()
        assert (tmp_path / "profiles").is_dir()
        assert (tmp_path / "profiles" / "alpha" / "profile.json").is_file()

    def test_help_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, _output = _run(["config", "delete", "--help"])
        captured = capsys.readouterr()
        assert code == 0
        # argparse writes --help straight to the process stdout.
        assert "profile" in captured.out
        assert "--yes" in captured.out
        assert "--force" in captured.out
