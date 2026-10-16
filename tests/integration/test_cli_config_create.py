"""CLI contract tests for ``config create``."""

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

#: A valid hash descriptor for the scanned ``boot`` image.
SAMPLE_HASH = (AVBTOOL_OUTPUT_DIR / "hash_descriptor.txt").read_text(encoding="utf-8")


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


def _read_profile(root: Path, profile_id: str) -> dict[str, object]:
    path = root / "profiles" / profile_id / "profile.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _read_profile_name(root: Path, profile_id: str) -> str:
    profile = _read_profile(root, profile_id)
    meta = profile["profile"]
    assert isinstance(meta, dict)
    name = meta["name"]
    assert isinstance(name, str)
    return name


def _partitions(root: Path, profile_id: str) -> dict[str, object]:
    partitions = _read_profile(root, profile_id)["partitions"]
    assert isinstance(partitions, dict)
    return partitions


class TestConfigCreateCli:
    def test_create_empty_profile_json(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            code, output = _run(["config", "create", "--id", "dev", "--allow-empty", "--json"])
        finally:
            os.chdir(old_cwd)

        assert code == 0
        data = json.loads(output)
        assert data["profile_id"] == "dev"
        assert data["created"] is True
        assert data["issues"] == []

        profile = _read_profile(tmp_path, "dev")
        assert profile["partitions"] == {}
        assert (tmp_path / "profiles" / "dev" / "keys" / "manifest.json").is_file()

    def test_create_without_allow_empty_fails_and_creates_nothing(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            code, output = _run(["config", "create", "--id", "dev", "--json"])
        finally:
            os.chdir(old_cwd)

        assert code == 1
        data = json.loads(output)
        assert data["created"] is False
        assert [i["error_code"] for i in data["issues"]] == ["config.no_partitions"]
        assert not (tmp_path / "profiles" / "dev").exists()

    def test_name_defaults_to_id(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            code, _output = _run(["config", "create", "--id", "dev", "--allow-empty"])
        finally:
            os.chdir(old_cwd)

        assert code == 0
        assert _read_profile_name(tmp_path, "dev") == "dev"

    def test_explicit_name_is_kept(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            code, _output = _run(
                ["config", "create", "--id", "dev", "--name", "My Device", "--allow-empty"]
            )
        finally:
            os.chdir(old_cwd)

        assert code == 0
        assert _read_profile_name(tmp_path, "dev") == "My Device"

    def test_create_is_not_activating_by_default(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            code, _output = _run(["config", "create", "--id", "dev", "--allow-empty"])
        finally:
            os.chdir(old_cwd)

        assert code == 0
        assert not (tmp_path / ".active-profile").exists()

    def test_no_activate_keeps_existing_active_profile(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            (tmp_path / ".active-profile").write_text("other", encoding="utf-8")
            code, _output = _run(
                ["config", "create", "--id", "dev", "--allow-empty", "--no-activate"]
            )
        finally:
            os.chdir(old_cwd)

        assert code == 0
        assert (tmp_path / ".active-profile").read_text(encoding="utf-8") == "other"

    def test_activate_writes_active_profile(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            code, _output = _run(["config", "create", "--id", "dev", "--allow-empty", "--activate"])
        finally:
            os.chdir(old_cwd)

        assert code == 0
        assert (tmp_path / ".active-profile").read_text(encoding="utf-8") == "dev"

    def test_duplicate_create_fails(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            first, _output = _run(["config", "create", "--id", "dev", "--allow-empty"])
            code, output = _run(["config", "create", "--id", "dev", "--allow-empty", "--json"])
        finally:
            os.chdir(old_cwd)

        assert first == 0
        assert code == 1
        data = json.loads(output)
        assert data["created"] is False
        assert [i["error_code"] for i in data["issues"]] == ["config.profile_exists"]

    def test_invalid_id_fails(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            code, output = _run(["config", "create", "--id", "bad id!", "--allow-empty", "--json"])
        finally:
            os.chdir(old_cwd)

        assert code == 1
        data = json.loads(output)
        assert [i["error_code"] for i in data["issues"]] == ["config.invalid_profile_id"]
        assert not (tmp_path / "profiles" / "bad_id_").exists()

    def test_overwrite_with_allow_empty_is_rejected(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            code, output = _run(
                ["config", "create", "--id", "dev", "--allow-empty", "--overwrite", "--json"]
            )
        finally:
            os.chdir(old_cwd)

        captured = capsys.readouterr()
        assert code == 2
        assert "--overwrite requires --from-images" in captured.err
        assert output == ""
        assert not (tmp_path / "profiles" / "dev").exists()

    def test_overwrite_without_a_source_is_rejected(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            code, output = _run(["config", "create", "--id", "dev", "--overwrite", "--json"])
        finally:
            os.chdir(old_cwd)

        captured = capsys.readouterr()
        assert code == 2
        assert "--overwrite requires --from-images" in captured.err
        assert output == ""
        assert not (tmp_path / "profiles" / "dev").exists()

    def test_overwrite_with_from_images_still_works(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path)
            (tmp_path / "Images" / "boot.img").write_bytes(b"x" * 4096)
            with _stub_avb_tool({"boot": AvbToolResult(0, SAMPLE_HASH, "", "info_image")}):
                first, _output = _run(["config", "create", "--id", "dev", "--from-images"])
                code, output = _run(
                    ["config", "create", "--id", "dev", "--from-images", "--overwrite", "--json"]
                )
        finally:
            os.chdir(old_cwd)

        assert first == 0
        assert code == 0
        data = json.loads(output)
        assert data["created"] is True
        assert data["issues"] == []
        assert set(_partitions(tmp_path, "dev")) == {"boot"}

    def test_help_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, _output = _run(["config", "create", "--help"])
        captured = capsys.readouterr()
        assert code == 0
        # argparse writes --help straight to the process stdout.
        assert "--allow-empty" in captured.out
        assert "--id" in captured.out
