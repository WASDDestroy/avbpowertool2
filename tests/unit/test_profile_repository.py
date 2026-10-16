"""Tests for ProfileRepository."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from avbpowertool.domain.errors import ConfigError
from avbpowertool.domain.models import (
    AvbProfile,
    DescriptorType,
    PartitionConfig,
    SigningAlgorithm,
)
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.persistence.profile_codec import encode_profile
from avbpowertool.infrastructure.persistence.profile_repository import ProfileRepository


def _make_workspace(tmp_path: Path) -> WorkspacePaths:
    ws = WorkspacePaths.discover(tmp_path)
    ws.ensure_dirs()
    return ws


def _write_profile(ws: WorkspacePaths, profile: AvbProfile) -> None:
    profile_dir = ws.resolve_profile_dir(profile.id)
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "keys").mkdir(exist_ok=True)
    data = encode_profile(profile)
    (profile_dir / "profile.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


class TestProfileRepositoryLoad:
    def test_load_existing(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        profile = AvbProfile(id="test", name="Test")
        _write_profile(ws, profile)

        repo = ProfileRepository(ws)
        loaded = repo.load("test")
        assert loaded.id == "test"
        assert loaded.name == "Test"

    def test_load_nonexistent_raises(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        repo = ProfileRepository(ws)
        with pytest.raises(ConfigError, match="not found"):
            repo.load("nonexistent")

    def test_load_preserves_partitions(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        profile = AvbProfile(
            id="test",
            name="Test",
            partitions={
                "boot": PartitionConfig(
                    image="boot.img",
                    descriptor=DescriptorType.HASH,
                    algorithm=SigningAlgorithm.SHA256_RSA4096,
                    key_id="testkey",
                    partition_name="boot",
                ),
            },
        )
        _write_profile(ws, profile)

        repo = ProfileRepository(ws)
        loaded = repo.load("test")
        assert "boot" in loaded.partitions
        assert loaded.partitions["boot"].image == "boot.img"


class TestProfileRepositorySave:
    def test_save_creates_profile_json(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        repo = ProfileRepository(ws)
        profile = AvbProfile(id="saved", name="Saved Profile")
        repo.save(profile)

        profile_json = ws.resolve_profile_dir("saved") / "profile.json"
        assert profile_json.exists()
        data = json.loads(profile_json.read_text(encoding="utf-8"))
        assert data["profile"]["id"] == "saved"


class TestProfileRepositoryList:
    def test_list_profiles(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        _write_profile(ws, AvbProfile(id="alpha", name="A"))
        _write_profile(ws, AvbProfile(id="beta", name="B"))

        repo = ProfileRepository(ws)
        profiles = repo.list_profiles()
        assert "alpha" in profiles
        assert "beta" in profiles

    def test_list_empty(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        repo = ProfileRepository(ws)
        assert repo.list_profiles() == ()


class TestProfileRepositoryDelete:
    def test_delete_existing(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        _write_profile(ws, AvbProfile(id="del", name="Del"))
        repo = ProfileRepository(ws)
        repo.delete("del")
        assert repo.list_profiles() == ()

    def test_delete_nonexistent_raises(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        repo = ProfileRepository(ws)
        with pytest.raises(ConfigError, match="not found"):
            repo.delete("nonexistent")


class TestProfileRepositoryActivate:
    def test_activate_and_get(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        repo = ProfileRepository(ws)

        assert repo.get_active_profile_id() is None
        repo.activate("myprofile")
        assert repo.get_active_profile_id() == "myprofile"

    def test_activate_overwrites(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        repo = ProfileRepository(ws)
        repo.activate("first")
        repo.activate("second")
        assert repo.get_active_profile_id() == "second"


class TestResolveProfileId:
    # Rule 1: a literal profile named like the request always wins.

    def test_literal_id_returned(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        _write_profile(ws, AvbProfile(id="device_a", name="A"))

        repo = ProfileRepository(ws)
        assert repo.resolve_profile_id("device_a") == "device_a"

    def test_literal_current_wins_over_active_profile(self, tmp_path: Path) -> None:
        """A profile really named ``current`` keeps working (conftest layout)."""
        ws = _make_workspace(tmp_path)
        _write_profile(ws, AvbProfile(id="current", name="Current"))
        _write_profile(ws, AvbProfile(id="device_a", name="A"))
        repo = ProfileRepository(ws)
        repo.activate("device_a")

        assert repo.resolve_profile_id("current") == "current"

    # Rule 2: ``current``/empty falls back to the active profile.

    def test_current_resolves_to_active_profile(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        _write_profile(ws, AvbProfile(id="device_a", name="A"))
        _write_profile(ws, AvbProfile(id="device_b", name="B"))
        repo = ProfileRepository(ws)
        repo.activate("device_b")

        assert repo.resolve_profile_id("current") == "device_b"
        assert repo.resolve_profile_id("") == "device_b"

    def test_whitespace_request_resolves_to_active_profile(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        _write_profile(ws, AvbProfile(id="device_a", name="A"))
        repo = ProfileRepository(ws)
        repo.activate("device_a")

        assert repo.resolve_profile_id("  ") == "device_a"

    # Rule 3: unresolvable requests raise ConfigError.

    def test_no_active_profile_raises(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        _write_profile(ws, AvbProfile(id="device_a", name="A"))
        repo = ProfileRepository(ws)

        with pytest.raises(ConfigError) as excinfo:
            repo.resolve_profile_id("current")

        assert excinfo.value.error_code == "config.no_active_profile"
        assert "config activate" in str(excinfo.value)

    def test_empty_request_without_any_profile_raises(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        repo = ProfileRepository(ws)

        with pytest.raises(ConfigError) as excinfo:
            repo.resolve_profile_id("")

        assert excinfo.value.error_code == "config.no_active_profile"

    def test_active_profile_pointing_to_missing_id_raises(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        _write_profile(ws, AvbProfile(id="device_a", name="A"))
        repo = ProfileRepository(ws)
        repo.activate("ghost")

        with pytest.raises(ConfigError) as excinfo:
            repo.resolve_profile_id("current")

        assert excinfo.value.error_code == "config.no_active_profile"

    def test_unknown_explicit_id_raises_not_found(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        _write_profile(ws, AvbProfile(id="device_a", name="A"))
        repo = ProfileRepository(ws)
        repo.activate("device_a")

        with pytest.raises(ConfigError) as excinfo:
            repo.resolve_profile_id("ghost")

        assert excinfo.value.error_code == "config.not_found"
        assert "ghost" in str(excinfo.value)
