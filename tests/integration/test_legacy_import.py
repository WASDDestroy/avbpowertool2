"""Integration tests for legacy (v1) config import."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from avbpowertool.application.commands import (
    ConfigExportRequest,
    ConfigImportRequest,
    LegacyImportRequest,
)
from avbpowertool.application.services.manage_configs import (
    ConfigExportUseCase,
    ConfigImportUseCase,
    LegacyConfigImportUseCase,
)
from avbpowertool.domain.models import AvbProfile, DescriptorType, SigningAlgorithm
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.persistence.profile_codec import encode_profile
from avbpowertool.infrastructure.persistence.profile_repository import ProfileRepository

LEGACY_FIXTURES = Path(__file__).parent.parent / "fixtures" / "legacy"


def _make_v1_archive(tmp_path: Path, archive_name: str = "demo_config.zip") -> Path:
    """Build a v1-style ZIP from the static fixtures."""
    archive = tmp_path / archive_name
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(LEGACY_FIXTURES / "imageInfo.json", "Configs/ZUXOS_411/imageInfo.json")
        zf.write(LEGACY_FIXTURES / "imageList.txt", "Configs/ZUXOS_411/imageList.txt")
        for f in sorted((LEGACY_FIXTURES / "keys").iterdir()):
            zf.write(f, f"Keys/ZUXOS_411/{f.name}")
        zf.writestr("this_is_a_config_file_of_avbpowertool", "x")
    return archive


class TestLegacyConfigImportUseCase:
    def test_import_converts_and_persists(self, tmp_path: Path) -> None:
        ws = WorkspacePaths.discover(tmp_path)
        ws.ensure_dirs()
        archive = _make_v1_archive(tmp_path)

        uc = LegacyConfigImportUseCase(ws)
        result = uc.execute(LegacyImportRequest(archive_path=str(archive)))

        assert result.profile_id == "ZUXOS_411"
        assert len(result.issues) == 0
        assert result.partition_count == 15
        assert result.key_count == 2

        repo = ProfileRepository(ws)
        assert "ZUXOS_411" in repo.list_profiles()
        assert repo.get_active_profile_id() == "ZUXOS_411"

        profile = repo.load("ZUXOS_411")
        assert profile.schema_version == 3
        vbmeta = profile.partitions["vbmeta"]
        assert vbmeta.descriptor == DescriptorType.VBMETA
        assert vbmeta.algorithm == SigningAlgorithm.SHA256_RSA4096
        assert vbmeta.included_partitions[0] == "dtbo"
        assert vbmeta.chain_partitions[0] == "boot:3:testkey_rsa4096_pub.bin"

        # keys copied and manifest written
        key_dir = ws.resolve_key_dir("ZUXOS_411")
        assert (key_dir / "testkey_rsa4096.pem").is_file()
        assert (key_dir / "testkey_rsa4096_pub.bin").is_file()
        manifest = json.loads((key_dir / "manifest.json").read_text(encoding="utf-8"))
        assert set(manifest.keys()) == {"testkey_rsa2048", "testkey_rsa4096"}
        assert manifest["testkey_rsa4096"]["public_key_sha1"] == (
            "2597c218aae470a130f61162feaae70afd97f011"
        )

    def test_import_with_custom_id(self, tmp_path: Path) -> None:
        ws = WorkspacePaths.discover(tmp_path)
        ws.ensure_dirs()
        archive = _make_v1_archive(tmp_path)

        uc = LegacyConfigImportUseCase(ws)
        result = uc.execute(
            LegacyImportRequest(archive_path=str(archive), new_profile_id="my_device")
        )
        assert result.profile_id == "my_device"
        assert "my_device" in ProfileRepository(ws).list_profiles()
        assert "ZUXOS_411" not in ProfileRepository(ws).list_profiles()

    def test_import_does_not_activate(self, tmp_path: Path) -> None:
        ws = WorkspacePaths.discover(tmp_path)
        ws.ensure_dirs()
        archive = _make_v1_archive(tmp_path)

        uc = LegacyConfigImportUseCase(ws)
        result = uc.execute(LegacyImportRequest(archive_path=str(archive), activate=False))
        assert result.profile_id == "ZUXOS_411"
        assert ProfileRepository(ws).get_active_profile_id() is None

    def test_import_conflict(self, tmp_path: Path) -> None:
        ws = WorkspacePaths.discover(tmp_path)
        ws.ensure_dirs()
        archive = _make_v1_archive(tmp_path)

        uc = LegacyConfigImportUseCase(ws)
        uc.execute(LegacyImportRequest(archive_path=str(archive)))
        result = uc.execute(LegacyImportRequest(archive_path=str(archive)))
        assert any(i.error_code == "config.profile_exists" for i in result.issues)

    def test_not_legacy_archive_rejected(self, tmp_path: Path) -> None:
        ws = WorkspacePaths.discover(tmp_path)
        ws.ensure_dirs()
        plain = tmp_path / "plain.zip"
        with zipfile.ZipFile(plain, "w") as zf:
            zf.writestr("foo.txt", "x")

        uc = LegacyConfigImportUseCase(ws)
        result = uc.execute(LegacyImportRequest(archive_path=str(plain)))
        assert any(i.error_code == "config.invalid_archive" for i in result.issues)

    def test_v2_archive_not_importable_as_legacy(self, tmp_path: Path) -> None:
        """A v2 archive must be rejected by the legacy path, and vice versa."""
        ws = WorkspacePaths.discover(tmp_path)
        ws.ensure_dirs()

        # Build a v2 profile + archive
        profile_dir = ws.resolve_profile_dir("v2")
        profile_dir.mkdir(parents=True, exist_ok=True)
        key_dir = profile_dir / "keys"
        key_dir.mkdir()
        (profile_dir / "profile.json").write_text(
            json.dumps(encode_profile(AvbProfile(id="v2", name="V2"))),
            encoding="utf-8",
        )
        (key_dir / "manifest.json").write_text("{}", encoding="utf-8")
        v2_archive = tmp_path / "v2.zip"
        export_uc = ConfigExportUseCase(ws)
        export_uc.execute(ConfigExportRequest(profile_id="v2", output_path=str(v2_archive)))

        legacy_uc = LegacyConfigImportUseCase(ws)
        result = legacy_uc.execute(LegacyImportRequest(archive_path=str(v2_archive)))
        assert any(i.error_code == "config.invalid_archive" for i in result.issues)

        # And a v1 archive must be rejected by the regular (v2-only) import path
        v1_archive = _make_v1_archive(tmp_path, "v1.zip")
        regular = ConfigImportUseCase(ws)
        regular_result = regular.execute(ConfigImportRequest(archive_path=str(v1_archive)))
        assert any(
            "invalid_archive" in i.error_code or "import_failed" in i.error_code
            for i in regular_result.issues
        )


class TestLegacyImportTuiWiring:
    """The TUI must expose the legacy import action end to end."""

    def _nav_file(self) -> Path:
        return (
            Path(__file__).parent.parent.parent / "avbpowertool" / "resources" / "navigation.json"
        )

    def test_misc_route_has_legacy_import_action(self) -> None:
        from avbpowertool.presentation.tui.router import Router

        router = Router(self._nav_file())
        misc_route = router.get_route("route:misc")
        assert misc_route is not None
        actions = [item.action_id for item in misc_route.items]
        assert "action:misc.import_legacy" in actions
        # shortcut 'I' must not collide with existing misc shortcuts
        shortcuts = [item.shortcut for item in misc_route.items]
        assert len(shortcuts) == len(set(shortcuts))
        assert "action:misc.import_legacy" in router._actions

    def test_misc_view_exposes_handler(self) -> None:
        from avbpowertool.presentation.tui.views import import_legacy as import_legacy_view

        assert callable(import_legacy_view.show)

    def test_app_view_map_includes_handler(self) -> None:
        """The production app must dispatch the new action to its handler."""
        import inspect

        from avbpowertool.presentation.tui import app as tui_app

        source = inspect.getsource(tui_app.App._dispatch_action)
        assert "action:misc.import_legacy" in source
        assert "import_legacy.show" in source
