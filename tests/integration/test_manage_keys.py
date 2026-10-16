"""Integration tests for key management use cases."""

from __future__ import annotations

import json
from pathlib import Path

from avbpowertool.application.commands import (
    KeyDiscoveryRequest,
    KeyEnsurePublicRequest,
)
from avbpowertool.application.ports import AvbToolResult
from avbpowertool.application.services.manage_keys import (
    KeyDiscoveryUseCase,
    KeyEnsurePublicUseCase,
)
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from tests.conftest import FakeAvbTool


class WritingFakeAvbTool(FakeAvbTool):
    """``FakeAvbTool`` that also materialises the extracted public key.

    The real ``SubprocessAvbTool`` writes ``output_path``; the use case
    verifies the file exists afterwards, so the fake has to do the same.
    """

    def extract_public_key(self, key_path: Path, output_path: Path) -> AvbToolResult:
        result = super().extract_public_key(key_path, output_path)
        if result.returncode == 0:
            output_path.write_bytes(b"fake public key")
        return result


def _setup_key_dir(tmp_path: Path) -> WorkspacePaths:
    """Create a workspace whose literal ``current`` profile owns a key store."""
    ws = WorkspacePaths.discover(tmp_path)
    ws.ensure_dirs()
    key_dir = ws.resolve_key_dir("current")
    key_dir.mkdir(parents=True, exist_ok=True)
    # A profile.json makes ``current`` resolvable as a literal profile id
    # (ProfileRepository.list_profiles only counts complete profiles).
    profile_json = ws.resolve_profile_dir("current") / "profile.json"
    if not profile_json.exists():
        profile_json.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "profile": {"id": "current", "name": "Current"},
                    "key_store_path": "keys",
                    "partitions": {},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return ws


def _key_dir(ws: WorkspacePaths, profile_id: str = "current") -> Path:
    return ws.resolve_key_dir(profile_id)


