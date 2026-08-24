"""Tests for KeyRepository."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from avbpowertool.domain.errors import ConfigError
from avbpowertool.infrastructure.persistence.key_repository import KeyRepository


class TestKeyRepositoryLoadManifest:
    def test_load_existing(self, tmp_path: Path) -> None:
        key_dir = tmp_path / "keys"
        key_dir.mkdir()
        manifest = {"testkey": {"private_key": "test.pem"}}
        (key_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        repo = KeyRepository(key_dir)
        loaded = repo.load_manifest()
        assert "testkey" in loaded

    def test_load_missing_returns_empty(self, tmp_path: Path) -> None:
        key_dir = tmp_path / "keys"
        key_dir.mkdir()
        repo = KeyRepository(key_dir)
        assert repo.load_manifest() == {}

    def test_load_non_dict_returns_empty(self, tmp_path: Path) -> None:
        key_dir = tmp_path / "keys"
        key_dir.mkdir()
        (key_dir / "manifest.json").write_text("not a dict", encoding="utf-8")
        repo = KeyRepository(key_dir)
        assert repo.load_manifest() == {}


class TestKeyRepositorySaveManifest:
    def test_save_creates_file(self, tmp_path: Path) -> None:
        key_dir = tmp_path / "keys"
        key_dir.mkdir()
        repo = KeyRepository(key_dir)
        manifest = {"mykey": {"private_key": "my.pem"}}
        repo.save_manifest(manifest)
        assert (key_dir / "manifest.json").exists()

    def test_round_trip(self, tmp_path: Path) -> None:
        key_dir = tmp_path / "keys"
        key_dir.mkdir()
        repo = KeyRepository(key_dir)
        manifest = {
            "key1": {"private_key": "key1.pem", "public_key": "key1_pub.bin"},
            "key2": {"private_key": "key2.pem"},
        }
        repo.save_manifest(manifest)
        loaded = repo.load_manifest()
        assert loaded == manifest


class TestKeyRepositoryResolveKeyPath:
    def test_resolve_existing(self, tmp_path: Path) -> None:
        key_dir = tmp_path / "keys"
        key_dir.mkdir()
        (key_dir / "test.pem").write_text("fake key")
        manifest = {"testkey": {"private_key": "test.pem"}}
        (key_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        repo = KeyRepository(key_dir)
        path = repo.resolve_key_path("testkey")
        assert path.name == "test.pem"
        assert path.exists()

    def test_resolve_missing_key_id_raises(self, tmp_path: Path) -> None:
        key_dir = tmp_path / "keys"
        key_dir.mkdir()
        (key_dir / "manifest.json").write_text("{}", encoding="utf-8")

        repo = KeyRepository(key_dir)
        with pytest.raises(ConfigError, match="not found in manifest"):
            repo.resolve_key_path("nonexistent")

    def test_resolve_missing_file_raises(self, tmp_path: Path) -> None:
        key_dir = tmp_path / "keys"
        key_dir.mkdir()
        manifest = {"testkey": {"private_key": "missing.pem"}}
        (key_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        repo = KeyRepository(key_dir)
        with pytest.raises(ConfigError, match="not found"):
            repo.resolve_key_path("testkey")

    def test_resolve_empty_private_key_raises(self, tmp_path: Path) -> None:
        key_dir = tmp_path / "keys"
        key_dir.mkdir()
        manifest = {"testkey": {"private_key": ""}}
        (key_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        repo = KeyRepository(key_dir)
        with pytest.raises(ConfigError, match="no private_key"):
            repo.resolve_key_path("testkey")


class TestKeyRepositoryDiscoverKeys:
    def test_discover_pem_files(self, tmp_path: Path) -> None:
        key_dir = tmp_path / "keys"
        key_dir.mkdir()
        (key_dir / "key1.pem").write_text("key1")
        (key_dir / "key2.pem").write_text("key2")
        (key_dir / "other.txt").write_text("not a key")

        repo = KeyRepository(key_dir)
        discovered = repo.discover_keys()
        names = [name for name, _ in discovered]
        assert "key1.pem" in names
        assert "key2.pem" in names
        assert "other.txt" not in names

    def test_discover_empty_dir(self, tmp_path: Path) -> None:
        key_dir = tmp_path / "keys"
        key_dir.mkdir()
        repo = KeyRepository(key_dir)
        assert repo.discover_keys() == []

    def test_discover_nonexistent_dir(self, tmp_path: Path) -> None:
        repo = KeyRepository(tmp_path / "nonexistent")
        assert repo.discover_keys() == []
