"""CLI contract tests for ``config create --from-images``."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from io import StringIO
from pathlib import Path

import pytest

from avbpowertool.application.ports import AvbToolResult
from avbpowertool.presentation.cli.parser import main
from tests.conftest import AVBTOOL_OUTPUT_DIR

SAMPLE_HASH = (AVBTOOL_OUTPUT_DIR / "hash_descriptor.txt").read_text(encoding="utf-8")
SAMPLE_NO_FOOTER = (AVBTOOL_OUTPUT_DIR / "no_footer_stderr.txt").read_text(encoding="utf-8")
#: The boot fixture, re-labelled so several distinct partitions can be scanned.
HASH_DTBO = SAMPLE_HASH.replace("Partition Name:        boot", "Partition Name:        dtbo")

#: A vbmeta image embedding exactly one descriptor, for the scanned ``boot``.
VBMETA_EMBEDDING_BOOT = """\
Footer version:           1.0
Image size:               4096 bytes
Algorithm:                SHA256_RSA4096
Rollback Index:           0
Flags:                    0
Rollback Index Location:  0
Release String:           'avbtool 1.3.0'
Descriptors:
    Hash descriptor:
      Image Size:            4194304 bytes
      Hash Algorithm:        sha256
      Partition Name:        boot
      Salt:                  aabbccddeeff
      Digest:                1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b
      Flags:                 0
"""


def _ok(stdout: str) -> AvbToolResult:
    return AvbToolResult(0, stdout, "", "info_image")


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
    except SystemExit as exc:  # --help / argparse usage errors
        code = exc.code if isinstance(exc.code, int) else 2
    return code, out.getvalue()


def _read_profile(root: Path, profile_id: str) -> dict[str, object]:
    path = root / "profiles" / profile_id / "profile.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _partitions(root: Path, profile_id: str) -> dict[str, object]:
    partitions = _read_profile(root, profile_id)["partitions"]
    assert isinstance(partitions, dict)
    return partitions


class _StubAvbTool:
    """``inspect_image`` answers per image stem; no process is spawned."""

    def __init__(self, outputs: dict[str, AvbToolResult]) -> None:
        self._outputs = outputs

    def inspect_image(self, image_path: Path, cert: bool = False) -> AvbToolResult:
        return self._outputs.get(image_path.stem, AvbToolResult(0, "", "", "info_image"))


@contextmanager
def _stub_avb_tool(outputs: dict[str, AvbToolResult]) -> Iterator[None]:
    """Replace the CLI's avbtool factory for the duration of the block."""
    import avbpowertool.presentation.cli.handlers as handlers

    original = handlers._create_avb_tool
    handlers._create_avb_tool = lambda _ws: _StubAvbTool(outputs)
    try:
        yield
    finally:
        handlers._create_avb_tool = original