def _write_manifest(key_dir: Path, manifest: dict[str, dict[str, str]]) -> None:
    (key_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _read_manifest(key_dir: Path) -> dict[str, dict[str, str]]:
    return json.loads((key_dir / "manifest.json").read_text(encoding="utf-8"))


class TestKeyDiscoveryUseCase:
    def test_discover_pem_files(self, tmp_path: Path) -> None:
        ws = _setup_key_dir(tmp_path)
        key_dir = ws.resolve_key_dir("current")
        (key_dir / "testkey.pem").write_text("fake key 1")
        (key_dir / "release.pem").write_text("fake key 2")

        uc = KeyDiscoveryUseCase(ws)
        result = uc.execute(KeyDiscoveryRequest(profile_id="current"))

        assert result.discovered_count == 2
        assert len(result.manifest_entries) == 2
        # Manifest should be written
        assert (key_dir / "manifest.json").exists()

    def test_discover_empty_directory(self, tmp_path: Path) -> None:
        ws = _setup_key_dir(tmp_path)
        uc = KeyDiscoveryUseCase(ws)
        result = uc.execute(KeyDiscoveryRequest(profile_id="current"))

        assert result.discovered_count == 0
        assert len(result.manifest_entries) == 0

    def test_discover_nonexistent_directory(self, tmp_path: Path) -> None:
        ws = WorkspacePaths.discover(tmp_path)
        ws.ensure_dirs()
        uc = KeyDiscoveryUseCase(ws)
        result = uc.execute(KeyDiscoveryRequest(profile_id="nonexistent"))

        assert any(i.error_code == "keys.directory_not_found" for i in result.issues)
        issue = next(i for i in result.issues if i.error_code == "keys.directory_not_found")
        # The resolved profile id and the key directory must be discoverable
        # from the message (``--profile`` omitted resolves to the active one).
        assert "nonexistent" in issue.message
        assert str(ws.resolve_key_dir("nonexistent")) in issue.message


class TestKeyDiscoveryMergeSemantics:
    """``discover`` merges into the on-disk manifest by default."""

    def test_merge_keeps_public_key_of_unchanged_entry_and_adds_new(self, tmp_path: Path) -> None:
        ws = _setup_key_dir(tmp_path)
        key_dir = _key_dir(ws)
        (key_dir / "testkey_rsa4096.pem").write_text("fake rsa4096")
        (key_dir / "other.pem").write_text("fake other")
        _write_manifest(
            key_dir,
            {
                "testkey_rsa4096": {
                    "private_key": "testkey_rsa4096.pem",
                    "public_key": "testkey_rsa4096_pub.bin",
                    "public_key_sha1": "cd2c1e5e3c4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b",
                }
            },
        )

        result = KeyDiscoveryUseCase(ws).execute(KeyDiscoveryRequest(profile_id="current"))

        assert result.issues == ()
        assert result.merged is True
        assert result.discovered_count == 2
        assert sorted(result.manifest_entries) == [
            ("other", "other.pem"),
            ("testkey_rsa4096", "testkey_rsa4096.pem"),
        ]

        manifest = _read_manifest(key_dir)
        assert manifest["testkey_rsa4096"] == {
            "private_key": "testkey_rsa4096.pem",
            "public_key": "testkey_rsa4096_pub.bin",
            "public_key_sha1": "cd2c1e5e3c4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b",
        }
        assert manifest["other"] == {"private_key": "other.pem"}

    def test_merge_drops_public_key_when_private_key_filename_changed(self, tmp_path: Path) -> None:
        ws = _setup_key_dir(tmp_path)
        key_dir = _key_dir(ws)
        # The manifest caches a public key produced from the OLD filename,
        # but the key_id still maps to it.
        (key_dir / "testkey_rsa4096.pem").write_text("fake renamed")
        _write_manifest(
            key_dir,
            {
                "testkey_rsa4096": {
                    "private_key": "old_name.pem",
                    "public_key": "old_name.pem.bin",
                    "public_key_sha1": "deadbeef",
                }
            },
        )

        result = KeyDiscoveryUseCase(ws).execute(KeyDiscoveryRequest(profile_id="current"))

        assert result.issues == ()
        manifest = _read_manifest(key_dir)
        # Same key_id, different filename -> the cache belongs to another
        # file and must be dropped.
        assert manifest["testkey_rsa4096"] == {"private_key": "testkey_rsa4096.pem"}

    def test_merge_adds_a_renamed_pem_under_its_new_key_id(self, tmp_path: Path) -> None:
        """A renamed .pem registers a new entry; the stale one is retained."""
        ws = _setup_key_dir(tmp_path)
        key_dir = _key_dir(ws)
        (key_dir / "renamed.pem").write_text("fake renamed")
        _write_manifest(
            key_dir,
            {
                "testkey_rsa4096": {
                    "private_key": "old_name.pem",
                    "public_key": "old_name.pem.bin",
                    "public_key_sha1": "deadbeef",
                }
            },
        )

        result = KeyDiscoveryUseCase(ws).execute(KeyDiscoveryRequest(profile_id="current"))

        assert result.manifest_entries == (("renamed", "renamed.pem"),)
        manifest = _read_manifest(key_dir)
        assert manifest["renamed"] == {"private_key": "renamed.pem"}
        # The old entry's .pem is gone: it stays untouched (public key kept).
        assert manifest["testkey_rsa4096"]["public_key"] == "old_name.pem.bin"

    def test_merge_retains_entries_without_a_pem_on_disk(self, tmp_path: Path) -> None:
        ws = _setup_key_dir(tmp_path)
        key_dir = _key_dir(ws)
        (key_dir / "kept.pem").write_text("fake kept")
        _write_manifest(
            key_dir,
            {
                "kept": {"private_key": "kept.pem", "public_key": "kept.pem.bin"},
                "ghost": {"private_key": "ghost.pem", "public_key": "ghost.pem.bin"},
            },
        )

        result = KeyDiscoveryUseCase(ws).execute(KeyDiscoveryRequest(profile_id="current"))

        assert result.retained_count == 1
        manifest = _read_manifest(key_dir)
        assert set(manifest) == {"kept", "ghost"}
        assert manifest["ghost"]["public_key"] == "ghost.pem.bin"

    def test_replace_drops_public_keys_and_absent_entries(self, tmp_path: Path) -> None:
        ws = _setup_key_dir(tmp_path)
        key_dir = _key_dir(ws)
        (key_dir / "testkey_rsa4096.pem").write_text("fake rsa4096")
        _write_manifest(
            key_dir,
            {
                "testkey_rsa4096": {
                    "private_key": "testkey_rsa4096.pem",
                    "public_key": "testkey_rsa4096_pub.bin",
                    "public_key_sha1": "cd2c1e5e",
                },
                "ghost": {"private_key": "ghost.pem", "public_key": "ghost.pem.bin"},
            },
        )

        result = KeyDiscoveryUseCase(ws).execute(
            KeyDiscoveryRequest(profile_id="current", merge=False)
        )

        assert result.merged is False
        assert result.retained_count == 0
        manifest = _read_manifest(key_dir)
        assert manifest == {"testkey_rsa4096": {"private_key": "testkey_rsa4096.pem"}}

    def test_replace_with_no_pem_leaves_the_manifest_untouched(self, tmp_path: Path) -> None:
        """Replace keeps the historical "only write a non-empty manifest" rule."""
        ws = _setup_key_dir(tmp_path)
        key_dir = _key_dir(ws)
        _write_manifest(key_dir, {"ghost": {"private_key": "ghost.pem"}})

        KeyDiscoveryUseCase(ws).execute(KeyDiscoveryRequest(profile_id="current", merge=False))

        assert _read_manifest(key_dir) == {"ghost": {"private_key": "ghost.pem"}}

    def test_merge_does_not_rewrite_an_unchanged_manifest(self, tmp_path: Path) -> None:
        ws = _setup_key_dir(tmp_path)
        key_dir = _key_dir(ws)
        (key_dir / "kept.pem").write_text("fake kept")
        _write_manifest(
            key_dir,
            {"kept": {"private_key": "kept.pem", "public_key": "kept.pem.bin"}},
        )
        manifest_path = key_dir / "manifest.json"
        before = manifest_path.stat().st_mtime_ns

        KeyDiscoveryUseCase(ws).execute(KeyDiscoveryRequest(profile_id="current"))

        assert manifest_path.stat().st_mtime_ns == before


class TestKeyEnsurePublicUseCase:
    def test_extracts_missing_public_key_and_reports_it(self, tmp_path: Path) -> None:
        ws = _setup_key_dir(tmp_path)
        key_dir = _key_dir(ws)
        (key_dir / "testkey_rsa4096.pem").write_text("fake rsa4096")
        _write_manifest(key_dir, {"testkey_rsa4096": {"private_key": "testkey_rsa4096.pem"}})
        fake = WritingFakeAvbTool()

        result = KeyEnsurePublicUseCase(ws, fake).execute(KeyEnsurePublicRequest())

        assert result.issues == ()
        assert result.extracted == (("testkey_rsa4096", "testkey_rsa4096.pem.bin"),)
        assert result.skipped == ()
        assert [call[0] for call in fake.calls] == ["extract_public_key"]
        assert fake.calls[0][1] == (
            key_dir / "testkey_rsa4096.pem",
            key_dir / "testkey_rsa4096.pem.bin",
        )
        assert _read_manifest(key_dir)["testkey_rsa4096"]["public_key"] == (
            "testkey_rsa4096.pem.bin"
        )

    def test_does_not_call_avbtool_when_public_key_exists(self, tmp_path: Path) -> None:
        ws = _setup_key_dir(tmp_path)
        key_dir = _key_dir(ws)
        (key_dir / "testkey_rsa4096.pem").write_text("fake rsa4096")
        (key_dir / "testkey_rsa4096.pem.bin").write_bytes(b"fake public key")
        _write_manifest(
            key_dir,
            {"testkey_rsa4096": {"private_key": "testkey_rsa4096.pem"}},
        )
        fake = WritingFakeAvbTool()

        result = KeyEnsurePublicUseCase(ws, fake).execute(KeyEnsurePublicRequest())

        assert result.issues == ()
        assert result.extracted == ()
        assert fake.calls == []
        assert _read_manifest(key_dir)["testkey_rsa4096"]["public_key"] == (
            "testkey_rsa4096.pem.bin"
        )

    def test_missing_private_key_is_skipped_and_reported(self, tmp_path: Path) -> None:
        ws = _setup_key_dir(tmp_path)
        key_dir = _key_dir(ws)
        (key_dir / "present.pem").write_text("fake present")
        _write_manifest(
            key_dir,
            {
                "present": {"private_key": "present.pem"},
                "gone": {"private_key": "gone.pem"},
                "empty": {"private_key": ""},
            },
        )
        fake = WritingFakeAvbTool()

        result = KeyEnsurePublicUseCase(ws, fake).execute(KeyEnsurePublicRequest())

        assert result.skipped == ("gone", "empty")
        assert result.extracted == (("present", "present.pem.bin"),)
        codes = [i.error_code for i in result.issues]
        assert codes == ["keys.private_key_missing", "keys.private_key_missing"]
        assert "gone" in result.issues[0].message

    def test_extract_failure_is_reported_and_not_registered(self, tmp_path: Path) -> None:
        from avbpowertool.application.ports import AvbToolResult

        ws = _setup_key_dir(tmp_path)
        key_dir = _key_dir(ws)
        (key_dir / "broken.pem").write_text("fake broken")
        _write_manifest(key_dir, {"broken": {"private_key": "broken.pem"}})
        fake = FakeAvbTool(
            {"extract_public_key": AvbToolResult(1, "", "boom", "extract_public_key")}
        )

        result = KeyEnsurePublicUseCase(ws, fake).execute(KeyEnsurePublicRequest())

        assert result.extracted == ()
        assert [i.error_code for i in result.issues] == ["keys.public_key_extract_failed"]
        assert "public_key" not in _read_manifest(key_dir)["broken"]

    def test_unknown_profile_reports_directory_not_found(self, tmp_path: Path) -> None:
        ws = WorkspacePaths.discover(tmp_path)
        ws.ensure_dirs()

        result = KeyEnsurePublicUseCase(ws, FakeAvbTool()).execute(
            KeyEnsurePublicRequest(profile_id="nonexistent")
        )

        assert [i.error_code for i in result.issues] == ["keys.directory_not_found"]
        assert "nonexistent" in result.issues[0].message
