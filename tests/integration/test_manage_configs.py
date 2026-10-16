"""Integration tests for config management use cases."""

from __future__ import annotations

import json
from pathlib import Path

from avbpowertool.application.commands import (
    ConfigCreateRequest,
    ConfigExportRequest,
    ConfigImportRequest,
    ConfigShowRequest,
    ConfigValidateRequest,
    ProfileDeleteRequest,
)
from avbpowertool.application.services.manage_configs import (
    ConfigCreateUseCase,
    ConfigExportUseCase,
    ConfigImportUseCase,
    ConfigShowUseCase,
    ConfigValidateUseCase,
)
from avbpowertool.application.services.manage_profiles import ProfileDeleteUseCase
from avbpowertool.domain.models import (
    AvbProfile,
    DescriptorType,
    PartitionConfig,
    SigningAlgorithm,
)
from avbpowertool.domain.validation import validate_profile
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.persistence.profile_codec import encode_profile
from avbpowertool.infrastructure.persistence.profile_repository import ProfileRepository


def _setup_profile(tmp_path: Path) -> WorkspacePaths:
    ws = WorkspacePaths.discover(tmp_path)
    ws.ensure_dirs()
    profile_dir = ws.resolve_profile_dir("test")
    profile_dir.mkdir(parents=True, exist_ok=True)
    key_dir = profile_dir / "keys"
    key_dir.mkdir()
    (profile_dir / "profile.json").write_text(
        json.dumps(encode_profile(AvbProfile(id="test", name="Test Profile"))),
        encoding="utf-8",
    )
    return ws


class TestProfileDeleteUseCase:
    def test_delete_profile(self, tmp_path: Path) -> None:
        ws = _setup_profile(tmp_path)
        result = ProfileDeleteUseCase(ws).execute(ProfileDeleteRequest(profile_id="test"))
        assert result.issues == ()
        assert "test" not in ProfileRepository(ws).list_profiles()

    def test_delete_active_profile_is_forbidden(self, tmp_path: Path) -> None:
        ws = _setup_profile(tmp_path)
        ProfileRepository(ws).activate("test")
        result = ProfileDeleteUseCase(ws).execute(ProfileDeleteRequest(profile_id="test"))
        assert any(i.error_code == "config.active_delete_forbidden" for i in result.issues)
        assert "test" in ProfileRepository(ws).list_profiles()


class TestConfigShowUseCase:
    def test_show_existing_profile(self, tmp_path: Path) -> None:
        ws = _setup_profile(tmp_path)
        uc = ConfigShowUseCase(ws)
        result = uc.execute(ConfigShowRequest(profile_id="test"))
        assert result.config_name == "test"
        assert len(result.issues) == 0

    def test_show_nonexistent_profile(self, tmp_path: Path) -> None:
        ws = _setup_profile(tmp_path)
        uc = ConfigShowUseCase(ws)
        result = uc.execute(ConfigShowRequest(profile_id="nonexistent"))
        assert any(i.error_code == "config.not_found" for i in result.issues)


def _partition(name: str, algorithm: SigningAlgorithm, key_id: str) -> PartitionConfig:
    return PartitionConfig(
        image=f"{name}.img",
        descriptor=DescriptorType.HASH,
        algorithm=algorithm,
        key_id=key_id,
        partition_name=name,
        partition_size=4096,
    )


def _setup_profile_with_partitions(
    tmp_path: Path, partitions: dict[str, PartitionConfig]
) -> WorkspacePaths:
    """Write a profile holding *partitions* and a one-key store.

    The store really holds ``testkey_rsa4096``, so a partition reported as
    missing is missing for its own reason — not because the store is absent.
    """
    ws = _setup_profile(tmp_path)
    profile_dir = ws.resolve_profile_dir("test")
    (profile_dir / "profile.json").write_text(
        json.dumps(
            encode_profile(
                AvbProfile(
                    id="test",
                    name="Test Profile",
                    key_store_path="keys",
                    partitions=partitions,
                )
            )
        ),
        encoding="utf-8",
    )
    key_dir = profile_dir / "keys"
    (key_dir / "testkey_rsa4096.pem").write_text("fake key", encoding="utf-8")
    (key_dir / "manifest.json").write_text(
        json.dumps({"testkey_rsa4096": {"private_key": "testkey_rsa4096.pem"}}),
        encoding="utf-8",
    )
    for config in partitions.values():
        (ws.images / config.image).write_bytes(b"x" * 4096)
    return ws


