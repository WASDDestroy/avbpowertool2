"""Unit tests for ``CheckChainsUseCase`` (``config check-chains``).

Every test builds its own workspace under ``tmp_path``: the real
``profiles/``, ``Keys/`` and ``Images/`` directories are never touched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from avbpowertool.application.commands import CheckChainsRequest
from avbpowertool.application.ports import AvbToolResult
from avbpowertool.application.services.check_chains import (
    CheckChainsUseCase,
    parse_chain_entry,
)
from avbpowertool.domain.models import (
    AvbProfile,
    DescriptorType,
    OperationIssue,
    PartitionConfig,
    SigningAlgorithm,
)
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.persistence.profile_codec import encode_profile

from tests.conftest import FakeAvbTool

PUBLIC_KEY_4096 = b"public key of the 4096 test key"
PUBLIC_KEY_2048 = b"public key of the 2048 test key"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _workspace(tmp_path: Path) -> WorkspacePaths:
    ws = WorkspacePaths.discover(tmp_path)
    ws.ensure_dirs()
    return ws


def _partition(
    name: str,
    *,
    descriptor: DescriptorType = DescriptorType.HASH,
    algorithm: SigningAlgorithm = SigningAlgorithm.SHA256_RSA4096,
    key_id: str = "k4096",
    chain_partitions: tuple[str, ...] = (),
) -> PartitionConfig:
    return PartitionConfig(
        image=f"{name}.img",
        descriptor=descriptor,
        algorithm=algorithm,
        key_id=key_id,
        partition_name=name,
        chain_partitions=chain_partitions,
    )


def _write_profile(
    ws: WorkspacePaths, partitions: dict[str, PartitionConfig], profile_id: str = "test"
) -> Path:
    profile_dir = ws.resolve_profile_dir(profile_id)
    key_dir = profile_dir / "keys"
    key_dir.mkdir(parents=True, exist_ok=True)
    profile_json = profile_dir / "profile.json"
    profile_json.write_text(
        json.dumps(encode_profile(AvbProfile(id=profile_id, name="Test", partitions=partitions))),
        encoding="utf-8",
    )
    return profile_json


def _write_keys(
    ws: WorkspacePaths,
    manifest: dict[str, dict[str, str]],
    blobs: dict[str, bytes],
    profile_id: str = "test",
) -> Path:
    """Write ``manifest.json`` plus the named key-store files."""
    key_dir = ws.resolve_key_dir(profile_id)
    key_dir.mkdir(parents=True, exist_ok=True)
    (key_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for name, content in blobs.items():
        (key_dir / name).write_bytes(content)
    return key_dir


def _consistent_manifest() -> dict[str, dict[str, str]]:
    return {
        "k4096": {"private_key": "k4096.pem", "public_key": "k4096.pem.bin"},
        "k2048": {"private_key": "k2048.pem", "public_key": "k2048.pem.bin"},
    }


def _consistent_blobs() -> dict[str, bytes]:
    return {
        "k4096.pem": b"private 4096",
        "k4096.pem.bin": PUBLIC_KEY_4096,
        "k2048.pem": b"private 2048",
        "k2048.pem.bin": PUBLIC_KEY_2048,
    }


def _consistent_profile(chain: str = "boot:3:k4096.pem.bin") -> dict[str, PartitionConfig]:
    return {
        "boot": _partition("boot"),
        "vbmeta": _partition(
            "vbmeta",
            descriptor=DescriptorType.VBMETA,
            chain_partitions=(chain,),
        ),
    }


class _ExtractingAvbTool(FakeAvbTool):
    """FakeAvbTool that really writes the extracted public-key blob."""

    def __init__(self, blob: bytes = PUBLIC_KEY_4096) -> None:
        super().__init__()
        self.blob = blob

    def extract_public_key(self, key_path: Path, output_path: Path) -> AvbToolResult:
        self.calls.append(("extract_public_key", (key_path, output_path), {}))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(self.blob)
        return AvbToolResult(0, "", "", "extract_public_key")


def _codes(issues: tuple[OperationIssue, ...]) -> list[str]:
    return [i.error_code for i in issues]


# ---------------------------------------------------------------------------
# parse_chain_entry
# ---------------------------------------------------------------------------


class TestParseChainEntry:
    @pytest.mark.parametrize(
        "entry", ["boot", "boot:1", "boot:1:", ":1:k.bin", "boot:notanint:k.bin"]
    )
    def test_malformed(self, entry: str) -> None:
        assert parse_chain_entry(entry) is None

    @pytest.mark.parametrize("entry", ["boot:0:k.bin", "boot:-1:k.bin"])
    def test_slot_below_one(self, entry: str) -> None:
        assert parse_chain_entry(entry) is None

    def test_well_formed(self) -> None:
        assert parse_chain_entry("boot:3:k.bin") == ("boot", 3, "k.bin")

    def test_keeps_colons_of_an_absolute_key_path(self) -> None:
        assert parse_chain_entry("boot:3:C:\\keys\\k.bin") == ("boot", 3, "C:\\keys\\k.bin")


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


class TestCheckChainsHappyPath:
    def test_consistent_chain_reports_nothing(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        _write_profile(ws, _consistent_profile())
        _write_keys(ws, _consistent_manifest(), _consistent_blobs())

        result = CheckChainsUseCase(ws, FakeAvbTool()).execute(
            CheckChainsRequest(profile_id="test")
        )

        assert result.profile_id == "test"
        assert result.checked == 1
        assert result.issues == ()
        assert [e.ok for e in result.entries] == [True]

    def test_no_chain_entries_is_clean(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        _write_profile(ws, {"boot": _partition("boot")})
        _write_keys(ws, _consistent_manifest(), _consistent_blobs())

        result = CheckChainsUseCase(ws, FakeAvbTool()).execute(
            CheckChainsRequest(profile_id="test")
        )

        assert result.checked == 0
        assert result.issues == ()
        assert result.entries == ()

    def test_absolute_key_file_is_used_as_is(self, tmp_path: Path) -> None:
        external = tmp_path / "external" / "k4096.bin"
        external.parent.mkdir()
        external.write_bytes(PUBLIC_KEY_4096)
        ws = _workspace(tmp_path)
        _write_profile(ws, _consistent_profile(chain=f"boot:3:{external}"))
        _write_keys(ws, _consistent_manifest(), _consistent_blobs())

        result = CheckChainsUseCase(ws, FakeAvbTool()).execute(
            CheckChainsRequest(profile_id="test")
        )

        assert result.issues == ()
        assert result.checked == 1

    def test_unknown_profile(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        _write_profile(ws, _consistent_profile())

        result = CheckChainsUseCase(ws, FakeAvbTool()).execute(
            CheckChainsRequest(profile_id="nope")
        )

        assert _codes(result.issues) == ["config.not_found"]
        assert result.checked == 0


# ---------------------------------------------------------------------------
# Individual failures
# ---------------------------------------------------------------------------


class TestCheckChainsFailures:
    def test_key_mismatch_is_reported(self, tmp_path: Path) -> None:
        """The real tb710fu shape: chain points at the 2048 key, partition uses 4096."""
        ws = _workspace(tmp_path)
        _write_profile(ws, _consistent_profile(chain="boot:3:k2048.pem.bin"))
        _write_keys(ws, _consistent_manifest(), _consistent_blobs())

        result = CheckChainsUseCase(ws, FakeAvbTool()).execute(
            CheckChainsRequest(profile_id="test")
        )

        assert _codes(result.issues) == ["chain.key_mismatch"]
        message = result.issues[0].message
        assert "boot:3:k2048.pem.bin" in message
        assert "k4096" in message  # the key id of the chained partition
        assert "k2048.pem.bin" in message
        # Both sha1 values are part of the message.
        import hashlib

        assert hashlib.sha1(PUBLIC_KEY_2048).hexdigest() in message
        assert hashlib.sha1(PUBLIC_KEY_4096).hexdigest() in message
        assert [e.ok for e in result.entries] == [False]

    def test_chained_partition_missing_from_profile(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        _write_profile(ws, _consistent_profile(chain="recovery:1:k4096.pem.bin"))
        _write_keys(ws, _consistent_manifest(), _consistent_blobs())

        result = CheckChainsUseCase(ws, FakeAvbTool()).execute(
            CheckChainsRequest(profile_id="test")
        )

        assert _codes(result.issues) == ["config.missing_included_partition"]
        assert "recovery" in result.issues[0].message

    def test_key_file_missing_from_key_store(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        _write_profile(ws, _consistent_profile(chain="boot:3:absent.pem.bin"))
        _write_keys(ws, _consistent_manifest(), _consistent_blobs())

        result = CheckChainsUseCase(ws, FakeAvbTool()).execute(
            CheckChainsRequest(profile_id="test")
        )

        assert _codes(result.issues) == ["chain.key_file_missing"]
        assert "absent.pem.bin" in result.issues[0].message

    def test_relative_key_file_resolves_against_the_key_dir(self, tmp_path: Path) -> None:
        """A relative key file living outside keys/ is not found."""
        outside = tmp_path / "k4096.pem.bin"
        outside.write_bytes(PUBLIC_KEY_4096)
        ws = _workspace(tmp_path)
        _write_profile(ws, _consistent_profile())
        _write_keys(ws, _consistent_manifest(), _consistent_blobs())
        (ws.resolve_key_dir("test") / "k4096.pem.bin").unlink()

        result = CheckChainsUseCase(ws, FakeAvbTool()).execute(
            CheckChainsRequest(profile_id="test")
        )

        assert _codes(result.issues) == ["chain.key_file_missing"]

    @pytest.mark.parametrize("entry", ["boot:notanint:k.bin", "boot", "boot:1:", "boot:0:k.bin"])
    def test_malformed_entries(self, tmp_path: Path, entry: str) -> None:
        ws = _workspace(tmp_path)
        _write_profile(ws, _consistent_profile(chain=entry))
        _write_keys(ws, _consistent_manifest(), _consistent_blobs())

        result = CheckChainsUseCase(ws, FakeAvbTool()).execute(
            CheckChainsRequest(profile_id="test")
        )

        assert _codes(result.issues) == ["chain.malformed_entry"]
        assert result.checked == 1

    def test_unsigned_chained_partition(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        partitions = _consistent_profile()
        partitions["boot"] = _partition("boot", algorithm=SigningAlgorithm.NONE, key_id="k4096")
        _write_profile(ws, partitions)
        _write_keys(ws, _consistent_manifest(), _consistent_blobs())

        result = CheckChainsUseCase(ws, FakeAvbTool()).execute(
            CheckChainsRequest(profile_id="test")
        )

        assert _codes(result.issues) == ["chain.chained_partition_unsigned"]
        assert "unsigned" in result.issues[0].message

    def test_key_id_absent_from_manifest(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        _write_profile(ws, _consistent_profile())
        manifest = _consistent_manifest()
        _write_keys(ws, {"k2048": manifest["k2048"]}, _consistent_blobs())

        result = CheckChainsUseCase(ws, FakeAvbTool()).execute(
            CheckChainsRequest(profile_id="test")
        )

        assert _codes(result.issues) == ["config.key_missing"]
        assert "k4096" in result.issues[0].message

    def test_every_failure_is_reported_at_once(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        partitions = _consistent_profile()
        partitions["boot"] = _partition("boot")
        partitions["vbmeta"] = _partition(
            "vbmeta",
            descriptor=DescriptorType.VBMETA,
            chain_partitions=(
                "boot:notanint:k.bin",  # malformed
                "recovery:1:k4096.pem.bin",  # not in the profile
                "boot:1:absent.pem.bin",  # key file missing
                "boot:2:k2048.pem.bin",  # key mismatch
            ),
        )
        _write_profile(ws, partitions)
        _write_keys(ws, _consistent_manifest(), _consistent_blobs())

        result = CheckChainsUseCase(ws, FakeAvbTool()).execute(
            CheckChainsRequest(profile_id="test")
        )

        assert result.checked == 4
        assert _codes(result.issues) == [
            "chain.malformed_entry",
            "config.missing_included_partition",
            "chain.key_file_missing",
            "chain.key_mismatch",
        ]
        assert [e.ok for e in result.entries] == [False, False, False, False]

    def test_chain_entries_are_checked_on_every_partition(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        partitions = {
            "boot": _partition("boot"),
            "vbmeta": _partition(
                "vbmeta",
                descriptor=DescriptorType.VBMETA,
                chain_partitions=("boot:1:k4096.pem.bin",),
            ),
            "vbmeta_system": _partition(
                "vbmeta_system",
                descriptor=DescriptorType.VBMETA,
                chain_partitions=("boot:2:k2048.pem.bin",),
            ),
        }
        _write_profile(ws, partitions)
        _write_keys(ws, _consistent_manifest(), _consistent_blobs())

        result = CheckChainsUseCase(ws, FakeAvbTool()).execute(
            CheckChainsRequest(profile_id="test")
        )

        assert result.checked == 2
        assert _codes(result.issues) == ["chain.key_mismatch"]
        assert result.entries[1].partition_name == "vbmeta_system"


# ---------------------------------------------------------------------------
# Public-key extraction (public_key missing from the manifest)
# ---------------------------------------------------------------------------


class TestPublicKeyExtraction:
    def _manifest_without_public_key(self) -> dict[str, dict[str, str]]:
        return {
            "k4096": {"private_key": "k4096.pem"},
            "k2048": {"private_key": "k2048.pem"},
        }

    def test_extracts_into_staging_and_uses_the_result(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        _write_profile(ws, _consistent_profile())
        key_dir = _write_keys(
            ws,
            self._manifest_without_public_key(),
            {
                "k4096.pem": b"private 4096",
                "k4096.pem.bin": PUBLIC_KEY_4096,
                "k2048.pem": b"private 2048",
                "k2048.pem.bin": PUBLIC_KEY_2048,
            },
        )
        before = sorted(p.name for p in key_dir.iterdir())
        tool = _ExtractingAvbTool(blob=PUBLIC_KEY_4096)

        result = CheckChainsUseCase(ws, tool).execute(CheckChainsRequest(profile_id="test"))

        assert result.issues == ()
        assert [call[0] for call in tool.calls] == ["extract_public_key"]
        _name, (key_path, output_path), _kwargs = tool.calls[0]
        assert key_path == key_dir / "k4096.pem"
        assert output_path == ws.staging / "check-chains" / "k4096.pem.bin"
        assert output_path.read_bytes() == PUBLIC_KEY_4096
        # The key store is untouched: the blob went to staging only.
        assert sorted(p.name for p in key_dir.iterdir()) == before
        assert not (key_dir / "k4096.pem.bin.bin").exists()

    def test_extracted_key_that_differs_is_a_mismatch(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        _write_profile(ws, _consistent_profile())
        _write_keys(
            ws,
            self._manifest_without_public_key(),
            {
                "k4096.pem": b"private 4096",
                "k4096.pem.bin": PUBLIC_KEY_2048,
                "k2048.pem": b"private 2048",
            },
        )
        tool = _ExtractingAvbTool(blob=PUBLIC_KEY_4096)

        result = CheckChainsUseCase(ws, tool).execute(CheckChainsRequest(profile_id="test"))

        assert _codes(result.issues) == ["chain.key_mismatch"]
        assert [call[0] for call in tool.calls] == ["extract_public_key"]

    def test_extract_failure_is_reported(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        _write_profile(ws, _consistent_profile())
        _write_keys(
            ws,
            self._manifest_without_public_key(),
            {"k4096.pem.bin": PUBLIC_KEY_4096, "k2048.pem": b"private 2048"},
        )

        # The plain FakeAvbTool never writes the blob -> extraction "fails".
        result = CheckChainsUseCase(ws, FakeAvbTool()).execute(
            CheckChainsRequest(profile_id="test")
        )

        assert _codes(result.issues) == ["keys.public_key_extract_failed"]

    def test_missing_private_key_is_an_extract_failure(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        _write_profile(ws, _consistent_profile())
        _write_keys(ws, self._manifest_without_public_key(), {"k4096.pem.bin": PUBLIC_KEY_4096})

        result = CheckChainsUseCase(ws, FakeAvbTool()).execute(
            CheckChainsRequest(profile_id="test")
        )

        assert _codes(result.issues) == ["keys.public_key_extract_failed"]


# ---------------------------------------------------------------------------
# Read-only guarantee
# ---------------------------------------------------------------------------


class TestReadOnly:
    def test_profile_and_manifest_are_not_rewritten(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        profile_json = _write_profile(ws, _consistent_profile(chain="boot:3:k2048.pem.bin"))
        key_dir = _write_keys(ws, _consistent_manifest(), _consistent_blobs())
        profile_before = profile_json.read_bytes()
        manifest_before = (key_dir / "manifest.json").read_bytes()
        listing_before = sorted(p.name for p in key_dir.iterdir())

        result = CheckChainsUseCase(ws, FakeAvbTool()).execute(
            CheckChainsRequest(profile_id="test")
        )

        assert _codes(result.issues) == ["chain.key_mismatch"]
        assert profile_json.read_bytes() == profile_before
        assert (key_dir / "manifest.json").read_bytes() == manifest_before
        assert sorted(p.name for p in key_dir.iterdir()) == listing_before
