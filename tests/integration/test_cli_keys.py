"""CLI contract tests for the ``keys`` command group."""

from __future__ import annotations

import json
import os
from io import StringIO
from pathlib import Path

from avbpowertool.application.ports import AvbToolResult
from avbpowertool.presentation.cli.parser import build_parser, main

PUBLIC_KEY_BYTES = b"fake public key"


def _prepare_workspace(root: Path) -> Path:
    """Create an empty workspace layout (no profiles, no active profile)."""
    (root / "Images").mkdir(exist_ok=True)
    (root / "profiles").mkdir(exist_ok=True)
    (root / "Logs").mkdir(exist_ok=True)
    (root / ".avbpowertool-staging").mkdir(exist_ok=True)
    (root / "avbtool.py").write_text("# placeholder", encoding="utf-8")
    return root


def _key_dir(root: Path, profile_id: str) -> Path:
    """Create ``profiles/<id>/{profile.json,keys}`` and return the key dir.

    ``profile.json`` matters: ``ProfileRepository.list_profiles`` only
    considers directories that contain one, so an active-profile marker
    pointing at a profile without it resolves to nothing.
    """
    profile_dir = root / "profiles" / profile_id
    key_dir = profile_dir / "keys"
    key_dir.mkdir(parents=True, exist_ok=True)
    profile_json = profile_dir / "profile.json"
    if not profile_json.exists():
        profile_json.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "profile": {"id": profile_id, "name": profile_id},
                    "key_store_path": "keys",
                    "partitions": {},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return key_dir


