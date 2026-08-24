"""Integration tests for SignImagesUseCase."""

from __future__ import annotations

import json
from pathlib import Path

from avbpowertool.application.commands import SignImagesRequest
from avbpowertool.application.ports import AvbToolResult
from avbpowertool.application.services.sign_images import SignImagesUseCase
from avbpowertool.domain.models import (
    AvbProfile,
    DescriptorType,
    PartitionConfig,
    SigningAlgorithm,
)
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.persistence.profile_codec import encode_profile
from tests.conftest import FakeAvbTool


def _setup_profile(tmp_path: Path) -> WorkspacePaths:
    ws = WorkspacePaths.discover(tmp_path)
    ws.ensure_dirs()

    profile_dir = ws.resolve_profile_dir("current")
    profile_dir.mkdir(parents=True, exist_ok=True)
    key_dir = profile_dir / "keys"
    key_dir.mkdir()

    # Create image files in workspace-level Images/
    (ws.images / "boot.img").write_bytes(b"fake boot image")

    # Create key files
    (key_dir / "testkey.pem").write_text("fake key", encoding="utf-8")
    manifest = {"testkey": {"private_key": "testkey.pem"}}
    (key_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    # Create profile
    profile = AvbProfile(
        id="current",
        name="Current",
        partitions={
            "boot": PartitionConfig(
                image="boot.img",
                descriptor=DescriptorType.HASH,
                algorithm=SigningAlgorithm.SHA256_RSA4096,
                key_id="testkey",
                partition_name="boot",
                rollback_index=0,
                salt="abcdef",
            ),
        },
    )
    (profile_dir / "profile.json").write_text(
        json.dumps(encode_profile(profile), indent=2), encoding="utf-8"
    )

    return ws


class TestSignImagesUseCase:
    def test_dry_run_produces_plan(self, tmp_path: Path) -> None:
        ws = _setup_profile(tmp_path)
        fake_avb = FakeAvbTool(
            {"add_hash_footer": AvbToolResult(0, "", "", "add_hash_footer")}
        )
        uc = SignImagesUseCase(ws, fake_avb)
        result = uc.execute(
            SignImagesRequest(
                image_names=("boot",), profile_id="current", dry_run=True
            )
        )

        assert not result.executed
        assert len(result.plan.steps) == 1
        assert result.plan.steps[0].operation == "add_hash_footer"

    def test_real_signing_executes(self, tmp_path: Path) -> None:
        ws = _setup_profile(tmp_path)
        fake_avb = FakeAvbTool(
            {"add_hash_footer": AvbToolResult(0, "", "", "add_hash_footer")}
        )
        uc = SignImagesUseCase(ws, fake_avb)
        result = uc.execute(
            SignImagesRequest(
                image_names=("boot",), profile_id="current", dry_run=False
            )
        )

        assert result.executed
        assert result.success_count == 1
        assert result.fail_count == 0

    def test_signing_failure_reported(self, tmp_path: Path) -> None:
        ws = _setup_profile(tmp_path)
        fake_avb = FakeAvbTool(
            {"add_hash_footer": AvbToolResult(1, "", "signing failed", "add_hash_footer")}
        )
        uc = SignImagesUseCase(ws, fake_avb)
        result = uc.execute(
            SignImagesRequest(
                image_names=("boot",), profile_id="current", dry_run=False
            )
        )

        assert result.executed
        assert result.success_count == 0
        assert result.fail_count == 1
        assert any(i.error_code == "signing.step_failed" for i in result.issues)

    def test_missing_profile_reports_issue(self, tmp_path: Path) -> None:
        ws = _setup_profile(tmp_path)
        fake_avb = FakeAvbTool()
        uc = SignImagesUseCase(ws, fake_avb)
        result = uc.execute(
            SignImagesRequest(image_names=("boot",), profile_id="nonexistent")
        )

        assert not result.executed
        assert any(i.error_code == "config.not_found" for i in result.issues)

    def test_missing_partition_in_plan(self, tmp_path: Path) -> None:
        ws = _setup_profile(tmp_path)
        fake_avb = FakeAvbTool()
        uc = SignImagesUseCase(ws, fake_avb)
        result = uc.execute(
            SignImagesRequest(
                image_names=("nonexistent",), profile_id="current", dry_run=True
            )
        )

        assert not result.executed
        assert any(i.error_code == "config.partition_missing" for i in result.issues)
