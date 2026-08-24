"""Integration tests for InspectImagesUseCase."""

from __future__ import annotations

from pathlib import Path

from avbpowertool.application.commands import InspectImagesRequest
from avbpowertool.application.ports import AvbToolResult
from avbpowertool.application.services.inspect_images import InspectImagesUseCase
from avbpowertool.domain.models import DescriptorType
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from tests.conftest import FakeAvbTool, FIXTURES_DIR

SAMPLE_HASH = (FIXTURES_DIR / "avbtool_output" / "hash_descriptor.txt").read_text(
    encoding="utf-8"
)
SAMPLE_VBMETA = (FIXTURES_DIR / "avbtool_output" / "vbmeta_no_descriptors.txt").read_text(
    encoding="utf-8"
)
SAMPLE_NO_FOOTER = (
    "usage: avbtool info_image ...\n"
    "avbtool.py: error: Given image does not look like a vbmeta image.\n"
)


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
    return ws


class TestInspectImagesUseCase:
    def test_inspect_hash_image(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        (ws.images / "boot.img").write_bytes(b"fake boot image")

        fake_avb = FakeAvbTool(
            {"inspect_image": AvbToolResult(0, SAMPLE_HASH, "", "info_image")}
        )
        uc = InspectImagesUseCase(ws, fake_avb)
        result = uc.execute(InspectImagesRequest(image_names=("boot",)))

        assert len(result.images) == 1
        img = result.images[0]
        assert img.image_name == "boot"
        assert img.descriptor == DescriptorType.HASH
        assert img.partition_name == "boot"
        assert "cd2c1e5e" in (img.public_key_sha1 or "")
        assert len(result.issues) == 0

    def test_inspect_vbmeta_image(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        (ws.images / "vbmeta.img").write_bytes(b"fake vbmeta")

        fake_avb = FakeAvbTool(
            {"inspect_image": AvbToolResult(0, SAMPLE_VBMETA, "", "info_image")}
        )
        uc = InspectImagesUseCase(ws, fake_avb)
        result = uc.execute(InspectImagesRequest(image_names=("vbmeta",)))

        assert len(result.images) == 1
        assert result.images[0].descriptor == DescriptorType.VBMETA
        assert result.images[0].algorithm == "SHA256_RSA4096"

    def test_inspect_missing_image(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        fake_avb = FakeAvbTool()
        uc = InspectImagesUseCase(ws, fake_avb)
        result = uc.execute(InspectImagesRequest(image_names=("nonexistent",)))

        assert len(result.images) == 0
        assert any(i.error_code == "image.not_found" for i in result.issues)

    def test_inspect_no_vbmeta_structure(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        (ws.images / "raw.img").write_bytes(b"raw image")

        fake_avb = FakeAvbTool(
            {"inspect_image": AvbToolResult(1, "", SAMPLE_NO_FOOTER, "info_image")}
        )
        uc = InspectImagesUseCase(ws, fake_avb)
        result = uc.execute(InspectImagesRequest(image_names=("raw",)))

        assert len(result.images) == 1
        assert result.images[0].descriptor is None
        assert any(i.error_code == "image.no_vbmeta_structure" for i in result.issues)

    def test_inspect_with_cert_passes_flag(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        (ws.images / "boot.img").write_bytes(b"fake boot image")

        fake_avb = FakeAvbTool(
            {"inspect_image": AvbToolResult(0, SAMPLE_HASH, "", "info_image")}
        )
        uc = InspectImagesUseCase(ws, fake_avb)
        uc.execute(InspectImagesRequest(image_names=("boot",), with_cert=True))

        assert fake_avb.calls
        name, _args, kwargs = fake_avb.calls[0]
        assert name == "inspect_image"
        assert kwargs.get("cert") is True

    def test_inspect_multiple_images(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        (ws.images / "boot.img").write_bytes(b"fake boot")
        (ws.images / "vbmeta.img").write_bytes(b"fake vbmeta")

        fake_avb = FakeAvbTool(
            {"inspect_image": AvbToolResult(0, SAMPLE_HASH, "", "info_image")}
        )
        uc = InspectImagesUseCase(ws, fake_avb)
        result = uc.execute(InspectImagesRequest(image_names=("boot", "vbmeta")))

        assert len(result.images) == 2