def _write_manifest(key_dir: Path, manifest: dict[str, dict[str, str]]) -> None:
    (key_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _read_manifest(key_dir: Path) -> dict[str, dict[str, str]]:
    return json.loads((key_dir / "manifest.json").read_text(encoding="utf-8"))


def _activate(root: Path, profile_id: str) -> None:
    (root / ".active-profile").write_text(profile_id, encoding="utf-8")


def _run(argv: list[str]) -> tuple[int, str]:
    out = StringIO()
    try:
        code = main(argv, out=out)
    except SystemExit as exc:  # argparse --help / usage errors
        code = exc.code if isinstance(exc.code, int) else 2
    return code, out.getvalue()


class TestKeysHelp:
    def test_keys_help(self) -> None:
        code, _ = _run(["keys", "--help"])
        assert code == 0

    def test_keys_subcommand_help(self) -> None:
        for sub in ("list", "discover", "ensure-public", "add", "remove"):
            code, _ = _run(["keys", sub, "--help"])
            assert code == 0, sub

    def test_keys_requires_a_subcommand(self) -> None:
        parser = build_parser()
        try:
            parser.parse_args(["keys"])
        except SystemExit as exc:
            assert exc.code == 2
        else:  # pragma: no cover - argparse must reject a bare `keys`
            raise AssertionError("bare 'keys' should be rejected")


class TestKeysParserShape:
    def test_profile_defaults_to_current(self) -> None:
        parser = build_parser()
        for argv in (
            ["keys", "list"],
            ["keys", "discover"],
            ["keys", "ensure-public"],
            ["keys", "add", "k", "--file", "k.pem"],
            ["keys", "remove", "k"],
        ):
            assert parser.parse_args(argv).profile == "current", argv

    def test_discover_merge_is_the_default(self) -> None:
        parser = build_parser()
        assert parser.parse_args(["keys", "discover"]).merge is True
        assert parser.parse_args(["keys", "discover", "--merge"]).merge is True
        assert parser.parse_args(["keys", "discover", "--replace"]).merge is False

    def test_discover_merge_and_replace_are_mutually_exclusive(self) -> None:
        parser = build_parser()
        try:
            parser.parse_args(["keys", "discover", "--merge", "--replace"])
        except SystemExit as exc:
            assert exc.code == 2
        else:  # pragma: no cover - the group must reject both flags
            raise AssertionError("--merge and --replace must be mutually exclusive")

    def test_actions_are_stable_ids(self) -> None:
        parser = build_parser()
        assert parser.parse_args(["keys", "list"]).action_id == "keys.list"
        assert parser.parse_args(["keys", "discover"]).action_id == "keys.discover"
        assert parser.parse_args(["keys", "ensure-public"]).action_id == "keys.ensure_public"
        assert parser.parse_args(["keys", "add", "k", "--file", "k.pem"]).action_id == "keys.add"
        assert parser.parse_args(["keys", "remove", "k"]).action_id == "keys.remove"


class TestKeysCli:
    def test_list_json(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            key_dir = _key_dir(tmp_path, "device_a")
            (key_dir / "testkey_rsa4096.pem").write_text("fake key", encoding="utf-8")
            (key_dir / "loose.pem").write_text("fake loose", encoding="utf-8")
            _write_manifest(
                key_dir,
                {
                    "testkey_rsa4096": {
                        "private_key": "testkey_rsa4096.pem",
                        "public_key": "testkey_rsa4096_pub.bin",
                    }
                },
            )
            os.chdir(tmp_path)

            code, output = _run(["keys", "list", "--profile", "device_a", "--json"])
        finally:
            os.chdir(old_cwd)

        data = json.loads(output)
        assert code == 0
        assert data["issues"] == []
        assert data["keys"] == [{"key_id": "testkey_rsa4096", "filename": "testkey_rsa4096.pem"}]
        assert data["unregistered_pem_files"] == ["loose.pem"]

    def test_discover_json_merges(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            key_dir = _key_dir(tmp_path, "device_a")
            (key_dir / "testkey_rsa4096.pem").write_text("fake key", encoding="utf-8")
            (key_dir / "other.pem").write_text("fake other", encoding="utf-8")
            _write_manifest(
                key_dir,
                {
                    "testkey_rsa4096": {
                        "private_key": "testkey_rsa4096.pem",
                        "public_key": "testkey_rsa4096_pub.bin",
                        "public_key_sha1": "cd2c1e5e3c4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b",
                    }
                },
            )
            os.chdir(tmp_path)

            code, output = _run(["keys", "discover", "--profile", "device_a", "--json"])
            manifest = _read_manifest(key_dir)
        finally:
            os.chdir(old_cwd)

        data = json.loads(output)
        assert code == 0
        assert data["issues"] == []
        assert data["merged"] is True
        assert data["discovered_count"] == 2
        assert sorted(e["key_id"] for e in data["manifest_entries"]) == [
            "other",
            "testkey_rsa4096",
        ]
        # The cached public key survived the merge.
        assert manifest["testkey_rsa4096"]["public_key"] == "testkey_rsa4096_pub.bin"
        assert manifest["other"] == {"private_key": "other.pem"}

    def test_discover_replace_json_drops_public_keys(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            key_dir = _key_dir(tmp_path, "device_a")
            (key_dir / "testkey_rsa4096.pem").write_text("fake key", encoding="utf-8")
            _write_manifest(
                key_dir,
                {
                    "testkey_rsa4096": {
                        "private_key": "testkey_rsa4096.pem",
                        "public_key": "testkey_rsa4096_pub.bin",
                        "public_key_sha1": "cd2c1e5e",
                    },
                    "ghost": {"private_key": "ghost.pem"},
                },
            )
            os.chdir(tmp_path)

            code, output = _run(
                ["keys", "discover", "--profile", "device_a", "--replace", "--json"]
            )
            manifest = _read_manifest(key_dir)
        finally:
            os.chdir(old_cwd)

        data = json.loads(output)
        assert code == 0
        assert data["merged"] is False
        assert manifest == {"testkey_rsa4096": {"private_key": "testkey_rsa4096.pem"}}

    def test_ensure_public_json(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            key_dir = _key_dir(tmp_path, "device_a")
            (key_dir / "testkey_rsa4096.pem").write_text("fake key", encoding="utf-8")
            _write_manifest(
                key_dir,
                {
                    "testkey_rsa4096": {"private_key": "testkey_rsa4096.pem"},
                    "ghost": {"private_key": "ghost.pem"},
                },
            )
            os.chdir(tmp_path)

            # The CLI builds a real SubprocessAvbTool; stub it out so the
            # extraction is deterministic and no process is spawned.
            import avbpowertool.presentation.cli.handlers as handlers

            class _StubTool:
                def extract_public_key(self, key_path: Path, output_path: Path) -> AvbToolResult:
                    output_path.write_bytes(PUBLIC_KEY_BYTES)
                    return AvbToolResult(0, "", "", "extract_public_key")

            original = handlers._create_avb_tool
            handlers._create_avb_tool = lambda _ws: _StubTool()
            try:
                code, output = _run(["keys", "ensure-public", "--profile", "device_a", "--json"])
            finally:
                handlers._create_avb_tool = original
            manifest = _read_manifest(key_dir)
        finally:
            os.chdir(old_cwd)

        data = json.loads(output)
        assert code == 1  # the skipped entry reports keys.private_key_missing
        assert data["extracted"] == [
            {"key_id": "testkey_rsa4096", "public_key": "testkey_rsa4096.pem.bin"}
        ]
        assert data["skipped"] == ["ghost"]
        assert [i["error_code"] for i in data["issues"]] == ["keys.private_key_missing"]
        assert manifest["testkey_rsa4096"]["public_key"] == "testkey_rsa4096.pem.bin"

    def test_ensure_public_json_success_is_exit_zero(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            key_dir = _key_dir(tmp_path, "device_a")
            (key_dir / "testkey_rsa4096.pem").write_text("fake key", encoding="utf-8")
            _write_manifest(key_dir, {"testkey_rsa4096": {"private_key": "testkey_rsa4096.pem"}})
            os.chdir(tmp_path)

            import avbpowertool.presentation.cli.handlers as handlers

            class _StubTool:
                def extract_public_key(self, key_path: Path, output_path: Path) -> AvbToolResult:
                    output_path.write_bytes(PUBLIC_KEY_BYTES)
                    return AvbToolResult(0, "", "", "extract_public_key")

            original = handlers._create_avb_tool
            handlers._create_avb_tool = lambda _ws: _StubTool()
            try:
                code, output = _run(["keys", "ensure-public", "--profile", "device_a", "--json"])
            finally:
                handlers._create_avb_tool = original
        finally:
            os.chdir(old_cwd)

        data = json.loads(output)
        assert code == 0
        assert data["issues"] == []
        assert data["skipped"] == []
        assert data["extracted"] == [
            {"key_id": "testkey_rsa4096", "public_key": "testkey_rsa4096.pem.bin"}
        ]

    def test_add_and_remove_json(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            key_dir = _key_dir(tmp_path, "device_a")
            (key_dir / "release.pem").write_text("fake release", encoding="utf-8")
            _write_manifest(key_dir, {})
            os.chdir(tmp_path)

            add_code, add_output = _run(
                [
                    "keys",
                    "add",
                    "release",
                    "--file",
                    "release.pem",
                    "--profile",
                    "device_a",
                    "--json",
                ]
            )
            after_add = _read_manifest(key_dir)

            remove_code, remove_output = _run(
                ["keys", "remove", "release", "--profile", "device_a", "--json"]
            )
            after_remove = _read_manifest(key_dir)
        finally:
            os.chdir(old_cwd)

        assert add_code == 0
        assert json.loads(add_output) == {"key_id": "release", "issues": []}
        assert after_add == {"release": {"private_key": "release.pem"}}

        assert remove_code == 0
        assert json.loads(remove_output) == {"key_id": "release", "issues": []}
        assert after_remove == {}

    def test_add_and_remove_text_output(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            key_dir = _key_dir(tmp_path, "device_a")
            (key_dir / "release.pem").write_text("fake release", encoding="utf-8")
            _write_manifest(key_dir, {})
            os.chdir(tmp_path)

            add_code, add_output = _run(
                ["keys", "add", "release", "--file", "release.pem", "--profile", "device_a"]
            )
            remove_code, remove_output = _run(
                ["keys", "remove", "release", "--profile", "device_a"]
            )
        finally:
            os.chdir(old_cwd)

        assert add_code == 0
        assert "Added key: release" in add_output
        assert remove_code == 0
        assert "Removed key: release" in remove_output

    def test_list_text_output(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            key_dir = _key_dir(tmp_path, "device_a")
            (key_dir / "release.pem").write_text("fake release", encoding="utf-8")
            _write_manifest(key_dir, {"release": {"private_key": "release.pem"}})
            os.chdir(tmp_path)

            code, output = _run(["keys", "list", "--profile", "device_a"])
        finally:
            os.chdir(old_cwd)

        assert code == 0
        assert "release: release.pem" in output


class TestKeysActiveProfile:
    """Without ``--profile`` the commands act on the active profile."""

    def test_list_uses_active_profile(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            key_dir = _key_dir(tmp_path, "device_x")
            (key_dir / "active.pem").write_text("fake active", encoding="utf-8")
            _write_manifest(key_dir, {"active": {"private_key": "active.pem"}})
            _activate(tmp_path, "device_x")
            os.chdir(tmp_path)

            code, output = _run(["keys", "list", "--json"])
        finally:
            os.chdir(old_cwd)

        data = json.loads(output)
        assert code == 0
        assert data["issues"] == []
        assert data["keys"] == [{"key_id": "active", "filename": "active.pem"}]

    def test_discover_writes_to_active_profile(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            key_dir = _key_dir(tmp_path, "device_x")
            (key_dir / "active.pem").write_text("fake active", encoding="utf-8")
            _activate(tmp_path, "device_x")
            os.chdir(tmp_path)

            code, output = _run(["keys", "discover", "--json"])
            manifest = _read_manifest(key_dir)
        finally:
            os.chdir(old_cwd)

        assert code == 0
        assert json.loads(output)["issues"] == []
        assert manifest == {"active": {"private_key": "active.pem"}}

    def test_explicit_profile_wins_over_active_profile(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            active_dir = _key_dir(tmp_path, "device_x")
            _write_manifest(active_dir, {"active": {"private_key": "active.pem"}})
            other_dir = _key_dir(tmp_path, "device_y")
            _write_manifest(other_dir, {"other": {"private_key": "other.pem"}})
            _activate(tmp_path, "device_x")
            os.chdir(tmp_path)

            code, output = _run(["keys", "list", "--profile", "device_y", "--json"])
        finally:
            os.chdir(old_cwd)

        data = json.loads(output)
        assert code == 0
        assert data["keys"] == [{"key_id": "other", "filename": "other.pem"}]


class TestKeysErrorPaths:
    def test_unknown_profile_directory_not_found(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            os.chdir(tmp_path)

            code, output = _run(["keys", "list", "--profile", "nope", "--json"])
        finally:
            os.chdir(old_cwd)

        data = json.loads(output)
        assert code != 0
        assert data["issues"][0]["error_code"] == "keys.directory_not_found"
        # The resolved profile id and the key directory are in the message.
        assert "nope" in data["issues"][0]["message"]
        assert "keys" in data["issues"][0]["message"]

    def test_add_missing_file(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            key_dir = _key_dir(tmp_path, "device_a")
            _write_manifest(key_dir, {})
            os.chdir(tmp_path)

            code, output = _run(
                [
                    "keys",
                    "add",
                    "release",
                    "--file",
                    "missing.pem",
                    "--profile",
                    "device_a",
                    "--json",
                ]
            )
            manifest = _read_manifest(key_dir)
        finally:
            os.chdir(old_cwd)

        data = json.loads(output)
        assert code != 0
        assert data["issues"][0]["error_code"] == "keys.file_not_found"
        assert manifest == {}

    def test_remove_unknown_key(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            key_dir = _key_dir(tmp_path, "device_a")
            _write_manifest(key_dir, {"release": {"private_key": "release.pem"}})
            os.chdir(tmp_path)

            code, output = _run(["keys", "remove", "ghost", "--profile", "device_a", "--json"])
        finally:
            os.chdir(old_cwd)

        data = json.loads(output)
        assert code != 0
        assert data["issues"][0]["error_code"] == "keys.not_found"

    def test_add_existing_key(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            key_dir = _key_dir(tmp_path, "device_a")
            (key_dir / "release.pem").write_text("fake release", encoding="utf-8")
            _write_manifest(key_dir, {"release": {"private_key": "release.pem"}})
            os.chdir(tmp_path)

            code, output = _run(
                [
                    "keys",
                    "add",
                    "release",
                    "--file",
                    "release.pem",
                    "--profile",
                    "device_a",
                    "--json",
                ]
            )
        finally:
            os.chdir(old_cwd)

        data = json.loads(output)
        assert code != 0
        assert data["issues"][0]["error_code"] == "keys.already_exists"