class TestConfigValidateUseCase:
    def test_validate_missing_images(self, tmp_path: Path) -> None:
        ws = _setup_profile(tmp_path)
        uc = ConfigValidateUseCase(ws)
        result = uc.execute(ConfigValidateRequest(profile_id="test"))
        # No images exist, no partitions defined, so no missing images
        assert result.config_name == "test"

    def test_unsigned_partition_with_empty_key_is_not_missing(self, tmp_path: Path) -> None:
        ws = _setup_profile_with_partitions(
            tmp_path, {"dtbo": _partition("dtbo", SigningAlgorithm.NONE, "")}
        )

        result = ConfigValidateUseCase(ws).execute(ConfigValidateRequest(profile_id="test"))

        assert result.missing_images == ()
        assert result.missing_keys == ()

    def test_unsigned_partition_with_unknown_key_is_not_missing(self, tmp_path: Path) -> None:
        """An unsigned partition is not checked against the manifest at all,
        so even a stale key_id is not reported."""
        ws = _setup_profile_with_partitions(
            tmp_path, {"dtbo": _partition("dtbo", SigningAlgorithm.NONE, "nonexistent")}
        )

        result = ConfigValidateUseCase(ws).execute(ConfigValidateRequest(profile_id="test"))

        assert result.missing_images == ()
        assert result.missing_keys == ()

    def test_signed_partition_with_unknown_key_is_missing(self, tmp_path: Path) -> None:
        ws = _setup_profile_with_partitions(
            tmp_path,
            {"boot": _partition("boot", SigningAlgorithm.SHA256_RSA4096, "ghost")},
        )

        result = ConfigValidateUseCase(ws).execute(ConfigValidateRequest(profile_id="test"))

        assert result.missing_images == ()
        assert result.missing_keys == ("ghost",)

    def test_signed_partition_with_empty_key_is_missing(self, tmp_path: Path) -> None:
        """Signing with no key is still an error: the NONE exemption must not
        widen into a blanket "empty key_id is fine" rule."""
        ws = _setup_profile_with_partitions(
            tmp_path,
            {"boot": _partition("boot", SigningAlgorithm.SHA256_RSA4096, "")},
        )

        result = ConfigValidateUseCase(ws).execute(ConfigValidateRequest(profile_id="test"))

        assert result.missing_images == ()
        assert result.missing_keys == ("",)


class TestConfigImportExportUseCase:
    def test_export_then_import_round_trip(self, tmp_path: Path) -> None:
        ws = _setup_profile(tmp_path)
        export_uc = ConfigExportUseCase(ws)
        archive_path = tmp_path / "export.zip"
        export_result = export_uc.execute(
            ConfigExportRequest(profile_id="test", output_path=str(archive_path))
        )
        assert archive_path.exists()
        assert len(export_result.issues) == 0

        # Delete original
        repo = ProfileRepository(ws)
        repo.delete("test")
        assert "test" not in repo.list_profiles()

        # Import
        import_uc = ConfigImportUseCase(ws)
        import_result = import_uc.execute(ConfigImportRequest(archive_path=str(archive_path)))
        assert import_result.profile_id == "test"
        assert len(import_result.issues) == 0
        assert "test" in repo.list_profiles()

    def test_import_with_new_id(self, tmp_path: Path) -> None:
        ws = _setup_profile(tmp_path)
        export_uc = ConfigExportUseCase(ws)
        archive_path = tmp_path / "export.zip"
        export_uc.execute(ConfigExportRequest(profile_id="test", output_path=str(archive_path)))

        import_uc = ConfigImportUseCase(ws)
        result = import_uc.execute(
            ConfigImportRequest(archive_path=str(archive_path), new_profile_id="renamed")
        )
        assert result.profile_id == "renamed"

    def test_import_conflict(self, tmp_path: Path) -> None:
        ws = _setup_profile(tmp_path)
        export_uc = ConfigExportUseCase(ws)
        archive_path = tmp_path / "export.zip"
        export_uc.execute(ConfigExportRequest(profile_id="test", output_path=str(archive_path)))

        import_uc = ConfigImportUseCase(ws)
        result = import_uc.execute(ConfigImportRequest(archive_path=str(archive_path)))
        # Conflict is caught as import_failed wrapping the profile_exists error
        assert any(
            "import_failed" in i.error_code or "already exists" in i.message for i in result.issues
        )

    def test_export_nonexistent(self, tmp_path: Path) -> None:
        ws = _setup_profile(tmp_path)
        uc = ConfigExportUseCase(ws)
        result = uc.execute(
            ConfigExportRequest(profile_id="nonexistent", output_path=str(tmp_path / "out.zip"))
        )
        assert any(i.error_code == "config.export_failed" for i in result.issues)


