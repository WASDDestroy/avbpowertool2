"""Tests for the TUI create-config wizard's auto-mode partition builder."""

from __future__ import annotations

from pathlib import Path

import pytest

import avbpowertool.presentation.tui.views.create_config as create_config_view
from avbpowertool.application.commands import ChainKeyResolution
from avbpowertool.application.ports import AvbToolResult
from avbpowertool.domain.models import (
    ChainDescriptor,
    DescriptorType,
    ImageInspection,
    PartitionConfig,
    SigningAlgorithm,
)
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.presentation.i18n import init_i18n
from avbpowertool.presentation.tui.views.create_config import (
    _apply_chain_resolutions,
    _auto_dir_default,
    _build_auto_partition,
    _finalize_vbmeta_includes,
)
from tests.conftest import FakeAvbTool


def _inspection(**overrides: object) -> ImageInspection:
    data: dict = dict(
        image_name="boot",
        image_path="/img/boot.img",
        descriptor=DescriptorType.HASH,
        algorithm="NONE",
        partition_name="boot",
        rollback_index="3",
        rollback_index_location="2",
        salt="a1b2c3d4e5f6",
        hash_algorithm="sha256",
        digest="d1e2f3",
        flags="2",
        props=(("android.boot.test", "1"),),
        raw_extensions=(),
    )
    data.update(overrides)  # type: ignore[arg-type]
    return ImageInspection(**data)  # type: ignore[arg-type]


class TestBuildAutoPartition:
    def test_reads_full_metadata(self, tmp_path: Path) -> None:
        (tmp_path / "boot.img").write_bytes(b"x" * 5000)
        config = _build_auto_partition(_inspection(), tmp_path)

        assert config is not None
        assert config.image == "boot.img"
        assert config.partition_name == "boot"
        # rollback index / location
        assert config.rollback_index == 3
        assert config.rollback_index_location == 2
        # salt / hash algorithm / props
        assert config.salt == "a1b2c3d4e5f6"
        assert config.hash_algorithm == "sha256"
        assert config.props == (("android.boot.test", "1"),)
        # signing algorithm from the header (NONE -> unsigned)
        assert config.algorithm == SigningAlgorithm.NONE
        # flags integer + flag-bit shortcuts (flags=2 -> VERIFICATION_DISABLED)
        assert config.flags == 2
        assert config.set_hashtree_disabled_flag is False
        assert config.set_verification_disabled_flag is True
        # partition size = image size rounded up to 4096
        assert config.partition_size == 8192

    def test_signed_algorithm_mapped(self, tmp_path: Path) -> None:
        config = _build_auto_partition(_inspection(algorithm="SHA256_RSA4096"), tmp_path)
        assert config is not None
        assert config.algorithm == SigningAlgorithm.SHA256_RSA4096

    def test_key_id_defaults_and_param(self, tmp_path: Path) -> None:
        default = _build_auto_partition(_inspection(), tmp_path)
        assert default is not None
        assert default.key_id == "default"

        chosen = _build_auto_partition(_inspection(), tmp_path, key_id="release")
        assert chosen is not None
        assert chosen.key_id == "release"

    def test_flag_bits(self, tmp_path: Path) -> None:
        config = _build_auto_partition(_inspection(flags="3"), tmp_path)
        assert config is not None
        assert config.flags == 3
        assert config.set_hashtree_disabled_flag is True
        assert config.set_verification_disabled_flag is True

    def test_hash_algorithm_clamped(self, tmp_path: Path) -> None:
        config = _build_auto_partition(_inspection(hash_algorithm="foobar"), tmp_path)
        assert config is not None
        assert config.hash_algorithm == "sha256"

    def test_hash_algorithm_missing_defaults(self, tmp_path: Path) -> None:
        config = _build_auto_partition(_inspection(hash_algorithm=None), tmp_path)
        assert config is not None
        assert config.hash_algorithm == "sha256"

    def test_hashtree_hash_algorithm_read(self, tmp_path: Path) -> None:
        config = _build_auto_partition(
            _inspection(
                descriptor=DescriptorType.HASHTREE,
                hash_algorithm="sha512",
                partition_name="system",
                image_name="system",
            ),
            tmp_path,
        )
        assert config is not None
        assert config.hash_algorithm == "sha512"

    def test_vbmeta_keeps_defaults_and_hashtree_flag(self, tmp_path: Path) -> None:
        config = _build_auto_partition(
            _inspection(
                descriptor=DescriptorType.VBMETA,
                image_name="vbmeta",
                partition_name="vbmeta",
                flags="1",
            ),
            tmp_path,
        )
        assert config is not None
        # vbmeta has no hash algorithm concept; default kept
        assert config.hash_algorithm == "sha256"
        assert config.set_hashtree_disabled_flag is True
        assert config.set_verification_disabled_flag is False

    def test_none_descriptor_returns_none(self, tmp_path: Path) -> None:
        inspection = ImageInspection(
            image_name="raw",
            image_path="/img/raw.img",
            descriptor=None,
        )
        assert _build_auto_partition(inspection, tmp_path) is None

    def test_empty_values_fall_back(self, tmp_path: Path) -> None:
        config = _build_auto_partition(
            _inspection(
                rollback_index=None,
                rollback_index_location=None,
                salt=None,
                flags=None,
                props=(),
            ),
            tmp_path,
        )
        assert config is not None
        assert config.rollback_index == 0
        assert config.rollback_index_location == 0
        assert config.salt == ""
        assert config.flags == 0
        assert config.props == ()


