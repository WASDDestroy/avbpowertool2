"""CLI contract tests — parser shape, --help, --json, exit codes."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

from avbpowertool.presentation.cli.parser import build_parser, main


class TestParserShape:
    def test_help_exits_zero(self) -> None:
        out = StringIO()
        try:
            code = main(["--help"], out=out)
        except SystemExit as exc:
            code = exc.code
        assert code == 0

    def test_image_inspect_help(self) -> None:
        out = StringIO()
        try:
            code = main(["image", "inspect", "--help"], out=out)
        except SystemExit as exc:
            code = exc.code
        assert code == 0

    def test_image_sign_help(self) -> None:
        out = StringIO()
        try:
            code = main(["image", "sign", "--help"], out=out)
        except SystemExit as exc:
            code = exc.code
        assert code == 0

    def test_config_show_help(self) -> None:
        out = StringIO()
        try:
            code = main(["config", "show", "--help"], out=out)
        except SystemExit as exc:
            code = exc.code
        assert code == 0

    def test_config_list_help(self) -> None:
        out = StringIO()
        try:
            code = main(["config", "list", "--help"], out=out)
        except SystemExit as exc:
            code = exc.code
        assert code == 0

    def test_config_import_legacy_help(self) -> None:
        out = StringIO()
        try:
            code = main(["config", "import-legacy", "--help"], out=out)
        except SystemExit as exc:
            code = exc.code
        assert code == 0


class TestAboutCommand:
    def test_about_outputs_version(self) -> None:
        out = StringIO()
        code = main(["about"], out=out)
        assert code == 0
        output = out.getvalue()
        assert "AVBPowerTool" in output


class TestDeprecatedAliases:
    def test_read_alias_warns(self) -> None:
        """The 'read' alias should produce a deprecation warning."""
        out = StringIO()
        err = StringIO()
        # read needs images but we just want to check the warning
        # It will fail with missing images, but should still warn
        import sys

        old_stderr = sys.stderr
        sys.stderr = err
        try:
            main(["read"], out=out)
        except SystemExit:
            pass
        finally:
            sys.stderr = old_stderr
        # The deprecated warning should appear
        assert "deprecated" in err.getvalue().lower() or "warning" in err.getvalue().lower()


class TestJsonOutput:
    def test_config_list_json_empty(self, tmp_path: Path) -> None:
        """config list --json should produce valid JSON even with no profiles."""
        import os

        # Change to tmp workspace
        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        (tmp_path / "profiles").mkdir(exist_ok=True)
        (tmp_path / "Logs").mkdir(exist_ok=True)
        (tmp_path / ".avbpowertool-staging").mkdir(exist_ok=True)
        (tmp_path / "avbtool.py").write_text("# placeholder")

        out = StringIO()
        try:
            code = main(["config", "list", "--json"], out=out)
            output = out.getvalue()
            data = json.loads(output)
            assert "profiles" in data
            assert isinstance(data["profiles"], list)
        finally:
            os.chdir(old_cwd)

    def test_about_no_json_flag(self) -> None:
        """about command works without --json."""
        out = StringIO()
        code = main(["about"], out=out)
        assert code == 0
        assert "AVBPowerTool" in out.getvalue()


class TestLegacyImportCli:
    LEGACY_FIXTURES = Path(__file__).parent.parent / "fixtures" / "legacy"

    def _make_v1_archive(self, tmp_path: Path, name: str = "legacy.zip") -> Path:
        import zipfile

        archive = tmp_path / name
        with zipfile.ZipFile(archive, "w") as zf:
            zf.write(
                self.LEGACY_FIXTURES / "imageInfo.json",
                "Configs/ZUXOS_411/imageInfo.json",
            )
            for f in sorted((self.LEGACY_FIXTURES / "keys").iterdir()):
                zf.write(f, f"Keys/ZUXOS_411/{f.name}")
            zf.writestr("this_is_a_config_file_of_avbpowertool", "x")
        return archive

    def _enter_workspace(self, tmp_path: Path) -> None:
        import os

        (tmp_path / "profiles").mkdir(exist_ok=True)
        (tmp_path / "Logs").mkdir(exist_ok=True)
        (tmp_path / ".avbpowertool-staging").mkdir(exist_ok=True)
        (tmp_path / "avbtool.py").write_text("# placeholder")
        os.chdir(tmp_path)

    def test_import_legacy_json(self, tmp_path: Path) -> None:
        import os

        archive = self._make_v1_archive(tmp_path)
        old_cwd = os.getcwd()
        try:
            self._enter_workspace(tmp_path)
            out = StringIO()
            code = main(["config", "import-legacy", str(archive), "--json"], out=out)
            data = json.loads(out.getvalue())
            assert code == 0
            assert data["profile_id"] == "ZUXOS_411"
            assert data["partition_count"] == 15
            assert data["key_count"] == 2
            assert data["issues"] == []
        finally:
            os.chdir(old_cwd)

    def test_import_legacy_text_custom_name(self, tmp_path: Path) -> None:
        import os

        archive = self._make_v1_archive(tmp_path)
        old_cwd = os.getcwd()
        try:
            self._enter_workspace(tmp_path)
            out = StringIO()
            code = main(
                ["config", "import-legacy", str(archive), "--name", "my_device"],
                out=out,
            )
            assert code == 0
            assert "my_device" in out.getvalue()
        finally:
            os.chdir(old_cwd)


class TestExitCodes:
    def test_no_command_would_launch_tui(self) -> None:
        """No subcommand should attempt to launch TUI (bootstrap + App)."""
        # We can't test the actual TUI in headless mode, but we can verify
        # the code path exists by checking that the parser doesn't error
        # and the action_id is None.
        parser = build_parser()
        args = parser.parse_args([])
        assert getattr(args, "action_id", None) is None
        assert getattr(args, "command", None) is None


class TestParserBuilds:
    def test_build_parser_returns_parser(self) -> None:
        parser = build_parser()
        assert parser is not None
        assert parser.prog == "avbpowertool"

    def test_parser_has_all_subcommands(self) -> None:
        parser = build_parser()
        # Verify key subcommands exist by parsing
        args = parser.parse_args(["image", "inspect", "boot"])
        assert args.command == "image"
        assert args.image_command == "inspect"
        assert args.images == ["boot"]
