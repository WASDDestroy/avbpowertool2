"""CLI contract tests for ``config rename``."""

from __future__ import annotations

import json
import os
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

from avbpowertool.presentation.cli.parser import main

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


def _write_profile(
    root: Path,
    profile_id: str,
    *,
    name: str | None = None,
    embedded_id: str | None = None,
) -> None:
    """Create ``profiles/<id>/`` with a key store and an optional stale id."""
    profile_dir = root / "profiles" / profile_id
    key_dir = profile_dir / "keys"
    key_dir.mkdir(parents=True, exist_ok=True)
    profile = {
        "schema_version": 3,
        "profile": {
            "id": embedded_id if embedded_id is not None else profile_id,
            "name": name if name is not None else profile_id,
        },
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


def _read_profile(root: Path, profile_id: str) -> dict[str, Any]:
    path = root / "profiles" / profile_id / "profile.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _active_profile(root: Path) -> str | None:
    path = root / ".active-profile"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").strip()


class TestConfigRenameCli:
    def test_rename_json_success(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            _write_profile(tmp_path, "alpha", name="Alpha")
            code, output = _run(["config", "rename", "alpha", "gamma", "--json"])
        finally:
            os.chdir(old_cwd)

        assert code == 0
        data = json.loads(output)
        assert set(data) == {
            "old_profile_id",
            "profile_id",
            "renamed",
            "name_changed",
            "issues",
        }
        assert data["old_profile_id"] == "alpha"
        assert data["profile_id"] == "gamma"
        assert data["renamed"] is True
        assert data["name_changed"] is False
        assert data["issues"] == []

        assert not (tmp_path / "profiles" / "alpha").exists()
        on_disk = _read_profile(tmp_path, "gamma")
        assert on_disk["profile"]["id"] == "gamma"
        assert on_disk["profile"]["name"] == "Alpha"
        # ``save`` re-encodes the profile (defaults are omitted), so compare
        # the meaningful field values instead of the raw dict.
        boot = on_disk["partitions"]["boot"]
        assert boot["image"] == "boot.img"
        assert boot["algorithm"] == "SHA256_RSA4096"
        assert boot["key_id"] == "testkey_rsa4096"
        assert boot["salt"] == "a1b2c3d4e5f6"
        for filename, payload in _KEY_FILES.items():
            assert (tmp_path / "profiles" / "gamma" / "keys" / filename).read_bytes() == payload

    def test_rename_updates_active_profile(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            _write_profile(tmp_path, "alpha", name="Alpha")
            (tmp_path / ".active-profile").write_text("alpha", encoding="utf-8")
            code, _output = _run(["config", "rename", "alpha", "gamma"])
        finally:
            os.chdir(old_cwd)

        assert code == 0
        assert _active_profile(tmp_path) == "gamma"

    def test_rename_keeps_other_active_profile(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            _write_profile(tmp_path, "alpha", name="Alpha")
            _write_profile(tmp_path, "beta", name="Beta")
            (tmp_path / ".active-profile").write_text("beta", encoding="utf-8")
            code, _output = _run(["config", "rename", "alpha", "gamma"])
        finally:
            os.chdir(old_cwd)

        assert code == 0
        assert _active_profile(tmp_path) == "beta"

    def test_name_only_change_is_reported_in_text(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            _write_profile(tmp_path, "alpha", name="Alpha")
            code, output = _run(["config", "rename", "alpha", "alpha", "--name", "New Alpha"])
        finally:
            os.chdir(old_cwd)

        assert code == 0
        assert "kept its directory name" in output
        assert "Display name:   changed" in output
        assert _read_profile(tmp_path, "alpha")["profile"]["name"] == "New Alpha"

    def test_rename_text_shows_active_profile(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            _write_profile(tmp_path, "alpha", name="Alpha")
            (tmp_path / ".active-profile").write_text("alpha", encoding="utf-8")
            code, output = _run(["config", "rename", "alpha", "gamma"])
        finally:
            os.chdir(old_cwd)

        assert code == 0
        assert "Renamed profile 'alpha' to 'gamma'." in output
        assert "Active profile: gamma" in output

    def test_missing_profile_exits_1(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            code, output = _run(["config", "rename", "missing", "gamma", "--json"])
        finally:
            os.chdir(old_cwd)

        assert code == 1
        data = json.loads(output)
        assert [i["error_code"] for i in data["issues"]] == ["config.not_found"]
        assert not (tmp_path / "profiles" / "gamma").exists()

    def test_existing_target_exits_1_without_touching_old(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            _write_profile(tmp_path, "alpha", name="Alpha")
            _write_profile(tmp_path, "beta", name="Beta")
            alpha_before = (tmp_path / "profiles" / "alpha" / "profile.json").read_bytes()
            code, output = _run(["config", "rename", "alpha", "beta", "--json"])
            alpha_after = (tmp_path / "profiles" / "alpha" / "profile.json").read_bytes()
        finally:
            os.chdir(old_cwd)

        assert code == 1
        data = json.loads(output)
        assert [i["error_code"] for i in data["issues"]] == ["config.profile_exists"]
        assert alpha_after == alpha_before
        assert _read_profile(tmp_path, "beta")["profile"]["name"] == "Beta"

    def test_invalid_new_id_exits_1(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            _write_profile(tmp_path, "alpha", name="Alpha")
            code, output = _run(["config", "rename", "alpha", "bad id!", "--json"])
        finally:
            os.chdir(old_cwd)

        assert code == 1
        data = json.loads(output)
        assert [i["error_code"] for i in data["issues"]] == ["config.invalid_profile_id"]
        assert (tmp_path / "profiles" / "alpha").is_dir()
        assert not (tmp_path / "profiles" / "bad_id_").exists()

    def test_rename_repairs_dirty_embedded_id_and_edit_works(self, tmp_path: Path) -> None:
        """A stale embedded id is repaired, so ``config edit`` works afterwards."""
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            _write_profile(tmp_path, "alpha", name="Alpha", embedded_id="beta")
            rename_code, _output = _run(["config", "rename", "alpha", "gamma", "--json"])
            edit_code, edit_output = _run(
                ["config", "edit", "boot", "--profile", "gamma", "--set", "flags=7", "--json"]
            )
        finally:
            os.chdir(old_cwd)

        assert rename_code == 0
        assert edit_code == 0
        assert json.loads(edit_output)["issues"] == []
        assert _read_profile(tmp_path, "gamma")["profile"]["id"] == "gamma"
        assert _read_profile(tmp_path, "gamma")["partitions"]["boot"]["flags"] == 7

    def test_help_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, _output = _run(["config", "rename", "--help"])
        captured = capsys.readouterr()
        assert code == 0
        # argparse writes --help straight to the process stdout.
        assert "OLD" in captured.out
        assert "NEW" in captured.out
        assert "--name" in captured.out
