"""CLI contract tests for the ``plugin`` command group.

Every test runs against a throw-away workspace under ``tmp_path``: the
real ``plugins/`` directory of this checkout is never read or written.
"""

from __future__ import annotations

import json
import os
import zipfile
from io import StringIO
from pathlib import Path

import pytest

from avbpowertool.domain.models import OperationIssue
from avbpowertool.infrastructure.persistence.plugin_repository import (
    PLUGIN_MANIFEST_NAME,
)
from avbpowertool.presentation.cli.parser import main
from avbpowertool.presentation.cli.renderer import exit_code_from_issues

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _manifest_xml(
    plugin_id: str = "demo",
    entry: str = "run.py",
    names: tuple[tuple[str, str], ...] = (("en", "Demo plugin"), ("zh", "演示插件")),
    version: int | None = None,
    version_name: str | None = None,
) -> str:
    body = "".join(f'<name lang="{lang}">{text}</name>' for lang, text in names)
    version_xml = "" if version is None else f"<version>{version}</version>"
    version_name_xml = (
        "" if version_name is None else f"<version_name>{version_name}</version_name>"
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<avbpowertool_plugin schema_version="1">'
        f"<id>{plugin_id}</id>{version_xml}{version_name_xml}"
        f"<entry>{entry}</entry><names>{body}</names>"
        "</avbpowertool_plugin>"
    )


def _enter_workspace(tmp_path: Path, language: str | None = None) -> None:
    """Make *tmp_path* the current directory and the CLI workspace."""
    (tmp_path / "avbtool.py").write_text("# placeholder", encoding="utf-8")
    if language is not None:
        (tmp_path / "settings.json").write_text(
            json.dumps({"language": language}), encoding="utf-8"
        )
    os.chdir(tmp_path)


def _install_plugin(
    root: Path,
    plugin_id: str = "demo",
    entry: str = "run.py",
    script: str = "print('hello')\n",
    names: tuple[tuple[str, str], ...] = (("en", "Demo plugin"), ("zh", "演示插件")),
    version: int | None = None,
    version_name: str | None = None,
) -> Path:
    plugin_dir = root / "plugins" / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / PLUGIN_MANIFEST_NAME).write_text(
        _manifest_xml(plugin_id, entry, names, version, version_name), encoding="utf-8"
    )
    (plugin_dir / entry).write_text(script, encoding="utf-8")
    return plugin_dir


def _make_source_dir(
    root: Path,
    plugin_id: str = "demo",
    entry: str = "run.py",
    script: str = "print('installed')\n",
    version: int | None = None,
    version_name: str | None = None,
) -> Path:
    """A plugin directory *outside* ``plugins/``, ready to be installed."""
    source = root / "src" / plugin_id
    source.mkdir(parents=True, exist_ok=True)
    (source / PLUGIN_MANIFEST_NAME).write_text(
        _manifest_xml(plugin_id, entry, version=version, version_name=version_name),
        encoding="utf-8",
    )
    (source / entry).write_text(script, encoding="utf-8")
    return source


def _run(argv: list[str]) -> tuple[int, str, str]:
    """Run the CLI, returning ``(exit_code, stdout, stderr)``."""
    out = StringIO()
    err = StringIO()
    import sys

    old_stderr = sys.stderr
    sys.stderr = err
    try:
        code = main(argv, out=out)
    except SystemExit as exc:  # --help and argparse usage errors
        code = exc.code if isinstance(exc.code, int) else 2
    finally:
        sys.stderr = old_stderr
    return code, out.getvalue(), err.getvalue()


@pytest.fixture
def workspace(tmp_path: Path):
    """Enter an empty throw-away workspace; restore the cwd afterwards."""
    old_cwd = os.getcwd()
    try:
        _enter_workspace(tmp_path)
        yield tmp_path
    finally:
        os.chdir(old_cwd)


# ---------------------------------------------------------------------------
# plugin list
# ---------------------------------------------------------------------------


