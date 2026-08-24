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
    (profile_dir / "profile.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


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
