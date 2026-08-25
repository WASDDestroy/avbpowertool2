"""Tests for ResolveChainKeysUseCase — chain descriptor -> key file mapping."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from avbpowertool.application.commands import (
    KeyDiscoveryRequest,
    ResolveChainKeysRequest,
)
from avbpowertool.application.ports import AvbToolResult
from avbpowertool.application.services.manage_keys import KeyDiscoveryUseCase
from avbpowertool.application.services.resolve_chains import ResolveChainKeysUseCase
from avbpowertool.domain.models import ChainDescriptor
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from tests.conftest import FakeAvbTool

PUB_BLOB = b"\x30\x81\x89\x02\x01\x00fake-public-key-blob"
PUB_SHA1 = hashlib.sha1(PUB_BLOB).hexdigest()
OTHER_BLOB = b"\x30\x81\x89\x02\x01\x00other-public-key-blob"


class _WritingFakeAvbTool(FakeAvbTool):
    """FakeAvbTool whose extract_public_key writes a known blob per key."""

    def extract_public_key(self, key_path: Path, output_path: Path) -> AvbToolResult:
        self._record("extract_public_key", (key_path, output_path), {})
        if key_path.name.startswith("other"):
            output_path.write_bytes(OTHER_BLOB)
        else:
            output_path.write_bytes(PUB_BLOB)
        return AvbToolResult(0, "", "", "extract_public_key")


def _make_workspace(tmp_path: Path) -> WorkspacePaths:
    ws = WorkspacePaths(
        root=tmp_path,
        images=tmp_path / "Images",
        profiles=tmp_path / "profiles",
        logs=tmp_path / "Logs",
        staging=tmp_path / ".avbpowertool-staging",
        avbtool_script=tmp_path / "avbtool.py",
    )
    ws.ensure_dirs()
    key_dir = tmp_path / "profiles" / "current" / "keys"
    key_dir.mkdir(parents=True, exist_ok=True)
    (key_dir / "key.pem").write_text("fake key", encoding="utf-8")
    (key_dir / "other.pem").write_text("fake other key", encoding="utf-8")
    (key_dir / "manifest.json").write_text(
        json.dumps(
            {
                "default": {"private_key": "key.pem"},
                "other": {"private_key": "other.pem"},
            }
        ),
        encoding="utf-8",
    )
    return ws


def _chain(name: str, slot: str = "1") -> ChainDescriptor:
    return ChainDescriptor(
        partition_name=name,
        rollback_index_location=slot,
        public_key_sha1=PUB_SHA1,
    )


class TestResolveChainKeys:
    def test_resolves_matching_key(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        uc = ResolveChainKeysUseCase(ws, _WritingFakeAvbTool())
        result = uc.execute(
            ResolveChainKeysRequest(
                profile_id="current",
                chains=(_chain("vbmeta_system"),),
            )
        )

        assert result.issues == ()
        assert len(result.resolutions) == 1
        res = result.resolutions[0]
        assert res.entry == "vbmeta_system:1:key.pem"
        assert res.key_id == "default"

    def test_unmatched_key_reports_issue_and_empty_entry(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        uc = ResolveChainKeysUseCase(ws, _WritingFakeAvbTool())
        result = uc.execute(
            ResolveChainKeysRequest(
                profile_id="current",
                chains=(
                    ChainDescriptor(
                        partition_name="vbmeta_system",
                        rollback_index_location="1",
                        public_key_sha1="f" * 40,
                    ),
                ),
            )
        )

        assert len(result.resolutions) == 1
        assert result.resolutions[0].entry == ""
        assert result.resolutions[0].key_id is None
        assert any(i.error_code == "chain.key_not_found" for i in result.issues)

    def test_multiple_chains_resolve_in_order(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        uc = ResolveChainKeysUseCase(ws, _WritingFakeAvbTool())
        result = uc.execute(
            ResolveChainKeysRequest(
                profile_id="current",
                chains=(_chain("vbmeta_system", "1"), _chain("vbmeta_vendor", "2")),
            )
        )

        assert [r.entry for r in result.resolutions] == [
            "vbmeta_system:1:key.pem",
            "vbmeta_vendor:2:key.pem",
        ]

    def test_no_chains_returns_empty(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        uc = ResolveChainKeysUseCase(ws, _WritingFakeAvbTool())
        result = uc.execute(ResolveChainKeysRequest(profile_id="current"))

        assert result.resolutions == ()
        assert result.issues == ()

    def test_missing_manifest_no_match(self, tmp_path: Path) -> None:
        ws = WorkspacePaths(
            root=tmp_path,
            images=tmp_path / "Images",
            profiles=tmp_path / "profiles",
            logs=tmp_path / "Logs",
            staging=tmp_path / ".avbpowertool-staging",
            avbtool_script=tmp_path / "avbtool.py",
        )
        ws.ensure_dirs()
        uc = ResolveChainKeysUseCase(ws, _WritingFakeAvbTool())
        result = uc.execute(
            ResolveChainKeysRequest(profile_id="current", chains=(_chain("vbmeta"),))
        )

        assert len(result.resolutions) == 1
        assert result.resolutions[0].entry == ""
        assert any(i.error_code == "chain.key_not_found" for i in result.issues)

    def test_discovered_keys_resolve_after_wizard_prepares_store(
        self, tmp_path: Path
    ) -> None:
        """The wizard runs key discovery before scanning images; chains must
        then resolve against the manifest discovery just wrote."""
        ws = WorkspacePaths(
            root=tmp_path,
            images=tmp_path / "Images",
            profiles=tmp_path / "profiles",
            logs=tmp_path / "Logs",
            staging=tmp_path / ".avbpowertool-staging",
            avbtool_script=tmp_path / "avbtool.py",
        )
        ws.ensure_dirs()
        # The wizard creates the key dir and the user drops a .pem in it.
        key_dir = ws.resolve_key_dir("my_device")
        key_dir.mkdir(parents=True, exist_ok=True)
        (key_dir / "release.pem").write_text("fake key", encoding="utf-8")

        discovery = KeyDiscoveryUseCase(ws).execute(
            KeyDiscoveryRequest(profile_id="my_device")
        )
        assert discovery.discovered_count == 1
        assert discovery.manifest_entries == (("release", "release.pem"),)

        resolution = ResolveChainKeysUseCase(ws, _WritingFakeAvbTool()).execute(
            ResolveChainKeysRequest(
                profile_id="my_device",
                chains=(_chain("vbmeta_system"),),
            )
        )
        assert resolution.issues == ()
        assert resolution.resolutions[0].entry == "vbmeta_system:1:release.pem"