"""Integration tests for the plugin management use cases."""

from __future__ import annotations

import sys
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from avbpowertool.application.commands import (
    PluginInstallRequest,
    PluginListRequest,
    PluginPackRequest,
    PluginRunRequest,
    PluginUninstallRequest,
)
from avbpowertool.application.ports import PluginRunOutcome
from avbpowertool.application.services.manage_plugins import (
    ENV_CLI,
    ENV_LANG,
    ENV_PLUGIN_DIR,
    ENV_PLUGIN_ID,
    ENV_ROOT,
    PluginInstallUseCase,
    PluginListUseCase,
    PluginPackUseCase,
    PluginRunUseCase,
    PluginUninstallUseCase,
)
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.persistence.plugin_repository import (
    PLUGIN_MANIFEST_NAME,
)
from avbpowertool.infrastructure.plugins.runner import SubprocessPluginRunner

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _manifest_xml(
    plugin_id: str = "demo",
    entry: str = "run.cmd",
    names: tuple[tuple[str, str], ...] = (("en", "Demo plugin"), ("zh", "演示插件")),
    version: int | None = None,
    version_name: str | None = None,
) -> bytes:
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
    ).encode("utf-8")


def _make_workspace(tmp_path: Path) -> WorkspacePaths:
    ws = WorkspacePaths(
        root=tmp_path,
        images=tmp_path / "Images",
        profiles=tmp_path / "profiles",
        plugins=tmp_path / "plugins",
        logs=tmp_path / "Logs",
        staging=tmp_path / ".avbpowertool-staging",
        avbtool_script=tmp_path / "avbtool.py",
    )
    ws.ensure_dirs()
    return ws


def _install_plugin(
    ws: WorkspacePaths,
    plugin_id: str = "demo",
    entry: str = "run.cmd",
    names: tuple[tuple[str, str], ...] = (("en", "Demo plugin"), ("zh", "演示插件")),
    version: int | None = None,
    version_name: str | None = None,
    script: str = "@echo off\n",
) -> Path:
    plugin_dir = ws.plugins / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / PLUGIN_MANIFEST_NAME).write_bytes(
        _manifest_xml(plugin_id, entry, names, version, version_name)
    )
    (plugin_dir / entry).write_text(script, encoding="utf-8")
    return plugin_dir


def _make_source_dir(
    tmp_path: Path,
    plugin_id: str = "demo",
    entry: str = "run.cmd",
    version: int | None = None,
    version_name: str | None = None,
    script: str = "@echo off\n",
) -> Path:
    source = tmp_path / "src" / plugin_id
    source.mkdir(parents=True)
    (source / PLUGIN_MANIFEST_NAME).write_bytes(
        _manifest_xml(plugin_id, entry, version=version, version_name=version_name)
    )
    (source / entry).write_text(script, encoding="utf-8")
    return source


def _codes(result: object) -> list[str]:
    return [issue.error_code for issue in result.issues]  # type: ignore[attr-defined]


class FakePluginRunner:
    """PluginRunnerPort double recording every call."""

    def __init__(self, outcome: PluginRunOutcome | None = None) -> None:
        self.outcome = outcome if outcome is not None else PluginRunOutcome(exit_code=0)
        self.calls: list[dict[str, object]] = []

    def run(
        self,
        entry: Path,
        *,
        cwd: Path,
        env: Mapping[str, str],
        args: Sequence[str],
    ) -> PluginRunOutcome:
        self.calls.append({"entry": entry, "cwd": cwd, "env": dict(env), "args": tuple(args)})
        return self.outcome


@pytest.fixture
def language() -> str:
    """The language every use case is explicitly wired with.

    Nothing here depends on the presentation layer's global language
    state: the language is an ordinary input of the use case.
    """
    return "en"


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