class TestConfigCreateUseCase:
    def test_create_profile_is_schema_v3_and_valid(self, tmp_path: Path) -> None:
        ws = WorkspacePaths.discover(tmp_path)
        ws.ensure_dirs()
        uc = ConfigCreateUseCase(ws)

        result = uc.execute(
            ConfigCreateRequest(
                profile_id="my_device",
                profile_name="My Device",
                partitions=(
                    PartitionConfig(
                        image="boot.img",
                        descriptor=DescriptorType.HASH,
                        algorithm=SigningAlgorithm.SHA256_RSA4096,
                        key_id="testkey_rsa4096",
                        partition_name="boot",
                        partition_size=67108864,
                    ),
                    PartitionConfig(
                        image="vbmeta.img",
                        descriptor=DescriptorType.VBMETA,
                        algorithm=SigningAlgorithm.SHA256_RSA4096,
                        key_id="testkey_rsa4096",
                        partition_name="vbmeta",
                        included_partitions=("boot",),
                    ),
                ),
                activate=False,
            )
        )

        assert result.issues == ()
        profile = ProfileRepository(ws).load("my_device")
        assert profile.schema_version == 3
        # The created profile must pass domain validation (regression: the
        # create path used to hardcode schema_version=2).
        assert validate_profile(profile) == []

    def test_create_hash_without_size_reports_issue_but_creates(self, tmp_path: Path) -> None:
        ws = WorkspacePaths.discover(tmp_path)
        ws.ensure_dirs()
        uc = ConfigCreateUseCase(ws)

        result = uc.execute(
            ConfigCreateRequest(
                profile_id="incomplete",
                profile_name="Incomplete",
                partitions=(
                    PartitionConfig(
                        image="boot.img",
                        descriptor=DescriptorType.HASH,
                        algorithm=SigningAlgorithm.SHA256_RSA4096,
                        key_id="testkey_rsa4096",
                        partition_name="boot",
                    ),
                ),
                activate=False,
            )
        )

        # Not a hard failure: the profile is still created, but the user is
        # told the hash partition needs a size (fixable via 'config edit').
        assert any(i.error_code == "config.missing_partition_size" for i in result.issues)
        assert any(i.error_code == "config.invalid_schema_version" for i in result.issues) is False
        profile = ProfileRepository(ws).load("incomplete")
        assert profile.schema_version == 3

    def test_create_duplicate_id_rejected(self, tmp_path: Path) -> None:
        ws = _setup_profile(tmp_path)  # creates profile id "test"
        uc = ConfigCreateUseCase(ws)
        result = uc.execute(
            ConfigCreateRequest(
                profile_id="test",
                profile_name="Duplicate",
                partitions=(),
                activate=False,
            )
        )
        assert any(i.error_code == "config.profile_exists" for i in result.issues)

    def test_create_keeps_existing_key_manifest(self, tmp_path: Path) -> None:
        """Regression: creation used to overwrite manifest.json with {} —
        the wizard prepares the key store (discovery) before creating, and
        that manifest must survive profile creation."""
        ws = WorkspacePaths.discover(tmp_path)
        ws.ensure_dirs()
        key_dir = ws.resolve_key_dir("my_device")
        key_dir.mkdir(parents=True, exist_ok=True)
        (key_dir / "release.pem").write_text("fake key", encoding="utf-8")
        (key_dir / "manifest.json").write_text(
            json.dumps({"release": {"private_key": "release.pem"}}), encoding="utf-8"
        )

        uc = ConfigCreateUseCase(ws)
        result = uc.execute(
            ConfigCreateRequest(
                profile_id="my_device",
                profile_name="My Device",
                partitions=(
                    PartitionConfig(
                        image="boot.img",
                        descriptor=DescriptorType.HASH,
                        algorithm=SigningAlgorithm.SHA256_RSA4096,
                        key_id="release",
                        partition_name="boot",
                        partition_size=67108864,
                    ),
                ),
                activate=False,
            )
        )

        assert result.issues == ()
        on_disk = json.loads(
            (ws.resolve_key_dir("my_device") / "manifest.json").read_text(encoding="utf-8")
        )
        assert on_disk == {"release": {"private_key": "release.pem"}}


