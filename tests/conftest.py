"""Shared pytest fixtures for AVBPowerTool tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from avbpowertool.application.ports import AvbToolResult


# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"
AVBTOOL_OUTPUT_DIR = FIXTURES_DIR / "avbtool_output"
PROFILES_DIR = FIXTURES_DIR / "profiles"
ARCHIVES_DIR = FIXTURES_DIR / "archives"


# ---------------------------------------------------------------------------
# Sample avbtool output text loaders
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_hash_output() -> str:
    return (AVBTOOL_OUTPUT_DIR / "hash_descriptor.txt").read_text(encoding="utf-8")


@pytest.fixture
def sample_hashtree_output() -> str:
    return (AVBTOOL_OUTPUT_DIR / "hashtree_descriptor.txt").read_text(encoding="utf-8")


@pytest.fixture
def sample_vbmeta_no_descriptors() -> str:
    return (AVBTOOL_OUTPUT_DIR / "vbmeta_no_descriptors.txt").read_text(encoding="utf-8")


@pytest.fixture
def sample_vbmeta_with_chain() -> str:
    return (AVBTOOL_OUTPUT_DIR / "vbmeta_with_chain.txt").read_text(encoding="utf-8")


@pytest.fixture
def sample_hash_with_props() -> str:
    return (AVBTOOL_OUTPUT_DIR / "hash_with_props.txt").read_text(encoding="utf-8")


@pytest.fixture
def sample_no_footer_stderr() -> str:
    return (AVBTOOL_OUTPUT_DIR / "no_footer_stderr.txt").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Temporary workspace
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Create a minimal workspace directory structure in tmp_path.

    Layout:
      tmp_path/
        avbtool.py               (empty placeholder)
        profiles/
          current/
            profile.json
            keys/
              manifest.json
        Logs/
        .avbpowertool-staging/
    """
    ws = tmp_path
    (ws / "profiles").mkdir()
    (ws / "Logs").mkdir()
    (ws / ".avbpowertool-staging").mkdir()

    # avbtool placeholder
    (ws / "avbtool.py").write_text("# placeholder\n", encoding="utf-8")

    # default profile
    profile_dir = ws / "profiles" / "current"
    profile_dir.mkdir(parents=True)
    key_dir = profile_dir / "keys"
    key_dir.mkdir()

    profile = {
        "schema_version": 2,
        "profile": {"id": "current", "name": "Current"},
        "key_store_path": "keys",
        "partitions": {
            "boot": {
                "image": "boot.img",
                "descriptor": "hash",
                "algorithm": "SHA256_RSA4096",
                "key_id": "testkey_rsa4096",
                "partition_name": "boot",
                "rollback_index": 0,
                "salt": "a1b2c3d4e5f6",
                "flags": 0,
            },
            "vbmeta": {
                "image": "vbmeta.img",
                "descriptor": "vbmeta",
                "algorithm": "SHA256_RSA4096",
                "key_id": "testkey_rsa4096",
                "partition_name": "vbmeta",
                "rollback_index": 0,
                "flags": 0,
                "included_partitions": ["boot"],
            },
        },
    }
    (profile_dir / "profile.json").write_text(
        json.dumps(profile, indent=2), encoding="utf-8"
    )

    manifest = {
        "testkey_rsa4096": {
            "private_key": "testkey_rsa4096.pem",
            "public_key": "testkey_rsa4096_pub.bin",
            "public_key_sha1": "cd2c1e5e3c4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b",
        }
    }
    (key_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    return ws


# ---------------------------------------------------------------------------
# FakeAvbTool
# ---------------------------------------------------------------------------


class FakeAvbTool:
    """Configurable fake that returns pre-canned AvbToolResult objects."""

    def __init__(self, responses: dict[str, AvbToolResult] | None = None) -> None:
        self._responses: dict[str, AvbToolResult] = responses or {}
        self.calls: list[tuple[str, tuple, dict]] = []

    def _record(self, name: str, args: tuple, kwargs: dict) -> AvbToolResult:
        self.calls.append((name, args, kwargs))
        if name in self._responses:
            return self._responses[name]
        return AvbToolResult(0, "", "", name)

    def inspect_image(self, image_path: Path) -> AvbToolResult:
        return self._record("inspect_image", (image_path,), {})

    def erase_footer(self, image_path: Path) -> AvbToolResult:
        return self._record("erase_footer", (image_path,), {})

    def add_hash_footer(
        self,
        image_path: Path,
        output_path: Path,
        *,
        partition_name: str,
        algorithm: str,
        key_path: Path,
        salt: str,
        rollback_index: int,
        flags: int = 0,
        props: tuple[tuple[str, str], ...] = (),
    ) -> AvbToolResult:
        return self._record("add_hash_footer", (image_path, output_path), {})

    def add_hashtree_footer(
        self,
        image_path: Path,
        output_path: Path,
        *,
        partition_name: str,
        algorithm: str,
        key_path: Path,
        salt: str,
        rollback_index: int,
        data_block_size: int = 4096,
        hash_block_size: int = 4096,
        flags: int = 0,
        props: tuple[tuple[str, str], ...] = (),
    ) -> AvbToolResult:
        return self._record("add_hashtree_footer", (image_path, output_path), {})

    def make_vbmeta_image(
        self,
        output_path: Path,
        *,
        algorithm: str,
        key_path: Path,
        rollback_index: int,
        include_descriptors: tuple[Path, ...] = (),
        chain_partitions: tuple[str, ...] = (),
        flags: int = 0,
        props: tuple[tuple[str, str], ...] = (),
    ) -> AvbToolResult:
        return self._record("make_vbmeta_image", (output_path,), {})

    def extract_public_key(self, key_path: Path, output_path: Path) -> AvbToolResult:
        return self._record("extract_public_key", (key_path, output_path), {})


@pytest.fixture
def fake_avb_tool() -> FakeAvbTool:
    return FakeAvbTool()


@pytest.fixture
def sample_profile_v2() -> dict[str, Any]:
    """A complete v2 profile dict for testing codec round-trips."""
    return {
        "schema_version": 2,
        "profile": {"id": "test_profile", "name": "Test Profile"},
        "key_store_path": "keys",
        "partitions": {
            "boot": {
                "image": "boot.img",
                "descriptor": "hash",
                "algorithm": "SHA256_RSA4096",
                "key_id": "release_rsa4096",
                "partition_name": "boot",
                "rollback_index": 0,
                "salt": "abcdef123456",
                "flags": 0,
                "props": [["android.boot.vbmeta.digest", "sha256_of_vbmeta"]],
            },
            "system": {
                "image": "system.img",
                "descriptor": "hashtree",
                "algorithm": "SHA256_RSA4096",
                "key_id": "release_rsa4096",
                "partition_name": "system",
                "rollback_index": 0,
                "data_block_size": 4096,
                "hash_block_size": 4096,
            },
            "vbmeta": {
                "image": "vbmeta.img",
                "descriptor": "vbmeta",
                "algorithm": "SHA256_RSA4096",
                "key_id": "release_rsa4096",
                "partition_name": "vbmeta",
                "rollback_index": 0,
                "flags": 0,
                "included_partitions": ["boot", "system"],
            },
        },
    }


@pytest.fixture
def sample_manifest_v2() -> dict[str, Any]:
    """A complete v2 key manifest dict."""
    return {
        "release_rsa4096": {
            "private_key": "release_rsa4096.pem",
            "public_key": "release_rsa4096_pub.bin",
            "public_key_sha1": "abcdef1234567890abcdef1234567890abcdef12",
        },
        "testkey_rsa2048": {
            "private_key": "testkey_rsa2048.pem",
            "public_key": "testkey_rsa2048_pub.bin",
            "public_key_sha1": "1234567890abcdef1234567890abcdef12345678",
        },
    }
