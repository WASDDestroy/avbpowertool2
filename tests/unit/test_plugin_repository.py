"""Tests for PluginRepository (manifest scan, install, uninstall)."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from avbpowertool.domain.errors import ConfigError
from avbpowertool.domain.plugin import PluginManifest
from avbpowertool.infrastructure.persistence.plugin_repository import (
    PLUGIN_MANIFEST_NAME,
    PluginRepository,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _manifest_xml(
    plugin_id: str = "demo",
    entry: str = "run.cmd",
    names: tuple[tuple[str, str], ...] = (("en", "Demo"),),
    version: int | None = None,
    version_name: str | None = None,
) -> bytes:
    """Build a manifest; ``None`` omits the element (a legacy manifest)."""
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


def _make_plugin(
    plugins_dir: Path,
    plugin_id: str = "demo",
    entry: str = "run.cmd",
    version: int | None = None,
    version_name: str | None = None,
    script: str = "@echo off\n",
) -> Path:
    """Create an installed-looking plugin directory."""
    plugin_dir = plugins_dir / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / PLUGIN_MANIFEST_NAME).write_bytes(
        _manifest_xml(plugin_id, entry, version=version, version_name=version_name)
    )
    (plugin_dir / entry).write_text(script, encoding="utf-8")
    return plugin_dir


def _make_source(
    tmp_path: Path,
    plugin_id: str = "demo",
    entry: str = "run.cmd",
    version: int | None = None,
    version_name: str | None = None,
    script: str = "@echo off\n",
) -> Path:
    """Create an installable plugin directory outside plugins/."""
    source = tmp_path / "src" / plugin_id
    source.mkdir(parents=True)
    (source / PLUGIN_MANIFEST_NAME).write_bytes(
        _manifest_xml(plugin_id, entry, version=version, version_name=version_name)
    )
    (source / entry).write_text(script, encoding="utf-8")
    (source / "README.md").write_text("hi\n", encoding="utf-8")
    return source


def _make_zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path


def _snapshot(directory: Path) -> dict[str, str]:
    """Map every file under *directory* to a hash of its content."""
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def _code(exc_info: pytest.ExceptionInfo[ConfigError]) -> str:
    return exc_info.value.error_code


# ---------------------------------------------------------------------------
# list_manifests
# ---------------------------------------------------------------------------


class TestListManifests:
    def test_lists_every_plugin_directory(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        _make_plugin(plugins_dir, "alpha")
        _make_plugin(plugins_dir, "beta", entry="go.ps1")

        manifests, issues = PluginRepository(plugins_dir).list_manifests()

        assert issues == []
        assert [manifest.plugin_id for manifest in manifests] == ["alpha", "beta"]
        assert [manifest.entry for manifest in manifests] == ["run.cmd", "go.ps1"]

    def test_directory_without_manifest_is_not_a_plugin(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        _make_plugin(plugins_dir, "alpha")
        (plugins_dir / "just_a_folder").mkdir()
        (plugins_dir / "just_a_folder" / "notes.txt").write_text("x", encoding="utf-8")
        (plugins_dir / "stray.txt").write_text("x", encoding="utf-8")

        manifests, issues = PluginRepository(plugins_dir).list_manifests()

        assert [manifest.plugin_id for manifest in manifests] == ["alpha"]
        assert issues == []

    def test_broken_manifest_is_reported_with_its_path(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        _make_plugin(plugins_dir, "alpha")
        broken = plugins_dir / "broken"
        broken.mkdir()
        (broken / PLUGIN_MANIFEST_NAME).write_text("<avbpowertool_plugin>", encoding="utf-8")

        manifests, issues = PluginRepository(plugins_dir).list_manifests()

        assert [manifest.plugin_id for manifest in manifests] == ["alpha"]
        assert [issue.error_code for issue in issues] == ["plugin.manifest_invalid"]
        assert str(broken / PLUGIN_MANIFEST_NAME) in issues[0].message

    def test_invalid_manifest_content_is_reported(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        bad = plugins_dir / "bad"
        bad.mkdir(parents=True)
        (bad / PLUGIN_MANIFEST_NAME).write_bytes(_manifest_xml(plugin_id="../escape"))

        manifests, issues = PluginRepository(plugins_dir).list_manifests()

        assert manifests == ()
        assert [issue.error_code for issue in issues] == ["plugin.id_invalid"]

    def test_missing_plugins_directory_is_not_an_error(self, tmp_path: Path) -> None:
        manifests, issues = PluginRepository(tmp_path / "plugins").list_manifests()

        assert manifests == ()
        assert issues == []


# ---------------------------------------------------------------------------
# load_manifest
# ---------------------------------------------------------------------------


class TestLoadManifest:
    def test_loads_an_installed_manifest(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        _make_plugin(plugins_dir, "demo")

        manifest = PluginRepository(plugins_dir).load_manifest("demo")

        assert manifest == PluginManifest(
            plugin_id="demo", entry="run.cmd", names=(("en", "Demo"),)
        )

    def test_missing_plugin_raises_not_found(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        with pytest.raises(ConfigError) as exc_info:
            PluginRepository(plugins_dir).load_manifest("nope")

        assert _code(exc_info) == "plugin.not_found"

    def test_missing_manifest_raises_not_found(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        (plugins_dir / "empty").mkdir(parents=True)

        with pytest.raises(ConfigError) as exc_info:
            PluginRepository(plugins_dir).load_manifest("empty")

        assert _code(exc_info) == "plugin.not_found"

    def test_broken_manifest_raises_manifest_invalid(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        broken = plugins_dir / "broken"
        broken.mkdir(parents=True)
        (broken / PLUGIN_MANIFEST_NAME).write_text("not xml at all", encoding="utf-8")

        with pytest.raises(ConfigError) as exc_info:
            PluginRepository(plugins_dir).load_manifest("broken")

        assert _code(exc_info) == "plugin.manifest_invalid"


# ---------------------------------------------------------------------------
# install from a directory
# ---------------------------------------------------------------------------


class TestInstallDirectory:
    def test_installs_and_counts_files(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        source = _make_source(tmp_path)
        (source / "sub").mkdir()
        (source / "sub" / "extra.txt").write_text("x", encoding="utf-8")

        manifest, file_count = PluginRepository(plugins_dir).install(source, force=False)

        assert manifest.plugin_id == "demo"
        assert file_count == 4  # manifest + entry + README + sub/extra.txt
        assert (plugins_dir / "demo" / PLUGIN_MANIFEST_NAME).is_file()
        assert (plugins_dir / "demo" / "run.cmd").is_file()
        assert (plugins_dir / "demo" / "sub" / "extra.txt").is_file()

    def test_missing_manifest_is_reported(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        source = tmp_path / "src" / "demo"
        source.mkdir(parents=True)
        (source / "run.cmd").write_text("x", encoding="utf-8")

        with pytest.raises(ConfigError) as exc_info:
            PluginRepository(plugins_dir).install(source, force=False)

        assert _code(exc_info) == "plugin.manifest_missing"
        assert not (plugins_dir / "demo").exists()

    def test_same_version_reinstall_overwrites_without_force(self, tmp_path: Path) -> None:
        """A reinstall of the same version is an upgrade of nothing: allowed."""
        plugins_dir = tmp_path / "plugins"
        _make_plugin(plugins_dir, "demo")
        source = _make_source(tmp_path)
        (source / "run.cmd").write_text("NEW\n", encoding="utf-8")

        _manifest, file_count = PluginRepository(plugins_dir).install(source, force=False)

        assert file_count == 3
        assert (plugins_dir / "demo" / "run.cmd").read_text(encoding="utf-8") == "NEW\n"

    def test_force_overwrites_the_installed_copy(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        _make_plugin(plugins_dir, "demo")
        source = _make_source(tmp_path)
        (source / "run.cmd").write_text("NEW\n", encoding="utf-8")

        _manifest, file_count = PluginRepository(plugins_dir).install(source, force=True)

        assert file_count == 3
        assert (plugins_dir / "demo" / "run.cmd").read_text(encoding="utf-8") == "NEW\n"
        assert (plugins_dir / "demo" / "README.md").is_file()

    def test_installing_a_plugin_in_place_is_a_no_op(self, tmp_path: Path) -> None:
        """The plugin directory is its own install location."""
        plugins_dir = tmp_path / "plugins"
        _make_plugin(plugins_dir, "demo")

        manifest, file_count = PluginRepository(plugins_dir).install(
            plugins_dir / "demo", force=True
        )

        assert manifest.plugin_id == "demo"
        assert file_count == 2
        assert (plugins_dir / "demo" / "run.cmd").is_file()

    def test_invalid_manifest_is_refused(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        source = tmp_path / "src" / "demo"
        source.mkdir(parents=True)
        (source / PLUGIN_MANIFEST_NAME).write_bytes(_manifest_xml(entry="bin/run.cmd"))

        with pytest.raises(ConfigError) as exc_info:
            PluginRepository(plugins_dir).install(source, force=False)

        assert _code(exc_info) == "plugin.entry_invalid"
        assert not (plugins_dir / "demo").exists()


# ---------------------------------------------------------------------------
# install from a zip
# ---------------------------------------------------------------------------


class TestInstallZip:
    def test_installs_a_root_layout_archive(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        archive = _make_zip(
            tmp_path / "demo.zip",
            {
                PLUGIN_MANIFEST_NAME: _manifest_xml(),
                "run.cmd": b"@echo off\n",
            },
        )

        manifest, file_count = PluginRepository(plugins_dir).install(archive, force=False)

        assert manifest.plugin_id == "demo"
        assert file_count == 2
        assert (plugins_dir / "demo" / "run.cmd").is_file()
        assert (plugins_dir / "demo" / PLUGIN_MANIFEST_NAME).is_file()

    def test_installs_a_single_directory_layout_and_strips_the_prefix(self, tmp_path: Path) -> None:
        """Compress-Archive <dir> wraps everything in one same-named directory."""
        plugins_dir = tmp_path / "plugins"
        archive = _make_zip(
            tmp_path / "demo.zip",
            {
                f"demo/{PLUGIN_MANIFEST_NAME}": _manifest_xml(),
                "demo/run.cmd": b"@echo off\n",
                "demo/sub/extra.txt": b"x",
                "demo/sub/": b"",
            },
        )

        _manifest, file_count = PluginRepository(plugins_dir).install(archive, force=False)

        assert file_count == 3
        assert (plugins_dir / "demo" / "run.cmd").is_file()
        assert (plugins_dir / "demo" / "sub" / "extra.txt").is_file()
        # Nothing was nested under another "demo/" level.
        assert not (plugins_dir / "demo" / "demo").exists()

    def test_two_candidate_manifests_are_refused(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        archive = _make_zip(
            tmp_path / "demo.zip",
            {
                PLUGIN_MANIFEST_NAME: _manifest_xml(),
                f"demo/{PLUGIN_MANIFEST_NAME}": _manifest_xml(),
            },
        )

        with pytest.raises(ConfigError) as exc_info:
            PluginRepository(plugins_dir).install(archive, force=False)

        assert _code(exc_info) == "plugin.manifest_invalid"
        assert not (plugins_dir / "demo").exists()

    def test_archive_without_manifest_is_refused(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        archive = _make_zip(tmp_path / "demo.zip", {"run.cmd": b"@echo off\n"})

        with pytest.raises(ConfigError) as exc_info:
            PluginRepository(plugins_dir).install(archive, force=False)

        assert _code(exc_info) == "plugin.manifest_missing"

    def test_manifest_two_levels_deep_is_not_found(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        archive = _make_zip(tmp_path / "demo.zip", {f"a/b/{PLUGIN_MANIFEST_NAME}": _manifest_xml()})

        with pytest.raises(ConfigError) as exc_info:
            PluginRepository(plugins_dir).install(archive, force=False)

        assert _code(exc_info) == "plugin.manifest_missing"

    def test_parent_traversal_member_is_refused(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        outside = tmp_path / "evil.txt"
        archive = _make_zip(
            tmp_path / "demo.zip",
            {
                PLUGIN_MANIFEST_NAME: _manifest_xml(),
                "../evil.txt": b"pwned",
            },
        )

        with pytest.raises(ConfigError) as exc_info:
            PluginRepository(plugins_dir).install(archive, force=False)

        assert _code(exc_info) == "plugin.install_failed"
        assert not outside.exists()
        # Nothing was extracted at all.
        assert not (plugins_dir / "demo").exists()

    def test_nested_parent_traversal_member_is_refused(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        archive = _make_zip(
            tmp_path / "demo.zip",
            {
                PLUGIN_MANIFEST_NAME: _manifest_xml(),
                "demo/../../evil.txt": b"pwned",
            },
        )

        with pytest.raises(ConfigError) as exc_info:
            PluginRepository(plugins_dir).install(archive, force=False)

        assert _code(exc_info) == "plugin.install_failed"
        assert not (tmp_path / "evil.txt").exists()

    def test_absolute_member_is_refused(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        archive = _make_zip(
            tmp_path / "demo.zip",
            {
                PLUGIN_MANIFEST_NAME: _manifest_xml(),
                "/absolute.txt": b"pwned",
            },
        )

        with pytest.raises(ConfigError) as exc_info:
            PluginRepository(plugins_dir).install(archive, force=False)

        assert _code(exc_info) == "plugin.install_failed"

    def test_drive_letter_member_is_refused(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        archive = _make_zip(
            tmp_path / "demo.zip",
            {
                PLUGIN_MANIFEST_NAME: _manifest_xml(),
                "C:/Windows/evil.txt": b"pwned",
            },
        )

        with pytest.raises(ConfigError) as exc_info:
            PluginRepository(plugins_dir).install(archive, force=False)

        assert _code(exc_info) == "plugin.install_failed"

    def test_same_version_zip_reinstall_overwrites_without_force(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        _make_plugin(plugins_dir, "demo")
        archive = _make_zip(
            tmp_path / "demo.zip",
            {PLUGIN_MANIFEST_NAME: _manifest_xml(), "run.cmd": b"NEW\n"},
        )

        PluginRepository(plugins_dir).install(archive, force=False)

        assert (plugins_dir / "demo" / "run.cmd").read_text(encoding="utf-8") == "NEW\n"

    def test_force_overwrites_through_a_zip(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        _make_plugin(plugins_dir, "demo")
        archive = _make_zip(
            tmp_path / "demo.zip",
            {PLUGIN_MANIFEST_NAME: _manifest_xml(), "run.cmd": b"NEW\n"},
        )

        PluginRepository(plugins_dir).install(archive, force=True)

        assert (plugins_dir / "demo" / "run.cmd").read_text(encoding="utf-8") == "NEW\n"


# ---------------------------------------------------------------------------
# install versioning: upgrade / same version / downgrade
# ---------------------------------------------------------------------------


class TestInstallVersioning:
    def test_fresh_install_reports_the_incoming_version(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        source = _make_source(tmp_path, version=3, version_name="3.0.0")

        manifest, file_count = PluginRepository(plugins_dir).install(source, force=False)

        assert manifest.version == 3
        assert manifest.version_name == "3.0.0"
        assert file_count == 3
        assert (plugins_dir / "demo" / PLUGIN_MANIFEST_NAME).is_file()

    def test_fresh_install_of_a_legacy_manifest_reports_version_zero(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        source = _make_source(tmp_path)

        manifest, _file_count = PluginRepository(plugins_dir).install(source, force=False)

        assert manifest.version == 0
        assert manifest.version_name == ""

    def test_downgrade_is_refused_without_force(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugin_dir = _make_plugin(plugins_dir, "demo", version=2, version_name="2.0.0")
        source = _make_source(tmp_path, version=1, version_name="1.0.0", script="NEW\n")
        before = _snapshot(plugin_dir)

        with pytest.raises(ConfigError) as exc_info:
            PluginRepository(plugins_dir).install(source, force=False)

        assert _code(exc_info) == "plugin.downgrade"
        message = str(exc_info.value)
        # Both versions (number and name) are named in the message.
        assert "version 2 (2.0.0)" in message
        assert "version 1 (1.0.0)" in message
        assert "--force" in message
        # The refused install wrote nothing at all.
        assert _snapshot(plugin_dir) == before

    def test_downgrade_with_force_overwrites(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugin_dir = _make_plugin(plugins_dir, "demo", version=2, version_name="2.0.0")
        source = _make_source(tmp_path, version=1, version_name="1.0.0", script="NEW\n")

        manifest, _file_count = PluginRepository(plugins_dir).install(source, force=True)

        assert manifest.version == 1
        assert manifest.version_name == "1.0.0"
        assert (plugin_dir / "run.cmd").read_text(encoding="utf-8") == "NEW\n"

    def test_upgrade_needs_no_force(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugin_dir = _make_plugin(plugins_dir, "demo", version=1, version_name="1.0.0")
        source = _make_source(tmp_path, version=2, version_name="2.0.0", script="NEW\n")

        manifest, _file_count = PluginRepository(plugins_dir).install(source, force=False)

        assert manifest.version == 2
        assert (plugin_dir / "run.cmd").read_text(encoding="utf-8") == "NEW\n"

    def test_same_version_needs_no_force(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugin_dir = _make_plugin(plugins_dir, "demo", version=1, version_name="1.0.0")
        source = _make_source(tmp_path, version=1, version_name="1.0.0", script="NEW\n")

        manifest, _file_count = PluginRepository(plugins_dir).install(source, force=False)

        assert manifest.version == 1
        assert (plugin_dir / "run.cmd").read_text(encoding="utf-8") == "NEW\n"

    def test_zip_downgrade_is_refused_without_force(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugin_dir = _make_plugin(plugins_dir, "demo", version=2, version_name="2.0.0")
        archive = _make_zip(
            tmp_path / "demo.zip",
            {
                PLUGIN_MANIFEST_NAME: _manifest_xml(version=1, version_name="1.0.0"),
                "run.cmd": b"NEW\n",
            },
        )
        before = _snapshot(plugin_dir)

        with pytest.raises(ConfigError) as exc_info:
            PluginRepository(plugins_dir).install(archive, force=False)

        assert _code(exc_info) == "plugin.downgrade"
        assert _snapshot(plugin_dir) == before

    def test_zip_downgrade_with_force_overwrites(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugin_dir = _make_plugin(plugins_dir, "demo", version=2, version_name="2.0.0")
        archive = _make_zip(
            tmp_path / "demo.zip",
            {PLUGIN_MANIFEST_NAME: _manifest_xml(version=1), "run.cmd": b"NEW\n"},
        )

        manifest, _file_count = PluginRepository(plugins_dir).install(archive, force=True)

        assert manifest.version == 1
        assert (plugin_dir / "run.cmd").read_text(encoding="utf-8") == "NEW\n"

    def test_zip_upgrade_needs_no_force(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugin_dir = _make_plugin(plugins_dir, "demo", version=1)
        archive = _make_zip(
            tmp_path / "demo.zip",
            {PLUGIN_MANIFEST_NAME: _manifest_xml(version=2), "run.cmd": b"NEW\n"},
        )

        PluginRepository(plugins_dir).install(archive, force=False)

        assert (plugin_dir / "run.cmd").read_text(encoding="utf-8") == "NEW\n"

    def test_legacy_installed_manifest_counts_as_version_zero_upgrade(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugin_dir = _make_plugin(plugins_dir, "demo")  # no <version> element
        source = _make_source(tmp_path, version=1, version_name="1.0.0", script="NEW\n")

        manifest, _file_count = PluginRepository(plugins_dir).install(source, force=False)

        assert manifest.version == 1
        assert (plugin_dir / "run.cmd").read_text(encoding="utf-8") == "NEW\n"

    def test_legacy_installed_manifest_counts_as_version_zero_same(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugin_dir = _make_plugin(plugins_dir, "demo")  # no <version> element
        source = _make_source(tmp_path, version=0, script="NEW\n")

        _manifest, _file_count = PluginRepository(plugins_dir).install(source, force=False)

        assert (plugin_dir / "run.cmd").read_text(encoding="utf-8") == "NEW\n"

    def test_missing_installed_manifest_falls_back_to_exists(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugin_dir = _make_plugin(plugins_dir, "demo")
        (plugin_dir / PLUGIN_MANIFEST_NAME).unlink()
        source = _make_source(tmp_path, version=1)

        with pytest.raises(ConfigError) as exc_info:
            PluginRepository(plugins_dir).install(source, force=False)

        assert _code(exc_info) == "plugin.exists"
        assert "--force" in str(exc_info.value)

    def test_missing_installed_manifest_with_force_installs(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugin_dir = _make_plugin(plugins_dir, "demo")
        (plugin_dir / PLUGIN_MANIFEST_NAME).unlink()
        source = _make_source(tmp_path, version=1)

        manifest, _file_count = PluginRepository(plugins_dir).install(source, force=True)

        assert manifest.version == 1
        assert (plugin_dir / PLUGIN_MANIFEST_NAME).is_file()

    def test_corrupt_installed_manifest_falls_back_to_exists(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugin_dir = _make_plugin(plugins_dir, "demo", version=5)
        (plugin_dir / PLUGIN_MANIFEST_NAME).write_text("not xml at all", encoding="utf-8")
        source = _make_source(tmp_path, version=1)

        with pytest.raises(ConfigError) as exc_info:
            PluginRepository(plugins_dir).install(source, force=False)

        assert _code(exc_info) == "plugin.exists"

    def test_corrupt_installed_manifest_with_force_installs(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugin_dir = _make_plugin(plugins_dir, "demo", version=5)
        (plugin_dir / PLUGIN_MANIFEST_NAME).write_text("not xml at all", encoding="utf-8")
        source = _make_source(tmp_path, version=1, script="NEW\n")

        _manifest, _file_count = PluginRepository(plugins_dir).install(source, force=True)

        assert (plugin_dir / "run.cmd").read_text(encoding="utf-8") == "NEW\n"

    def test_installed_manifest_of_another_id_falls_back_to_exists(self, tmp_path: Path) -> None:
        """The version of a manifest that is not this plugin's is unknown."""
        plugins_dir = tmp_path / "plugins"
        plugin_dir = _make_plugin(plugins_dir, "demo")
        (plugin_dir / PLUGIN_MANIFEST_NAME).write_bytes(_manifest_xml(plugin_id="other", version=9))
        source = _make_source(tmp_path, version=1)

        with pytest.raises(ConfigError) as exc_info:
            PluginRepository(plugins_dir).install(source, force=False)

        assert _code(exc_info) == "plugin.exists"

    def test_in_place_install_of_the_same_version_needs_no_force(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        _make_plugin(plugins_dir, "demo", version=1)

        manifest, file_count = PluginRepository(plugins_dir).install(
            plugins_dir / "demo", force=False
        )

        assert manifest.version == 1
        assert file_count == 2


class TestInstallRejectsOtherSources:
    def test_plain_file_is_not_a_plugin_package(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        source = tmp_path / "notes.txt"
        source.write_text("hello", encoding="utf-8")

        with pytest.raises(ConfigError) as exc_info:
            PluginRepository(plugins_dir).install(source, force=False)

        assert _code(exc_info) == "plugin.install_failed"

    def test_missing_source_is_not_a_plugin_package(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError) as exc_info:
            PluginRepository(tmp_path / "plugins").install(tmp_path / "nope", force=False)

        assert _code(exc_info) == "plugin.install_failed"


# ---------------------------------------------------------------------------
# uninstall
# ---------------------------------------------------------------------------


class TestUninstall:
    def test_removes_the_plugin_and_reports_its_size(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugin_dir = _make_plugin(plugins_dir, "demo")
        (plugin_dir / "sub").mkdir()
        (plugin_dir / "sub" / "data.bin").write_bytes(b"x" * 10)
        expected_bytes = sum(
            path.stat().st_size for path in plugin_dir.rglob("*") if path.is_file()
        )

        file_count, total_bytes = PluginRepository(plugins_dir).uninstall("demo")

        assert file_count == 3
        assert total_bytes == expected_bytes > 10
        assert not plugin_dir.exists()

    def test_missing_plugin_raises_not_found(self, tmp_path: Path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        with pytest.raises(ConfigError) as exc_info:
            PluginRepository(plugins_dir).uninstall("nope")

        assert _code(exc_info) == "plugin.not_found"

    @pytest.mark.parametrize("bad_id", ["", ".", "..", "a/b", "a\\b", "../outside"])
    def test_dangerous_ids_are_refused(self, tmp_path: Path, bad_id: str) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_text("keep", encoding="utf-8")

        with pytest.raises(ConfigError) as exc_info:
            PluginRepository(plugins_dir).uninstall(bad_id)

        assert _code(exc_info) == "plugin.id_invalid"
        assert outside.is_dir()
        assert (outside / "keep.txt").is_file()
        assert plugins_dir.is_dir()
        assert tmp_path.is_dir()