class TestPluginListCli:
    def test_empty_workspace_is_an_empty_json_list(self, workspace: Path) -> None:
        code, stdout, _ = _run(["plugin", "list", "--json"])

        assert code == 0
        data = json.loads(stdout)
        assert data["plugins"] == []
        assert data["issues"] == []

    def test_empty_workspace_text_hint(self, workspace: Path) -> None:
        code, stdout, _ = _run(["plugin", "list"])

        assert code == 0
        assert "No plugins installed." in stdout

    def test_lists_a_plugin_with_the_default_english_name(self, workspace: Path) -> None:
        _install_plugin(workspace, "demo")

        code, stdout, _ = _run(["plugin", "list", "--json"])

        assert code == 0
        data = json.loads(stdout)
        assert data["issues"] == []
        assert len(data["plugins"]) == 1
        entry = data["plugins"][0]
        assert entry["plugin_id"] == "demo"
        # No settings.json -> the persisted language is the "en" default.
        assert entry["name"] == "Demo plugin"
        assert entry["entry"] == "run.py"
        # A manifest without <version> / <version_name> reports 0 / "".
        assert entry["version"] == 0
        assert entry["version_name"] == ""
        assert Path(entry["path"]).resolve() == (workspace / "plugins" / "demo").resolve()

    def test_json_reports_the_manifest_version(self, workspace: Path) -> None:
        _install_plugin(workspace, "demo", version=2, version_name="2.1.0")

        code, stdout, _ = _run(["plugin", "list", "--json"])

        assert code == 0
        entry = json.loads(stdout)["plugins"][0]
        assert entry["version"] == 2
        assert entry["version_name"] == "2.1.0"

    def test_resolves_the_name_for_the_configured_language(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _enter_workspace(tmp_path, language="zh")
            _install_plugin(tmp_path, "demo")

            code, stdout, _ = _run(["plugin", "list", "--json"])

            assert code == 0
            data = json.loads(stdout)
            assert data["plugins"][0]["name"] == "演示插件"
        finally:
            os.chdir(old_cwd)

    def test_text_mode_lists_id_name_version_entry_and_path(self, workspace: Path) -> None:
        _install_plugin(workspace, "demo")

        code, stdout, _ = _run(["plugin", "list"])

        assert code == 0
        assert "demo: Demo plugin v0 [run.py] (" in stdout
        assert "plugins" in stdout and "demo)" in stdout

    def test_text_mode_includes_the_version_name_when_declared(self, workspace: Path) -> None:
        _install_plugin(workspace, "demo", version=2, version_name="2.1.0")

        code, stdout, _ = _run(["plugin", "list"])

        assert code == 0
        assert "demo: Demo plugin v2 (2.1.0) [run.py] (" in stdout


# ---------------------------------------------------------------------------
# plugin install
# ---------------------------------------------------------------------------


class TestPluginInstallCli:
    def test_installs_a_directory(self, workspace: Path) -> None:
        source = _make_source_dir(workspace)

        code, stdout, _ = _run(["plugin", "install", str(source), "--json"])

        assert code == 0
        data = json.loads(stdout)
        assert data["plugin_id"] == "demo"
        assert data["installed"] is True
        assert data["file_count"] == 2
        assert data["issues"] == []
        assert (workspace / "plugins" / "demo" / PLUGIN_MANIFEST_NAME).is_file()

    def test_installs_a_zip_archive(self, workspace: Path) -> None:
        archive = workspace / "demo.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr(f"demo/{PLUGIN_MANIFEST_NAME}", _manifest_xml())
            zf.writestr("demo/run.py", "print('zipped')\n")

        code, stdout, _ = _run(["plugin", "install", str(archive), "--json"])

        assert code == 0
        data = json.loads(stdout)
        assert data["plugin_id"] == "demo"
        assert data["installed"] is True
        assert data["file_count"] == 2
        assert (workspace / "plugins" / "demo" / "run.py").is_file()

    def test_install_json_reports_the_version(self, workspace: Path) -> None:
        source = _make_source_dir(workspace, version=3, version_name="3.0.0")

        code, stdout, _ = _run(["plugin", "install", str(source), "--json"])

        assert code == 0
        data = json.loads(stdout)
        assert data["version"] == 3
        assert data["version_name"] == "3.0.0"

    def test_install_text_mode_reports_the_version(self, workspace: Path) -> None:
        source = _make_source_dir(workspace, version=3, version_name="3.0.0")

        code, stdout, _ = _run(["plugin", "install", str(source)])

        assert code == 0
        assert "Installed plugin: demo" in stdout
        assert "v3 (3.0.0)" in stdout

    def test_same_version_reinstall_succeeds_without_force(self, workspace: Path) -> None:
        source = _make_source_dir(workspace, script="print('reinstalled')\n")
        _install_plugin(workspace, "demo")

        code, stdout, _ = _run(["plugin", "install", str(source), "--json"])

        assert code == 0
        data = json.loads(stdout)
        assert data["installed"] is True
        assert data["issues"] == []
        assert (workspace / "plugins" / "demo" / "run.py").read_text(
            encoding="utf-8"
        ) == "print('reinstalled')\n"

    def test_upgrade_succeeds_without_force(self, workspace: Path) -> None:
        _install_plugin(workspace, "demo", version=1, version_name="1.0.0")
        source = _make_source_dir(
            workspace, version=2, version_name="2.0.0", script="print('v2')\n"
        )

        code, stdout, _ = _run(["plugin", "install", str(source), "--json"])

        assert code == 0
        data = json.loads(stdout)
        assert data["installed"] is True
        assert data["version"] == 2
        assert data["version_name"] == "2.0.0"
        assert (workspace / "plugins" / "demo" / "run.py").read_text(encoding="utf-8") == (
            "print('v2')\n"
        )

    def test_downgrade_is_refused(self, workspace: Path) -> None:
        plugin_dir = _install_plugin(workspace, "demo", version=2, version_name="2.0.0")
        source = _make_source_dir(
            workspace, version=1, version_name="1.0.0", script="print('v1')\n"
        )

        code, stdout, _ = _run(["plugin", "install", str(source), "--json"])

        assert code == 1
        data = json.loads(stdout)
        assert data["installed"] is False
        assert [i["error_code"] for i in data["issues"]] == ["plugin.downgrade"]
        # Nothing was overwritten.
        assert (plugin_dir / "run.py").read_text(encoding="utf-8") == "print('hello')\n"

    def test_downgrade_text_message_names_both_versions(self, workspace: Path) -> None:
        _install_plugin(workspace, "demo", version=2, version_name="2.0.0")
        source = _make_source_dir(workspace, version=1, version_name="1.0.0")

        code, stdout, _ = _run(["plugin", "install", str(source)])

        assert code == 1
        assert "[plugin.downgrade]" in stdout
        assert "version 2 (2.0.0)" in stdout
        assert "version 1 (1.0.0)" in stdout
        assert "--force" in stdout

    def test_downgrade_with_force_succeeds(self, workspace: Path) -> None:
        _install_plugin(workspace, "demo", version=2, version_name="2.0.0")
        source = _make_source_dir(
            workspace, version=1, version_name="1.0.0", script="print('v1')\n"
        )

        code, stdout, _ = _run(["plugin", "install", str(source), "--force", "--json"])

        assert code == 0
        data = json.loads(stdout)
        assert data["installed"] is True
        assert data["version"] == 1
        assert (workspace / "plugins" / "demo" / "run.py").read_text(encoding="utf-8") == (
            "print('v1')\n"
        )

    def test_unreadable_installed_manifest_still_reports_exists(self, workspace: Path) -> None:
        plugin_dir = _install_plugin(workspace, "demo", version=2)
        (plugin_dir / PLUGIN_MANIFEST_NAME).write_text("not xml at all", encoding="utf-8")
        source = _make_source_dir(workspace, version=1)

        code, stdout, _ = _run(["plugin", "install", str(source), "--json"])

        assert code == 1
        data = json.loads(stdout)
        assert data["installed"] is False
        assert [i["error_code"] for i in data["issues"]] == ["plugin.exists"]

    def test_unreadable_installed_manifest_with_force_succeeds(self, workspace: Path) -> None:
        plugin_dir = _install_plugin(workspace, "demo", version=2)
        (plugin_dir / PLUGIN_MANIFEST_NAME).write_text("not xml at all", encoding="utf-8")
        source = _make_source_dir(workspace, version=1)

        code, stdout, _ = _run(["plugin", "install", str(source), "--force", "--json"])

        assert code == 0
        assert json.loads(stdout)["installed"] is True

    def test_reinstall_with_force_succeeds(self, workspace: Path) -> None:
        source = _make_source_dir(workspace)
        _install_plugin(workspace, "demo")

        code, stdout, _ = _run(["plugin", "install", str(source), "--force", "--json"])

        assert code == 0
        data = json.loads(stdout)
        assert data["installed"] is True
        assert data["issues"] == []

    def test_unsafe_zip_writes_nothing_anywhere(self, workspace: Path) -> None:
        archive = workspace / "demo.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr(PLUGIN_MANIFEST_NAME, _manifest_xml())
            zf.writestr("../evil.txt", "pwned")

        code, stdout, _ = _run(["plugin", "install", str(archive), "--json"])

        assert code == 1
        data = json.loads(stdout)
        assert data["installed"] is False
        assert [i["error_code"] for i in data["issues"]] == ["plugin.install_failed"]
        # Nothing escaped the workspace and no half-installed plugin exists.
        assert not (workspace / "plugins" / "demo").exists()
        assert not (workspace / "plugins" / "evil.txt").exists()
        assert not (workspace / "evil.txt").exists()
        assert not (workspace.parent / "evil.txt").exists()

    def test_missing_source_is_reported(self, workspace: Path) -> None:
        code, stdout, _ = _run(["plugin", "install", str(workspace / "nope"), "--json"])

        assert code == 1
        data = json.loads(stdout)
        assert [i["error_code"] for i in data["issues"]] == ["plugin.install_failed"]


# ---------------------------------------------------------------------------
# plugin uninstall
# ---------------------------------------------------------------------------


class TestPluginUninstallCli:
    def test_without_yes_nothing_is_removed(self, workspace: Path) -> None:
        plugin_dir = _install_plugin(workspace, "demo")

        code, _stdout, stderr = _run(["plugin", "uninstall", "demo"])

        assert code == 1
        assert "Use --yes to confirm." in stderr
        assert plugin_dir.is_dir()

    def test_with_yes_removes_the_directory(self, workspace: Path) -> None:
        plugin_dir = _install_plugin(workspace, "demo")

        code, stdout, _ = _run(["plugin", "uninstall", "demo", "--yes", "--json"])

        assert code == 0
        data = json.loads(stdout)
        assert data["plugin_id"] == "demo"
        assert data["removed"] is True
        assert data["removed_files"] == 2
        assert data["removed_bytes"] > 0
        assert data["issues"] == []
        assert not plugin_dir.exists()

    def test_missing_plugin_is_reported(self, workspace: Path) -> None:
        code, stdout, _ = _run(["plugin", "uninstall", "ghost", "--yes", "--json"])

        assert code == 1
        data = json.loads(stdout)
        assert data["removed"] is False
        assert [i["error_code"] for i in data["issues"]] == ["plugin.not_found"]


# ---------------------------------------------------------------------------
# plugin run
# ---------------------------------------------------------------------------

# Writes the value of AVBPOWERTOOL_ROOT into marker.txt and exits 3: the
# exit code proves the plugin's own status is passed through, and the marker
# proves the environment contract.
_ROOT_PROBE = (
    "import os\n"
    "import pathlib\n"
    "import sys\n"
    "\n"
    "root = os.environ['AVBPOWERTOOL_ROOT']\n"
    "assert root, 'AVBPOWERTOOL_ROOT must not be empty'\n"
    "pathlib.Path(__file__).with_name('marker.txt').write_text(root, encoding='utf-8')\n"
    "sys.exit(3)\n"
)

# Writes the arguments the plugin received into args.txt as JSON.
_ARGS_PROBE = (
    "import json\n"
    "import pathlib\n"
    "import sys\n"
    "\n"
    "pathlib.Path(__file__).with_name('args.txt').write_text(\n"
    "    json.dumps(sys.argv[1:]), encoding='utf-8'\n"
    ")\n"
)


class TestPluginRunCli:
    def test_exit_code_and_root_are_passed_through(self, workspace: Path) -> None:
        plugin_dir = _install_plugin(workspace, "probe", script=_ROOT_PROBE)

        code, stdout, _ = _run(["plugin", "run", "probe", "--json"])

        assert code == 3
        data = json.loads(stdout)
        assert data["plugin_id"] == "probe"
        assert data["exit_code"] == 3
        assert data["issues"] == []
        marker = (plugin_dir / "marker.txt").read_text(encoding="utf-8")
        assert Path(marker).resolve() == Path(os.getcwd()).resolve()

    def test_text_mode_prints_nothing_on_a_clean_run(self, workspace: Path) -> None:
        _install_plugin(workspace, "probe", script=_ROOT_PROBE)

        code, stdout, _ = _run(["plugin", "run", "probe"])

        assert code == 3
        # The plugin owns stdio; the tool must not add anything to it.
        assert stdout == ""

    def test_arguments_after_the_separator_reach_the_plugin(self, workspace: Path) -> None:
        plugin_dir = _install_plugin(workspace, "probe", script=_ARGS_PROBE)

        code, _stdout, _ = _run(["plugin", "run", "probe", "--", "--flag", "x"])

        assert code == 0
        assert json.loads((plugin_dir / "args.txt").read_text(encoding="utf-8")) == [
            "--flag",
            "x",
        ]

    def test_json_after_the_separator_goes_to_the_plugin(self, workspace: Path) -> None:
        plugin_dir = _install_plugin(workspace, "probe", script=_ARGS_PROBE)

        code, stdout, _ = _run(["plugin", "run", "probe", "--", "--json"])

        assert code == 0
        assert json.loads((plugin_dir / "args.txt").read_text(encoding="utf-8")) == ["--json"]
        # The tool did not switch to JSON output.
        assert stdout == ""

    def test_json_before_the_separator_is_consumed_by_the_tool(self, workspace: Path) -> None:
        plugin_dir = _install_plugin(workspace, "probe", script=_ARGS_PROBE)

        code, stdout, _ = _run(["plugin", "run", "probe", "--json"])

        assert code == 0
        data = json.loads(stdout)
        assert data["plugin_id"] == "probe"
        assert data["exit_code"] == 0
        # The plugin received no argument at all.
        assert json.loads((plugin_dir / "args.txt").read_text(encoding="utf-8")) == []

    def test_both_json_meanings_at_once(self, workspace: Path) -> None:
        plugin_dir = _install_plugin(workspace, "probe", script=_ARGS_PROBE)

        code, stdout, _ = _run(["plugin", "run", "probe", "--json", "--", "--json"])

        assert code == 0
        data = json.loads(stdout)
        assert data["issues"] == []
        assert json.loads((plugin_dir / "args.txt").read_text(encoding="utf-8")) == ["--json"]

    def test_missing_plugin_is_reported(self, workspace: Path) -> None:
        code, stdout, _ = _run(["plugin", "run", "ghost", "--json"])

        assert code == 1
        data = json.loads(stdout)
        assert data["plugin_id"] == "ghost"
        assert data["exit_code"] == -1
        assert [i["error_code"] for i in data["issues"]] == ["plugin.not_found"]

    def test_plugin_exit_code_1_is_not_confused_with_a_tool_error(self, workspace: Path) -> None:
        _install_plugin(workspace, "probe", script="import sys\nsys.exit(1)\n")

        code, stdout, _ = _run(["plugin", "run", "probe", "--json"])

        assert code == 1
        data = json.loads(stdout)
        # The plugin ran: its own status travels, without any issue.
        assert data["exit_code"] == 1
        assert data["issues"] == []


# ---------------------------------------------------------------------------
# Exit-code mapping
# ---------------------------------------------------------------------------


class TestPluginExitCodeMapping:
    @pytest.mark.parametrize(
        "error_code",
        ["plugin.downgrade", "plugin.exists", "plugin.manifest_invalid", "plugin.not_found"],
    )
    def test_plugin_error_codes_map_to_exit_code_one(self, error_code: str) -> None:
        assert exit_code_from_issues((OperationIssue(error_code, "message"),)) == 1

    def test_no_issues_map_to_exit_code_zero(self) -> None:
        assert exit_code_from_issues(()) == 0


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------


class TestPluginHelp:
    @pytest.mark.parametrize(
        "argv",
        [
            ["plugin", "--help"],
            ["plugin", "list", "--help"],
            ["plugin", "install", "--help"],
            ["plugin", "uninstall", "--help"],
            ["plugin", "run", "--help"],
        ],
    )
    def test_help_exits_zero(self, argv: list[str]) -> None:
        out = StringIO()
        try:
            code = main(argv, out=out)
        except SystemExit as exc:
            code = exc.code
        assert code == 0

    def test_run_help_documents_the_separator(self, capsys: pytest.CaptureFixture[str]) -> None:
        try:
            main(["plugin", "run", "--help"], out=StringIO())
        except SystemExit:
            pass
        assert "--" in capsys.readouterr().out