class TestConfigCreateAllowEmpty:
    """``allow_empty`` enables the "create config, then fill it" flow."""

    def test_allow_empty_creates_profile_without_partitions(self, tmp_path: Path) -> None:
        ws = WorkspacePaths.discover(tmp_path)
        ws.ensure_dirs()

        result = ConfigCreateUseCase(ws).execute(
            ConfigCreateRequest(
                profile_id="dev",
                profile_name="Dev",
                allow_empty=True,
                activate=False,
            )
        )

        assert result.issues == ()
        assert result.created is True
        assert result.profile_id == "dev"

        profile_path = ws.resolve_profile_dir("dev") / "profile.json"
        assert profile_path.is_file()
        assert json.loads(profile_path.read_text(encoding="utf-8"))["partitions"] == {}
        assert (ws.resolve_key_dir("dev") / "manifest.json").is_file()

    def test_without_allow_empty_rejects_and_creates_nothing(self, tmp_path: Path) -> None:
        ws = WorkspacePaths.discover(tmp_path)
        ws.ensure_dirs()

        result = ConfigCreateUseCase(ws).execute(
            ConfigCreateRequest(profile_id="dev", profile_name="Dev", activate=False)
        )

        assert any(i.error_code == "config.no_partitions" for i in result.issues)
        assert result.created is False
        assert not ws.resolve_profile_dir("dev").exists()

    def test_invalid_profile_id_rejected(self, tmp_path: Path) -> None:
        ws = WorkspacePaths.discover(tmp_path)
        ws.ensure_dirs()

        result = ConfigCreateUseCase(ws).execute(
            ConfigCreateRequest(
                profile_id="bad id!",
                profile_name="Bad",
                allow_empty=True,
                activate=False,
            )
        )

        assert any(i.error_code == "config.invalid_profile_id" for i in result.issues)
        assert result.created is False
        assert not (ws.profiles / "bad id!").exists()
        assert not (ws.profiles / "bad_id_").exists()

    def test_duplicate_id_rejected(self, tmp_path: Path) -> None:
        ws = _setup_profile(tmp_path)  # creates profile id "test"

        result = ConfigCreateUseCase(ws).execute(
            ConfigCreateRequest(
                profile_id="test",
                profile_name="Duplicate",
                allow_empty=True,
                activate=False,
            )
        )

        assert any(i.error_code == "config.profile_exists" for i in result.issues)
        assert result.created is False

    def test_allow_empty_still_requires_a_name(self, tmp_path: Path) -> None:
        """The use case keeps its strict "empty name is invalid" semantics.

        ``config.missing_profile_name`` is reported even under
        ``allow_empty`` (only ``config.no_partitions`` is suppressed); the
        CLI is what defaults the name to the id.
        """
        ws = WorkspacePaths.discover(tmp_path)
        ws.ensure_dirs()

        result = ConfigCreateUseCase(ws).execute(
            ConfigCreateRequest(
                profile_id="dev",
                profile_name="",
                allow_empty=True,
                activate=False,
            )
        )

        assert any(i.error_code == "config.missing_profile_name" for i in result.issues)
        assert all(i.error_code != "config.no_partitions" for i in result.issues)

    def test_allow_empty_activates_when_requested(self, tmp_path: Path) -> None:
        ws = WorkspacePaths.discover(tmp_path)
        ws.ensure_dirs()

        result = ConfigCreateUseCase(ws).execute(
            ConfigCreateRequest(
                profile_id="dev",
                profile_name="Dev",
                allow_empty=True,
                activate=True,
            )
        )

        assert result.issues == ()
        assert ProfileRepository(ws).get_active_profile_id() == "dev"