def _config(image: str, partition: str, descriptor: DescriptorType) -> PartitionConfig:
    return PartitionConfig(
        image=image,
        descriptor=descriptor,
        algorithm=SigningAlgorithm.SHA256_RSA4096,
        key_id="default",
        partition_name=partition,
    )


class TestFinalizeVbmetaIncludes:
    def test_uses_real_includes_limited_to_scan(self) -> None:
        by_image = {
            "boot.img": _config("boot.img", "boot", DescriptorType.HASH),
            "dtbo.img": _config("dtbo.img", "dtbo", DescriptorType.HASH),
            "vbmeta.img": _config("vbmeta.img", "vbmeta", DescriptorType.VBMETA),
        }
        included = {"vbmeta.img": ("dtbo", "odm", "init_boot")}
        partitions = _finalize_vbmeta_includes(by_image, included)
        vbmeta = next(p for p in partitions if p.partition_name == "vbmeta")
        # "odm"/"init_boot" are not in the scan -> dropped
        assert vbmeta.included_partitions == ("dtbo",)

    def test_falls_back_to_other_scanned_partitions(self) -> None:
        by_image = {
            "boot.img": _config("boot.img", "boot", DescriptorType.HASH),
            "system.img": _config("system.img", "system", DescriptorType.HASHTREE),
            "vbmeta.img": _config("vbmeta.img", "vbmeta", DescriptorType.VBMETA),
        }
        partitions = _finalize_vbmeta_includes(by_image, {})
        vbmeta = next(p for p in partitions if p.partition_name == "vbmeta")
        assert vbmeta.included_partitions == ("boot", "system")

    def test_fallback_excludes_other_vbmeta(self) -> None:
        by_image = {
            "boot.img": _config("boot.img", "boot", DescriptorType.HASH),
            "vbmeta.img": _config("vbmeta.img", "vbmeta", DescriptorType.VBMETA),
            "vbmeta_system.img": _config(
                "vbmeta_system.img", "vbmeta_system", DescriptorType.VBMETA
            ),
        }
        partitions = _finalize_vbmeta_includes(by_image, {})
        vbmeta = next(p for p in partitions if p.partition_name == "vbmeta")
        assert vbmeta.included_partitions == ("boot",)
        vbmeta_system = next(p for p in partitions if p.partition_name == "vbmeta_system")
        assert vbmeta_system.included_partitions == ("boot",)

    def test_no_image_entries_are_lost(self) -> None:
        """Every scanned image keeps its own entry (regression for the
        vbmeta.img overwriting the real dtbo.img entry bug)."""
        by_image = {
            "boot.img": _config("boot.img", "boot", DescriptorType.HASH),
            "dtbo.img": _config("dtbo.img", "dtbo", DescriptorType.HASH),
            "vbmeta.img": _config("vbmeta.img", "vbmeta", DescriptorType.VBMETA),
            "vbmeta_system.img": _config(
                "vbmeta_system.img", "vbmeta_system", DescriptorType.VBMETA
            ),
        }
        partitions = _finalize_vbmeta_includes(by_image, {"vbmeta.img": ("dtbo",)})
        names = {p.partition_name for p in partitions}
        assert names == {"boot", "dtbo", "vbmeta", "vbmeta_system"}
        # the real dtbo.img config keeps its own image file
        dtbo = next(p for p in partitions if p.partition_name == "dtbo")
        assert dtbo.image == "dtbo.img"


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


class TestApplyChainResolutions:
    def test_writes_resolved_entries_into_vbmeta_config(self) -> None:
        by_image = {
            "vbmeta.img": _config("vbmeta.img", "vbmeta", DescriptorType.VBMETA),
            "boot.img": _config("boot.img", "boot", DescriptorType.HASH),
        }
        chains = {
            "vbmeta.img": (
                ChainDescriptor("vbmeta_system", "1", "a" * 40),
                ChainDescriptor("vbmeta_vendor", "2", "b" * 40),
            )
        }
        resolutions = (
            ChainKeyResolution(entry="vbmeta_system:1:key.pem", key_id="k1"),
            ChainKeyResolution(entry="vbmeta_vendor:2:other.pem", key_id="k2"),
        )
        result = _apply_chain_resolutions(by_image, chains, resolutions)
        vbmeta = result["vbmeta.img"]
        assert vbmeta.chain_partitions == (
            "vbmeta_system:1:key.pem",
            "vbmeta_vendor:2:other.pem",
        )

    def test_unresolved_entries_are_skipped(self) -> None:
        by_image = {
            "vbmeta.img": _config("vbmeta.img", "vbmeta", DescriptorType.VBMETA),
        }
        chains = {"vbmeta.img": (ChainDescriptor("vbmeta_system", "1", "a" * 40),)}
        resolutions = (ChainKeyResolution(entry=""),)
        result = _apply_chain_resolutions(by_image, chains, resolutions)
        assert result["vbmeta.img"].chain_partitions == ()

    def test_no_chain_images_unchanged(self) -> None:
        by_image = {
            "boot.img": _config("boot.img", "boot", DescriptorType.HASH),
        }
        result = _apply_chain_resolutions(by_image, {}, ())
        assert result["boot.img"].chain_partitions == ()