class TestPluginListUseCase:
    def test_lists_plugins_sorted_by_id(self, tmp_path: Path, language: str) -> None:
        ws = _make_workspace(tmp_path)
        _install_plugin(ws, "zulu")
        _install_plugin(ws, "alpha", entry="go.ps1")

        result = PluginListUseCase(ws, language=language).execute(PluginListRequest())

        assert result.issues == ()
        assert [item.plugin_id for item in result.plugins] == ["alpha", "zulu"]
        assert [item.entry for item in result.plugins] == ["go.ps1", "run.cmd"]
        assert result.plugins[0].name == "Demo plugin"
        assert result.plugins[0].path == str(ws.plugins / "alpha")

    def test_resolves_names_for_the_injected_language(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        _install_plugin(ws, "demo")

        result = PluginListUseCase(ws, language="zh").execute(PluginListRequest())

        assert result.plugins[0].name == "演示插件"

    def test_defaults_to_english_without_an_injected_language(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        _install_plugin(ws, "demo")

        result = PluginListUseCase(ws).execute(PluginListRequest())

        assert result.plugins[0].name == "Demo plugin"

    def test_directory_without_manifest_is_ignored(self, tmp_path: Path, language: str) -> None:
        ws = _make_workspace(tmp_path)
        (ws.plugins / "not_a_plugin").mkdir()

        result = PluginListUseCase(ws, language=language).execute(PluginListRequest())

        assert result.plugins == ()
        assert result.issues == ()

    def test_broken_manifest_is_reported_not_dropped(self, tmp_path: Path, language: str) -> None:
        ws = _make_workspace(tmp_path)
        _install_plugin(ws, "demo")
        broken = ws.plugins / "broken"
        broken.mkdir()
        (broken / PLUGIN_MANIFEST_NAME).write_text("<avbpowertool_plugin>", encoding="utf-8")

        result = PluginListUseCase(ws, language=language).execute(PluginListRequest())

        assert [item.plugin_id for item in result.plugins] == ["demo"]
        assert _codes(result) == ["plugin.manifest_invalid"]
        assert "broken" in result.issues[0].message

    def test_empty_workspace_lists_nothing(self, tmp_path: Path, language: str) -> None:
        ws = _make_workspace(tmp_path)

        result = PluginListUseCase(ws, language=language).execute(PluginListRequest())

        assert result.plugins == ()
        assert result.issues == ()

    def test_reports_the_manifest_version_and_version_name(
        self, tmp_path: Path, language: str
    ) -> None:
        ws = _make_workspace(tmp_path)
        _install_plugin(ws, "alpha", version=3, version_name="3.1.0")
        _install_plugin(ws, "beta")

        result = PluginListUseCase(ws, language=language).execute(PluginListRequest())

        by_id = {item.plugin_id: item for item in result.plugins}
        assert by_id["alpha"].version == 3
        assert by_id["alpha"].version_name == "3.1.0"
        # A manifest without <version> / <version_name> is 0 / "".
        assert by_id["beta"].version == 0
        assert by_id["beta"].version_name == ""


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------


class TestPluginInstallUseCase:
    def test_installs_a_directory(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        source = _make_source_dir(tmp_path)

        result = PluginInstallUseCase(ws).execute(PluginInstallRequest(str(source)))

        assert result.issues == ()
        assert result.installed is True
        assert result.plugin_id == "demo"
        assert result.file_count == 2
        assert (ws.plugins / "demo" / PLUGIN_MANIFEST_NAME).is_file()

    def test_passes_the_version_fields_through(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        source = _make_source_dir(tmp_path, version=4, version_name="4.2.0")

        result = PluginInstallUseCase(ws).execute(PluginInstallRequest(str(source)))

        assert result.issues == ()
        assert result.installed is True
        assert result.version == 4
        assert result.version_name == "4.2.0"

    def test_legacy_manifest_installs_as_version_zero(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        source = _make_source_dir(tmp_path)

        result = PluginInstallUseCase(ws).execute(PluginInstallRequest(str(source)))

        assert result.version == 0
        assert result.version_name == ""

    def test_installs_a_zip_archive(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        archive = tmp_path / "demo.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr(f"demo/{PLUGIN_MANIFEST_NAME}", _manifest_xml())
            zf.writestr("demo/run.cmd", "@echo off\n")

        result = PluginInstallUseCase(ws).execute(PluginInstallRequest(str(archive)))

        assert result.issues == ()
        assert result.plugin_id == "demo"
        assert result.file_count == 2
        assert (ws.plugins / "demo" / "run.cmd").is_file()

    def test_same_version_reinstall_succeeds_without_force(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        _install_plugin(ws, "demo", version=1, version_name="1.0.0")
        source = _make_source_dir(tmp_path, version=1, version_name="1.0.0", script="NEW\n")

        result = PluginInstallUseCase(ws).execute(PluginInstallRequest(str(source)))

        assert result.issues == ()
        assert result.installed is True
        assert (ws.plugins / "demo" / "run.cmd").read_text(encoding="utf-8") == "NEW\n"

    def test_upgrade_succeeds_without_force(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        _install_plugin(ws, "demo", version=1, version_name="1.0.0")
        source = _make_source_dir(tmp_path, version=2, version_name="2.0.0", script="NEW\n")

        result = PluginInstallUseCase(ws).execute(PluginInstallRequest(str(source)))

        assert result.issues == ()
        assert result.installed is True
        assert result.version == 2
        assert result.version_name == "2.0.0"
        assert (ws.plugins / "demo" / "run.cmd").read_text(encoding="utf-8") == "NEW\n"

    def test_downgrade_is_reported(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        _install_plugin(ws, "demo", version=2, version_name="2.0.0")
        source = _make_source_dir(tmp_path, version=1, version_name="1.0.0", script="NEW\n")

        result = PluginInstallUseCase(ws).execute(PluginInstallRequest(str(source)))

        assert result.installed is False
        # Failure keeps the version fields at their defaults.
        assert result.version == 0
        assert result.version_name == ""
        assert _codes(result) == ["plugin.downgrade"]
        assert "2" in result.issues[0].message
        assert "1" in result.issues[0].message
        # The installed copy is untouched.
        assert (ws.plugins / "demo" / "run.cmd").read_text(encoding="utf-8") == "@echo off\n"

    def test_downgrade_with_force_installs(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        _install_plugin(ws, "demo", version=2, version_name="2.0.0")
        source = _make_source_dir(tmp_path, version=1, version_name="1.0.0", script="NEW\n")

        result = PluginInstallUseCase(ws).execute(PluginInstallRequest(str(source), force=True))

        assert result.issues == ()
        assert result.installed is True
        assert result.version == 1
        assert (ws.plugins / "demo" / "run.cmd").read_text(encoding="utf-8") == "NEW\n"

    def test_unreadable_installed_manifest_falls_back_to_exists(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        plugin_dir = _install_plugin(ws, "demo", version=2)
        (plugin_dir / PLUGIN_MANIFEST_NAME).unlink()
        source = _make_source_dir(tmp_path, version=1)

        result = PluginInstallUseCase(ws).execute(PluginInstallRequest(str(source)))

        assert result.installed is False
        assert _codes(result) == ["plugin.exists"]

    def test_unreadable_installed_manifest_with_force_installs(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        plugin_dir = _install_plugin(ws, "demo", version=2)
        (plugin_dir / PLUGIN_MANIFEST_NAME).unlink()
        source = _make_source_dir(tmp_path, version=1, script="NEW\n")

        result = PluginInstallUseCase(ws).execute(PluginInstallRequest(str(source), force=True))

        assert result.issues == ()
        assert result.installed is True
        assert (plugin_dir / "run.cmd").read_text(encoding="utf-8") == "NEW\n"

    def test_force_reinstalls(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        _install_plugin(ws, "demo")
        source = _make_source_dir(tmp_path)
        (source / "run.cmd").write_text("NEW\n", encoding="utf-8")

        result = PluginInstallUseCase(ws).execute(PluginInstallRequest(str(source), force=True))

        assert result.installed is True
        assert (ws.plugins / "demo" / "run.cmd").read_text(encoding="utf-8") == "NEW\n"

    def test_missing_manifest_is_reported(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        source = tmp_path / "src" / "demo"
        source.mkdir(parents=True)
        (source / "run.cmd").write_text("x", encoding="utf-8")

        result = PluginInstallUseCase(ws).execute(PluginInstallRequest(str(source)))

        assert result.installed is False
        assert _codes(result) == ["plugin.manifest_missing"]

    def test_unsafe_archive_is_reported(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        archive = tmp_path / "demo.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr(PLUGIN_MANIFEST_NAME, _manifest_xml())
            zf.writestr("../evil.txt", "pwned")

        result = PluginInstallUseCase(ws).execute(PluginInstallRequest(str(archive)))

        assert result.installed is False
        assert _codes(result) == ["plugin.install_failed"]
        assert not (tmp_path / "evil.txt").exists()


# ---------------------------------------------------------------------------
# Pack
# ---------------------------------------------------------------------------


class TestPluginPackUseCase:
    def test_packs_a_directory_source(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        source = _make_source_dir(tmp_path, version=2, version_name="2.0.0")

        result = PluginPackUseCase(ws).execute(PluginPackRequest(source=str(source)))

        assert result.issues == ()
        assert result.plugin_id == "demo"
        assert result.version == 2
        assert result.version_name == "2.0.0"
        assert result.file_count == 2
        assert result.output_path == str(ws.root / "demo.zip")
        assert (ws.root / "demo.zip").is_file()

    def test_packs_an_installed_plugin_by_id(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        _install_plugin(ws, "demo", version=3)

        result = PluginPackUseCase(ws).execute(PluginPackRequest(source="demo"))

        assert result.issues == ()
        assert result.plugin_id == "demo"
        assert result.output_path == str(ws.root / "demo.zip")
        with zipfile.ZipFile(ws.root / "demo.zip") as archive:
            assert sorted(archive.namelist()) == [
                f"demo/{PLUGIN_MANIFEST_NAME}",
                "demo/run.cmd",
            ]

    def test_unknown_source_is_not_found(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)

        result = PluginPackUseCase(ws).execute(PluginPackRequest(source="ghost"))

        assert result.plugin_id == ""
        assert _codes(result) == ["plugin.not_found"]
        # The message explains both ways of addressing a plugin.
        message = result.issues[0].message
        assert "directory" in message
        assert "plugins/" in message
        assert not (ws.root / "ghost.zip").exists()

    def test_default_output_is_the_workspace_root(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        source = _make_source_dir(tmp_path)

        result = PluginPackUseCase(ws).execute(PluginPackRequest(source=str(source)))

        assert result.output_path == str(ws.root / "demo.zip")
        assert (ws.root / "demo.zip").is_file()

    def test_output_override_is_used(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        source = _make_source_dir(tmp_path)
        target = tmp_path / "dist" / "custom.zip"

        result = PluginPackUseCase(ws).execute(
            PluginPackRequest(source=str(source), output_path=str(target))
        )

        assert result.issues == ()
        assert result.output_path == str(target)
        assert target.is_file()

    def test_key_material_is_flagged(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        source = _make_source_dir(tmp_path)
        (source / "keys").mkdir()
        (source / "keys" / "testkey_rsa4096.pem").write_text("KEY", encoding="utf-8")

        result = PluginPackUseCase(ws).execute(PluginPackRequest(source=str(source)))

        assert result.includes_key_material is True
        with zipfile.ZipFile(ws.root / "demo.zip") as archive:
            assert "demo/keys/testkey_rsa4096.pem" in archive.namelist()

    def test_plain_plugin_has_no_key_material(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        source = _make_source_dir(tmp_path)

        result = PluginPackUseCase(ws).execute(PluginPackRequest(source=str(source)))

        assert result.includes_key_material is False

    def test_missing_manifest_is_reported(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        source = tmp_path / "src" / "demo"
        source.mkdir(parents=True)
        (source / "run.cmd").write_text("x", encoding="utf-8")

        result = PluginPackUseCase(ws).execute(PluginPackRequest(source=str(source)))

        assert _codes(result) == ["plugin.manifest_missing"]
        assert not (ws.root / "demo.zip").exists()


# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------


class TestPluginUninstallUseCase:
    def test_removes_the_plugin_and_counts_its_files(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        plugin_dir = _install_plugin(ws, "demo")

        result = PluginUninstallUseCase(ws).execute(PluginUninstallRequest("demo"))

        assert result.issues == ()
        assert result.removed is True
        assert result.removed_files == 2
        assert result.removed_bytes > 0
        assert not plugin_dir.exists()

    def test_missing_plugin_is_reported(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)

        result = PluginUninstallUseCase(ws).execute(PluginUninstallRequest("nope"))

        assert result.removed is False
        assert _codes(result) == ["plugin.not_found"]

    @pytest.mark.parametrize("bad_id", ["", ".", "..", "a/b", "a\\b", "../other"])
    def test_dangerous_ids_are_refused(self, tmp_path: Path, bad_id: str) -> None:
        ws = _make_workspace(tmp_path)
        other = _install_plugin(ws, "other")
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_text("keep", encoding="utf-8")

        result = PluginUninstallUseCase(ws).execute(PluginUninstallRequest(bad_id))

        assert result.removed is False
        assert _codes(result) == ["plugin.id_invalid"]
        # Nothing outside plugins/ was touched.
        assert other.is_dir()
        assert outside.is_dir()
        assert (outside / "keep.txt").is_file()
        assert ws.plugins.is_dir()


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


class TestPluginRunUseCase:
    def test_exports_the_plugin_environment_and_passes_args(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        plugin_dir = _install_plugin(ws, "demo", entry="run.cmd")
        runner = FakePluginRunner(PluginRunOutcome(exit_code=0, command_summary="run.cmd"))

        result = PluginRunUseCase(ws, runner, language="zh").execute(
            PluginRunRequest("demo", args=("--flag", "value"))
        )

        assert result.issues == ()
        assert result.exit_code == 0
        assert len(runner.calls) == 1
        call = runner.calls[0]
        assert call["entry"] == plugin_dir / "run.cmd"
        assert call["cwd"] == ws.root
        assert call["args"] == ("--flag", "value")

        env = call["env"]
        assert isinstance(env, dict)
        assert env[ENV_ROOT] == str(ws.root)
        assert env[ENV_PLUGIN_DIR] == str(plugin_dir)
        assert env[ENV_PLUGIN_ID] == "demo"
        assert env[ENV_LANG] == "zh"
        assert env[ENV_CLI] == "uv run avbpowertool"

    def test_inherits_the_parent_environment(self, tmp_path: Path, language: str) -> None:
        ws = _make_workspace(tmp_path)
        _install_plugin(ws, "demo")
        runner = FakePluginRunner()

        PluginRunUseCase(ws, runner, language=language).execute(PluginRunRequest("demo"))

        env = runner.calls[0]["env"]
        assert isinstance(env, dict)
        assert "PATH" in env

    def test_exports_the_injected_language(self, tmp_path: Path, language: str) -> None:
        ws = _make_workspace(tmp_path)
        _install_plugin(ws, "demo")
        runner = FakePluginRunner()

        PluginRunUseCase(ws, runner, language="zh").execute(PluginRunRequest("demo"))

        env = runner.calls[0]["env"]
        assert isinstance(env, dict)
        assert env[ENV_LANG] == "zh"
        # The same injected language resolves the listed names.
        listed = PluginListUseCase(ws, language="zh").execute(PluginListRequest())
        assert listed.plugins[0].name == "演示插件"

    def test_non_zero_exit_is_passed_through_without_issues(
        self, tmp_path: Path, language: str
    ) -> None:
        ws = _make_workspace(tmp_path)
        _install_plugin(ws, "demo")
        runner = FakePluginRunner(PluginRunOutcome(exit_code=7, command_summary="run.cmd"))

        result = PluginRunUseCase(ws, runner, language=language).execute(PluginRunRequest("demo"))

        assert result.exit_code == 7
        assert result.issues == ()
        assert result.plugin_id == "demo"

    def test_runner_error_becomes_run_failed(self, tmp_path: Path, language: str) -> None:
        ws = _make_workspace(tmp_path)
        _install_plugin(ws, "demo")
        runner = FakePluginRunner(
            PluginRunOutcome(exit_code=-1, error="Plugin interpreter not found: pwsh")
        )

        result = PluginRunUseCase(ws, runner, language=language).execute(PluginRunRequest("demo"))

        assert result.exit_code == -1
        assert _codes(result) == ["plugin.run_failed"]
        assert "pwsh" in result.issues[0].message

    def test_missing_plugin_is_reported(self, tmp_path: Path, language: str) -> None:
        ws = _make_workspace(tmp_path)
        runner = FakePluginRunner()

        result = PluginRunUseCase(ws, runner, language=language).execute(PluginRunRequest("nope"))

        assert result.exit_code == -1
        assert _codes(result) == ["plugin.not_found"]
        assert runner.calls == []

    def test_missing_entry_file_is_reported(self, tmp_path: Path, language: str) -> None:
        ws = _make_workspace(tmp_path)
        plugin_dir = _install_plugin(ws, "demo")
        (plugin_dir / "run.cmd").unlink()
        runner = FakePluginRunner()

        result = PluginRunUseCase(ws, runner, language=language).execute(PluginRunRequest("demo"))

        assert result.exit_code == -1
        assert _codes(result) == ["plugin.entry_not_found"]
        assert runner.calls == []

    @pytest.mark.parametrize("bad_id", ["", ".", "..", "a/b", "a\\b"])
    def test_dangerous_ids_are_refused(self, tmp_path: Path, language: str, bad_id: str) -> None:
        ws = _make_workspace(tmp_path)
        _install_plugin(ws, "demo")
        runner = FakePluginRunner()

        result = PluginRunUseCase(ws, runner, language=language).execute(PluginRunRequest(bad_id))

        assert result.exit_code == -1
        assert _codes(result) == ["plugin.id_invalid"]
        assert runner.calls == []

    def test_invalid_manifest_is_reported(self, tmp_path: Path, language: str) -> None:
        ws = _make_workspace(tmp_path)
        plugin_dir = _install_plugin(ws, "demo")
        (plugin_dir / PLUGIN_MANIFEST_NAME).write_bytes(
            _manifest_xml(entry="bin/run.cmd")  # outside the plugin directory
        )
        runner = FakePluginRunner()

        result = PluginRunUseCase(ws, runner, language=language).execute(PluginRunRequest("demo"))

        assert result.exit_code == -1
        assert _codes(result) == ["plugin.entry_invalid"]
        assert runner.calls == []


# ---------------------------------------------------------------------------
# Real subprocess (the .py path only: the most controllable one)
# ---------------------------------------------------------------------------


class TestRealPluginSubprocess:
    def test_python_plugin_receives_the_root_and_its_exit_code(
        self, tmp_path: Path, language: str
    ) -> None:
        ws = _make_workspace(tmp_path)
        plugin_dir = _install_plugin(ws, "probe", entry="probe.py")
        marker = plugin_dir / "marker.txt"
        # The probe proves the environment contract end to end: it fails
        # with a KeyError (exit 1, no marker) when AVBPOWERTOOL_ROOT is not
        # exported, and it always exits 3 so the pass-through is checked too.
        (plugin_dir / "probe.py").write_text(
            "import os\n"
            "import pathlib\n"
            "import sys\n"
            "\n"
            "root = os.environ['AVBPOWERTOOL_ROOT']\n"
            "assert root, 'AVBPOWERTOOL_ROOT must not be empty'\n"
            "pathlib.Path(__file__).with_name('marker.txt').write_text(root, encoding='utf-8')\n"
            "sys.exit(3)\n",
            encoding="utf-8",
        )

        result = PluginRunUseCase(ws, SubprocessPluginRunner(), language=language).execute(
            PluginRunRequest("probe")
        )

        assert result.issues == ()
        assert result.exit_code == 3
        assert marker.read_text(encoding="utf-8") == str(ws.root)
        assert sys.executable  # the runner dispatched through this interpreter
