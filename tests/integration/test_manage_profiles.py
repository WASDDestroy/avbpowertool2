"""Integration tests for profile management use cases."""

from __future__ import annotations

import json
from pathlib import Path

from avbpowertool.application.commands import (
    ProfileActivateRequest,
    ProfileListRequest,
)
from avbpowertool.application.services.manage_profiles import (
    ProfileActivateUseCase,
    ProfileListUseCase,
)
from avbpowertool.domain.models import AvbProfile
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
