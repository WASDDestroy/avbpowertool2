"""Integration tests for profile management use cases."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from avbpowertool.application.commands import (
    ConfigEditRequest,
    ProfileActivateRequest,
    ProfileListRequest,
    ProfileRenameRequest,
)
from avbpowertool.application.services.manage_configs import ConfigEditUseCase
from avbpowertool.application.services.manage_profiles import (
    ProfileActivateUseCase,
    ProfileListUseCase,
    ProfileRenameUseCase,
)
from avbpowertool.domain.models import (
    AvbProfile,
    DescriptorType,
    PartitionConfig,
    SigningAlgorithm,
)
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.persistence.profile_codec import encode_profile
from avbpowertool.infrastructure.persistence.profile_repository import ProfileRepository


def _setup_profiles(tmp_path: Path) -> WorkspacePaths:
    ws = WorkspacePaths.discover(tmp_path)
    ws.ensure_dirs()
    for pid, name in [("alpha", "Alpha"), ("beta", "Beta")]:
        profile_dir = ws.resolve_profile_dir(pid)
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / "keys").mkdir()
        data = encode_profile(AvbProfile(id=pid, name=name))
        (profile_dir / "profile.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    return ws


# ---------------------------------------------------------------------------
# Rename helpers
# ---------------------------------------------------------------------------

#: Content of ``keys/`` used to prove a rename never touches the key store.
_KEY_FILES: dict[str, bytes] = {
    "manifest.json": b'{"testkey_rsa4096": {"private_key": "testkey_rsa4096.pem"}}',
    "testkey_rsa4096.pem": b"-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n",
    "testkey_rsa4096.pem.bin": b"\x00\x01\x02public-key-bytes",
}


def _boot_partition() -> PartitionConfig:
    return PartitionConfig(
        image="boot.img",
        descriptor=DescriptorType.HASH,
        algorithm=SigningAlgorithm.SHA256_RSA4096,
        key_id="testkey_rsa4096",
        partition_name="boot",
        rollback_index=3,
        salt="a1b2c3d4e5f6",
        flags=1,
    )


def _setup_ws(tmp_path: Path) -> WorkspacePaths:
    ws = WorkspacePaths.discover(tmp_path)
    ws.ensure_dirs()
    return ws


def _write_profile(
    ws: WorkspacePaths,
    profile_id: str,
    *,
    name: str | None = None,
    embedded_id: str | None = None,
    partitions: dict[str, PartitionConfig] | None = None,
) -> Path:
    """Create ``profiles/<profile_id>/`` with keys and an optional stale id."""
    profile_dir = ws.resolve_profile_dir(profile_id)
    key_dir = profile_dir / "keys"
    key_dir.mkdir(parents=True, exist_ok=True)
    data = encode_profile(
        AvbProfile(
            id=embedded_id if embedded_id is not None else profile_id,
            name=name if name is not None else profile_id,
            partitions=partitions if partitions is not None else {},
        )
    )
    (profile_dir / "profile.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    for filename, payload in _KEY_FILES.items():
        (key_dir / filename).write_bytes(payload)
    return profile_dir


def _read_profile_json(ws: WorkspacePaths, profile_id: str) -> dict[str, Any]:
    path = ws.resolve_profile_dir(profile_id) / "profile.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _profile_meta(ws: WorkspacePaths, profile_id: str) -> dict[str, Any]:
    meta = _read_profile_json(ws, profile_id)["profile"]
    assert isinstance(meta, dict)
    return meta


class TestProfileListUseCase:
    def test_list_profiles(self, tmp_path: Path) -> None:
        ws = _setup_profiles(tmp_path)
        uc = ProfileListUseCase(ws)
        result = uc.execute(ProfileListRequest())
        assert len(result.profiles) == 2
        ids = [p.profile_id for p in result.profiles]
        assert "alpha" in ids
        assert "beta" in ids

    def test_list_with_active(self, tmp_path: Path) -> None:
        ws = _setup_profiles(tmp_path)
        repo = ProfileRepository(ws)
        repo.activate("alpha")

        uc = ProfileListUseCase(ws)
        result = uc.execute(ProfileListRequest())
        assert result.active_profile_id == "alpha"
        active = [p for p in result.profiles if p.is_active]
        assert len(active) == 1
        assert active[0].profile_id == "alpha"

    def test_list_empty(self, tmp_path: Path) -> None:
        ws = WorkspacePaths.discover(tmp_path)
        ws.ensure_dirs()
        uc = ProfileListUseCase(ws)
        result = uc.execute(ProfileListRequest())
        assert len(result.profiles) == 0


class TestProfileActivateUseCase:
    def test_activate_existing(self, tmp_path: Path) -> None:
        ws = _setup_profiles(tmp_path)
        uc = ProfileActivateUseCase(ws)
        result = uc.execute(ProfileActivateRequest(profile_id="alpha"))
        assert len(result.issues) == 0

        repo = ProfileRepository(ws)
        assert repo.get_active_profile_id() == "alpha"

    def test_activate_nonexistent(self, tmp_path: Path) -> None:
        ws = _setup_profiles(tmp_path)
        uc = ProfileActivateUseCase(ws)
        result = uc.execute(ProfileActivateRequest(profile_id="nonexistent"))
        assert any(i.error_code == "config.not_found" for i in result.issues)

    def test_switch_active(self, tmp_path: Path) -> None:
        ws = _setup_profiles(tmp_path)
        uc = ProfileActivateUseCase(ws)
        uc.execute(ProfileActivateRequest(profile_id="alpha"))
        uc.execute(ProfileActivateRequest(profile_id="beta"))

        repo = ProfileRepository(ws)
        assert repo.get_active_profile_id() == "beta"


class TestProfileRenameUseCase:
    def test_rename_moves_directory_and_embedded_id(self, tmp_path: Path) -> None:
        ws = _setup_ws(tmp_path)
        _write_profile(ws, "alpha", name="Alpha", partitions={"boot": _boot_partition()})

        result = ProfileRenameUseCase(ws).execute(ProfileRenameRequest("alpha", "gamma"))

        assert result.issues == ()
        assert result.old_profile_id == "alpha"
        assert result.profile_id == "gamma"
        assert result.renamed is True
        assert result.name_changed is False
        assert not ws.resolve_profile_dir("alpha").exists()
        assert ws.resolve_profile_dir("gamma").is_dir()

        meta = _profile_meta(ws, "gamma")
        assert meta["id"] == "gamma"
        assert meta["name"] == "Alpha"

    def test_rename_keeps_partitions_and_key_store(self, tmp_path: Path) -> None:
        ws = _setup_ws(tmp_path)
        _write_profile(ws, "alpha", name="Alpha", partitions={"boot": _boot_partition()})

        ProfileRenameUseCase(ws).execute(ProfileRenameRequest("alpha", "gamma"))

        profile = ProfileRepository(ws).load("gamma")
        assert profile.partitions == {"boot": _boot_partition()}

        key_dir = ws.resolve_key_dir("gamma")
        for filename, payload in _KEY_FILES.items():
            assert (key_dir / filename).read_bytes() == payload

    def test_name_only_change_keeps_directory(self, tmp_path: Path) -> None:
        ws = _setup_ws(tmp_path)
        _write_profile(ws, "alpha", name="Alpha")

        result = ProfileRenameUseCase(ws).execute(
            ProfileRenameRequest("alpha", "alpha", new_name="New Alpha")
        )

        assert result.issues == ()
        assert result.renamed is False
        assert result.name_changed is True
        assert _profile_meta(ws, "alpha")["name"] == "New Alpha"
        assert _profile_meta(ws, "alpha")["id"] == "alpha"

    def test_name_change_with_rename(self, tmp_path: Path) -> None:
        ws = _setup_ws(tmp_path)
        _write_profile(ws, "alpha", name="Alpha")

        result = ProfileRenameUseCase(ws).execute(
            ProfileRenameRequest("alpha", "gamma", new_name="Gamma Device")
        )

        assert result.issues == ()
        assert result.renamed is True
        assert result.name_changed is True
        meta = _profile_meta(ws, "gamma")
        assert meta["id"] == "gamma"
        assert meta["name"] == "Gamma Device"

    def test_same_id_without_name_is_a_noop(self, tmp_path: Path) -> None:
        ws = _setup_ws(tmp_path)
        _write_profile(ws, "alpha", name="Alpha")
        profile_path = ws.resolve_profile_dir("alpha") / "profile.json"
        before = profile_path.read_bytes()

        result = ProfileRenameUseCase(ws).execute(ProfileRenameRequest("alpha", "alpha"))

        assert result.issues == ()
        assert result.renamed is False
        assert result.name_changed is False
        assert profile_path.read_bytes() == before

    def test_active_profile_follows_rename(self, tmp_path: Path) -> None:
        ws = _setup_ws(tmp_path)
        _write_profile(ws, "alpha", name="Alpha")
        repo = ProfileRepository(ws)
        repo.activate("alpha")

        result = ProfileRenameUseCase(ws).execute(ProfileRenameRequest("alpha", "gamma"))

        assert result.issues == ()
        assert repo.get_active_profile_id() == "gamma"

    def test_other_active_profile_is_untouched(self, tmp_path: Path) -> None:
        ws = _setup_ws(tmp_path)
        _write_profile(ws, "alpha", name="Alpha")
        _write_profile(ws, "beta", name="Beta")
        repo = ProfileRepository(ws)
        repo.activate("beta")

        result = ProfileRenameUseCase(ws).execute(ProfileRenameRequest("alpha", "gamma"))

        assert result.issues == ()
        assert repo.get_active_profile_id() == "beta"

    def test_existing_target_is_refused(self, tmp_path: Path) -> None:
        ws = _setup_ws(tmp_path)
        _write_profile(ws, "alpha", name="Alpha")
        _write_profile(ws, "beta", name="Beta")
        alpha_before = (ws.resolve_profile_dir("alpha") / "profile.json").read_bytes()
        beta_before = (ws.resolve_profile_dir("beta") / "profile.json").read_bytes()

        result = ProfileRenameUseCase(ws).execute(ProfileRenameRequest("alpha", "beta"))

        assert [i.error_code for i in result.issues] == ["config.profile_exists"]
        assert result.renamed is False
        assert (ws.resolve_profile_dir("alpha") / "profile.json").read_bytes() == alpha_before
        assert (ws.resolve_profile_dir("beta") / "profile.json").read_bytes() == beta_before

    def test_missing_profile_is_not_found(self, tmp_path: Path) -> None:
        ws = _setup_ws(tmp_path)

        result = ProfileRenameUseCase(ws).execute(ProfileRenameRequest("missing", "gamma"))

        assert [i.error_code for i in result.issues] == ["config.not_found"]
        assert result.renamed is False
        assert not ws.resolve_profile_dir("gamma").exists()

    def test_directory_without_profile_json_is_not_found(self, tmp_path: Path) -> None:
        ws = _setup_ws(tmp_path)
        ws.resolve_profile_dir("ghost").mkdir(parents=True)

        result = ProfileRenameUseCase(ws).execute(ProfileRenameRequest("ghost", "gamma"))

        assert [i.error_code for i in result.issues] == ["config.not_found"]
        assert ws.resolve_profile_dir("ghost").is_dir()
        assert not ws.resolve_profile_dir("gamma").exists()

    def test_invalid_new_id_is_refused(self, tmp_path: Path) -> None:
        ws = _setup_ws(tmp_path)
        _write_profile(ws, "alpha", name="Alpha")
        alpha_before = (ws.resolve_profile_dir("alpha") / "profile.json").read_bytes()

        result = ProfileRenameUseCase(ws).execute(ProfileRenameRequest("alpha", "bad id!"))

        assert [i.error_code for i in result.issues] == ["config.invalid_profile_id"]
        assert result.profile_id == "bad id!"
        assert result.renamed is False
        assert (ws.resolve_profile_dir("alpha") / "profile.json").read_bytes() == alpha_before
        assert not ws.resolve_profile_dir("bad_id_").exists()

    def test_dirty_embedded_id_is_repaired_and_editable(self, tmp_path: Path) -> None:
        """A directory whose embedded id disagrees is repaired by the rename."""
        ws = _setup_ws(tmp_path)
        _write_profile(
            ws,
            "alpha",
            name="Alpha",
            embedded_id="beta",
            partitions={"boot": _boot_partition()},
        )

        result = ProfileRenameUseCase(ws).execute(ProfileRenameRequest("alpha", "gamma"))

        assert result.issues == ()
        assert result.renamed is True
        assert _profile_meta(ws, "gamma")["id"] == "gamma"
        assert not ws.resolve_profile_dir("alpha").exists()

        # The repaired profile is editable again: no profile_id_mismatch.
        edit = ConfigEditUseCase(ws).execute(
            ConfigEditRequest(profile_id="gamma", partition_name="boot", updates={"flags": "7"})
        )
        assert edit.issues == ()
        assert ProfileRepository(ws).load("gamma").partitions["boot"].flags == 7

    def test_same_id_repairs_dirty_embedded_id(self, tmp_path: Path) -> None:
        ws = _setup_ws(tmp_path)
        _write_profile(ws, "alpha", name="Alpha", embedded_id="beta")

        result = ProfileRenameUseCase(ws).execute(ProfileRenameRequest("alpha", "alpha"))

        assert result.issues == ()
        assert result.renamed is False
        assert result.name_changed is False
        assert _profile_meta(ws, "alpha")["id"] == "alpha"
        assert _profile_meta(ws, "alpha")["name"] == "Alpha"