class TestConfigCreateFromImagesCli:
    def test_from_images_json_success(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            (tmp_path / "Images" / "boot.img").write_bytes(b"x" * 8192)
            (tmp_path / "Images" / "vbmeta.img").write_bytes(b"x" * 4096)
            with _stub_avb_tool({"boot": _ok(SAMPLE_HASH), "vbmeta": _ok(VBMETA_EMBEDDING_BOOT)}):
                code, output = _run(["config", "create", "--id", "dev", "--from-images", "--json"])
        finally:
            os.chdir(old_cwd)

        assert code == 0
        data = json.loads(output)
        assert data["profile_id"] == "dev"
        assert data["created"] is True
        assert data["partition_count"] == 2
        assert data["chain_count"] == 0
        assert data["scanned_images"] == ["boot", "vbmeta"]
        assert data["skipped_images"] == []
        # The store is empty, so nothing is invented for the unsigned boot
        # partition; the signed vbmeta keeps its (empty) key_id reported.
        assert data["missing_keys"] == [""]
        assert data["issues"] == []
        assert set(_partitions(tmp_path, "dev")) == {"boot", "vbmeta"}

    def test_from_images_text_output(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            (tmp_path / "Images" / "boot.img").write_bytes(b"x" * 4096)
            with _stub_avb_tool({"boot": _ok(SAMPLE_HASH)}):
                code, output = _run(["config", "create", "--id", "dev", "--from-images"])
        finally:
            os.chdir(old_cwd)

        assert code == 0
        assert "Created profile 'dev' with 1 partition(s) and 0 chain entr(ies)." in output
        assert "Scanned images: boot" in output
        # The only partition is unsigned, so it needs no key at all.
        assert "Missing keys:" not in output

    def test_explicit_image_directory(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            (tmp_path / "other").mkdir()
            (tmp_path / "other" / "boot.img").write_bytes(b"x" * 4096)
            with _stub_avb_tool({"boot": _ok(SAMPLE_HASH)}):
                code, output = _run(
                    ["config", "create", "--id", "dev", "--from-images", "other", "--json"]
                )
        finally:
            os.chdir(old_cwd)

        assert code == 0
        data = json.loads(output)
        assert data["created"] is True
        assert data["scanned_images"] == ["boot"]
        assert set(_partitions(tmp_path, "dev")) == {"boot"}

    def test_images_restricts_the_scan(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            for name in ("boot", "dtbo", "vbmeta"):
                (tmp_path / "Images" / f"{name}.img").write_bytes(b"x" * 4096)
            with _stub_avb_tool(
                {
                    "boot": _ok(SAMPLE_HASH),
                    "dtbo": _ok(HASH_DTBO),
                    "vbmeta": _ok(VBMETA_EMBEDDING_BOOT),
                }
            ):
                code, output = _run(
                    [
                        "config",
                        "create",
                        "--id",
                        "dev",
                        "--from-images",
                        "--images",
                        "dtbo,boot.img",
                        "--json",
                    ]
                )
        finally:
            os.chdir(old_cwd)

        assert code == 0
        data = json.loads(output)
        # Both names are accepted (bare and with .img) and the scan keeps
        # the directory order.
        assert data["scanned_images"] == ["boot", "dtbo"]
        assert data["partition_count"] == 2
        assert set(_partitions(tmp_path, "dev")) == {"boot", "dtbo"}

    def test_images_may_be_repeated(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            for name in ("boot", "dtbo"):
                (tmp_path / "Images" / f"{name}.img").write_bytes(b"x" * 4096)
            with _stub_avb_tool({"boot": _ok(SAMPLE_HASH), "dtbo": _ok(HASH_DTBO)}):
                code, output = _run(
                    [
                        "config",
                        "create",
                        "--id",
                        "dev",
                        "--from-images",
                        "--images",
                        "boot",
                        "--images",
                        "dtbo",
                        "--json",
                    ]
                )
        finally:
            os.chdir(old_cwd)

        assert code == 0
        assert json.loads(output)["scanned_images"] == ["boot", "dtbo"]

    def test_key_override_is_used_for_every_partition(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            (tmp_path / "Images" / "boot.img").write_bytes(b"x" * 4096)
            with _stub_avb_tool({"boot": _ok(SAMPLE_HASH)}):
                code, output = _run(
                    [
                        "config",
                        "create",
                        "--id",
                        "dev",
                        "--from-images",
                        "--key",
                        "testkey_rsa4096",
                        "--json",
                    ]
                )
        finally:
            os.chdir(old_cwd)

        assert code == 0
        # boot.img is unsigned (algorithm NONE), so no key is required and
        # nothing is reported as missing -- the override still lands in the
        # profile below.
        assert json.loads(output)["missing_keys"] == []
        assert _partitions(tmp_path, "dev")["boot"]["key_id"] == "testkey_rsa4096"

    def test_from_images_and_allow_empty_are_mutually_exclusive(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            code, _output = _run(
                ["config", "create", "--id", "dev", "--from-images", "--allow-empty", "--json"]
            )
        finally:
            os.chdir(old_cwd)

        assert code == 2
        assert not (tmp_path / "profiles" / "dev").exists()

    def test_missing_image_name_fails_and_creates_nothing(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            (tmp_path / "Images" / "boot.img").write_bytes(b"x" * 4096)
            with _stub_avb_tool({"boot": _ok(SAMPLE_HASH)}):
                code, output = _run(
                    [
                        "config",
                        "create",
                        "--id",
                        "dev",
                        "--from-images",
                        "--images",
                        "boot,ghost",
                        "--json",
                    ]
                )
        finally:
            os.chdir(old_cwd)

        assert code == 1
        data = json.loads(output)
        assert data["created"] is False
        assert [i["error_code"] for i in data["issues"]] == ["image.not_found"]
        assert "ghost.img" in data["issues"][0]["message"]
        assert not (tmp_path / "profiles" / "dev").exists()

    def test_image_without_avb_structure_fails_by_default(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            (tmp_path / "Images" / "boot.img").write_bytes(b"x" * 4096)
            (tmp_path / "Images" / "raw.img").write_bytes(b"raw")
            with _stub_avb_tool(
                {
                    "boot": _ok(SAMPLE_HASH),
                    "raw": AvbToolResult(1, "", SAMPLE_NO_FOOTER, "info_image"),
                }
            ):
                code, output = _run(["config", "create", "--id", "dev", "--from-images", "--json"])
        finally:
            os.chdir(old_cwd)

        assert code == 1
        data = json.loads(output)
        assert data["created"] is False
        assert [i["error_code"] for i in data["issues"]] == ["image.no_vbmeta_structure"]
        assert data["skipped_images"] == ["raw"]
        assert not (tmp_path / "profiles" / "dev").exists()

    def test_skip_non_avb_creates_the_profile(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            (tmp_path / "Images" / "boot.img").write_bytes(b"x" * 4096)
            (tmp_path / "Images" / "raw.img").write_bytes(b"raw")
            with _stub_avb_tool(
                {
                    "boot": _ok(SAMPLE_HASH),
                    "raw": AvbToolResult(1, "", SAMPLE_NO_FOOTER, "info_image"),
                }
            ):
                code, output = _run(
                    ["config", "create", "--id", "dev", "--from-images", "--skip-non-avb", "--json"]
                )
        finally:
            os.chdir(old_cwd)

        assert code == 0
        data = json.loads(output)
        assert data["created"] is True
        assert data["skipped_images"] == ["raw"]
        assert data["issues"] == []
        assert set(_partitions(tmp_path, "dev")) == {"boot"}

    def test_existing_profile_is_a_conflict_without_overwrite(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            (tmp_path / "Images" / "boot.img").write_bytes(b"x" * 4096)
            with _stub_avb_tool({"boot": _ok(SAMPLE_HASH)}):
                first, _output = _run(["config", "create", "--id", "dev", "--from-images"])
                code, output = _run(["config", "create", "--id", "dev", "--from-images", "--json"])
        finally:
            os.chdir(old_cwd)

        assert first == 0
        assert code == 1
        data = json.loads(output)
        assert data["created"] is False
        assert [i["error_code"] for i in data["issues"]] == ["config.profile_exists"]

    def test_overwrite_replaces_the_partitions(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            (tmp_path / "Images" / "boot.img").write_bytes(b"x" * 4096)
            with _stub_avb_tool({"boot": _ok(SAMPLE_HASH)}):
                first, _output = _run(["config", "create", "--id", "dev", "--from-images"])

            (tmp_path / "Images" / "boot.img").unlink()
            (tmp_path / "Images" / "dtbo.img").write_bytes(b"x" * 4096)
            with _stub_avb_tool({"dtbo": _ok(HASH_DTBO)}):
                code, output = _run(
                    ["config", "create", "--id", "dev", "--from-images", "--overwrite", "--json"]
                )
        finally:
            os.chdir(old_cwd)

        assert first == 0
        assert code == 0
        assert json.loads(output)["created"] is True
        assert set(_partitions(tmp_path, "dev")) == {"dtbo"}

    def test_activate_is_opt_in(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            (tmp_path / "Images" / "boot.img").write_bytes(b"x" * 4096)
            with _stub_avb_tool({"boot": _ok(SAMPLE_HASH)}):
                code, _output = _run(["config", "create", "--id", "dev", "--from-images"])
                not_activated = (tmp_path / ".active-profile").exists()

            (tmp_path / "Images" / "dtbo.img").write_bytes(b"x" * 4096)
            with _stub_avb_tool({"dtbo": _ok(HASH_DTBO)}):
                activated_code, _output = _run(
                    [
                        "config",
                        "create",
                        "--id",
                        "dev",
                        "--from-images",
                        "--overwrite",
                        "--activate",
                    ]
                )
        finally:
            os.chdir(old_cwd)

        assert code == 0
        assert not_activated is False
        assert activated_code == 0
        assert (tmp_path / ".active-profile").read_text(encoding="utf-8") == "dev"

    def test_help_lists_the_new_flags(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, _output = _run(["config", "create", "--help"])
        captured = capsys.readouterr()
        assert code == 0
        for flag in (
            "--from-images",
            "--images",
            "--key",
            "--no-chain-resolve",
            "--include-fallback",
            "--skip-non-avb",
            "--overwrite",
            "--allow-empty",
        ):
            assert flag in captured.out, flag
