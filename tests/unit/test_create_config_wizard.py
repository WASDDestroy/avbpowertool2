"""Tests for the TUI create-config wizard's view layer.

The auto-mode partition builders live in
``avbpowertool.application.services.config_auto_create`` and are covered
by ``tests/unit/test_config_auto_create.py``; what remains here is the
interactive glue: the default scan directory and the two regressions on
``_collect_partitions_auto`` (empty answer / explicit directory).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import avbpowertool.presentation.tui.views.create_config as create_config_view
from avbpowertool.application.ports import AvbToolResult
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.presentation.i18n import init_i18n
from avbpowertool.presentation.tui.views.create_config import _auto_dir_default
from tests.conftest import FakeAvbTool


class TestAutoDirDefault:
    def test_default_is_workspace_images(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.chdir(tmp_path)
        ws = WorkspacePaths.discover(tmp_path)

        default_dir, display = _auto_dir_default(ws)

        assert default_dir == tmp_path / "Images"
        # Compact legacy-style display when the workspace is the cwd.
        assert display == "./Images"

    def test_display_absolute_when_workspace_is_not_cwd(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        ws = WorkspacePaths.discover(tmp_path)

        default_dir, display = _auto_dir_default(ws)

        assert default_dir == ws.images == tmp_path / "Images"
        assert Path(display).is_absolute()


class TestCollectPartitionsAutoEmptyInput:
    """Regression: empty answer at the directory prompt must not abort."""

    def test_empty_input_uses_workspace_images(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_hash_output: str,
    ) -> None:
        # Activate real translations so the prompt text is formatted.
        init_i18n("en")
        # Like a real TUI session: launched from the workspace root.
        monkeypatch.chdir(tmp_path)

        ws = WorkspacePaths.discover(tmp_path)
        ws.ensure_dirs()
        (ws.images / "boot.img").write_bytes(b"x" * 8192)

        captured: dict[str, str] = {}

        def fake_input(_stdscr: object, prompt: str) -> str:
            captured["prompt"] = prompt
            return ""  # user pressed Enter without typing anything

        monkeypatch.setattr(create_config_view, "input_prompt", fake_input)
        monkeypatch.setattr(create_config_view, "message_screen", lambda *a, **k: None)
        fake_avb = FakeAvbTool(
            {"inspect_image": AvbToolResult(0, sample_hash_output, "", "info_image")}
        )

        result = create_config_view._collect_partitions_auto(
            object(), ws, fake_avb, "profile", ["default"]
        )

        # The prompt advertises the ./Images workspace default...
        assert "./Images" in captured["prompt"]
        # ...and the wizard proceeded with it instead of returning None.
        assert result is not None
        assert [p.partition_name for p in result] == ["boot"]
        assert result[0].image == "boot.img"
        assert result[0].partition_size == 8192  # size read from Images/boot.img
        # The scanned image was resolved inside the workspace Images dir.
        assert fake_avb.calls[0][1][0] == ws.images / "boot.img"

    def test_explicit_input_overrides_default(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        ws = WorkspacePaths.discover(tmp_path)
        ws.ensure_dirs()
        custom = ws.images / "custom"
        custom.mkdir()
        (custom / "dtbo.img").write_bytes(b"x" * 4096)
        (ws.images / "boot.img").write_bytes(b"workspace image")

        monkeypatch.setattr(create_config_view, "input_prompt", lambda _s, _p: str(custom))
        monkeypatch.setattr(create_config_view, "message_screen", lambda *a, **k: None)
        # Any inspection fails (image resolves to workspace Images/, which
        # has no dtbo.img) — but the flow must still scan the typed dir and
        # return a list, never abort with None.
        fake_avb = FakeAvbTool()

        result = create_config_view._collect_partitions_auto(
            object(), ws, fake_avb, "profile", ["default"]
        )

        assert result == []
