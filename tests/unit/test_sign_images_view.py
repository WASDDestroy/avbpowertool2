"""Tests for the TUI sign view's vbmeta generation options."""

from __future__ import annotations

from pathlib import Path

from avbpowertool.application.commands import SignImagesRequest
from avbpowertool.domain.models import (
    AvbProfile,
    DescriptorType,
    PartitionConfig,
    SigningAlgorithm,
    SigningPlan,
)
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.persistence.profile_repository import ProfileRepository
from avbpowertool.presentation.i18n import init_i18n
from avbpowertool.presentation.tui.views import sign_images as sign_view


def _partition(
    image: str,
    descriptor: DescriptorType = DescriptorType.HASH,
    *,
    included: tuple[str, ...] = (),
    extra_descriptors: tuple[str, ...] = (),
    chains: tuple[str, ...] = (),
) -> PartitionConfig:
    return PartitionConfig(
        image=image,
        descriptor=descriptor,
        algorithm=SigningAlgorithm.SHA256_RSA4096,
        key_id="testkey",
        partition_name=image.removesuffix(".img"),
        included_partitions=included,
        include_descriptors_from_image=extra_descriptors,
        chain_partitions=chains,
    )


def _profile(include_vbmeta_system: bool = False) -> AvbProfile:
    vbmeta_includes = ("dtbo", "vbmeta_system") if include_vbmeta_system else ("dtbo",)
    return AvbProfile(
        id="current",
        name="Current",
        partitions={
            "boot": _partition("boot.img"),
            "dtbo": _partition("dtbo.img"),
            "pvmfw": _partition("pvmfw.img"),
            "recovery": _partition("recovery.img"),
            "vbmeta": _partition(
                "vbmeta.img",
                DescriptorType.VBMETA,
                included=vbmeta_includes,
                chains=("boot:3:testkey.pem.bin", "vbmeta_system:2:test.pem.bin"),
            ),
            "vbmeta_system": _partition(
                "vbmeta_system.img",
                DescriptorType.VBMETA,
                included=("pvmfw",),
            ),
        },
    )


def _workspace(tmp_path: Path, profile: AvbProfile, images: tuple[str, ...]) -> WorkspacePaths:
    ws = WorkspacePaths.discover(tmp_path)
    ws.ensure_dirs()
    for image in images:
        (ws.images / image).write_bytes(b"fake image")
    ProfileRepository(ws).save(profile)
    return ws


class TestVbmetaGenerationTargets:
    def test_offers_missing_vbmeta_when_inputs_exist(self, tmp_path: Path) -> None:
        profile = _profile()
        ws = _workspace(
            tmp_path,
            profile,
            ("boot.img", "dtbo.img", "pvmfw.img", "recovery.img"),
        )

        targets = sign_view._vbmeta_generation_targets(profile, ws.images)

        assert [target.partition for target in targets] == ["vbmeta", "vbmeta_system"]
        assert all(target.missing_inputs == () for target in targets)

    def test_reports_missing_include_image(self, tmp_path: Path) -> None:
        profile = _profile()
        ws = _workspace(tmp_path, profile, ("boot.img", "dtbo.img", "recovery.img"))

        targets = {
            target.partition: target
            for target in sign_view._vbmeta_generation_targets(profile, ws.images)
        }

        assert targets["vbmeta"].missing_inputs == ()
        assert targets["vbmeta_system"].missing_inputs == ("pvmfw.img",)

    def test_nested_missing_vbmeta_inputs_block_parent(self, tmp_path: Path) -> None:
        profile = _profile(include_vbmeta_system=True)
        ws = _workspace(tmp_path, profile, ("boot.img", "dtbo.img", "recovery.img"))

        targets = {
            target.partition: target
            for target in sign_view._vbmeta_generation_targets(profile, ws.images)
        }

        assert targets["vbmeta"].missing_inputs == ("pvmfw.img",)
        assert targets["vbmeta_system"].missing_inputs == ("pvmfw.img",)

    def test_missing_extra_descriptor_image_is_reported(self, tmp_path: Path) -> None:
        profile = _profile()
        profile.partitions["vbmeta"] = _partition(
            "vbmeta.img",
            DescriptorType.VBMETA,
            extra_descriptors=("extra.img",),
        )
        ws = _workspace(tmp_path, profile, ("boot.img", "dtbo.img", "pvmfw.img"))

        targets = {
            target.partition: target
            for target in sign_view._vbmeta_generation_targets(profile, ws.images)
        }

        assert targets["vbmeta"].missing_inputs == ("extra.img",)

    def test_existing_vbmeta_is_not_a_generation_target(self, tmp_path: Path) -> None:
        profile = _profile()
        ws = _workspace(
            tmp_path,
            profile,
            ("boot.img", "dtbo.img", "pvmfw.img", "vbmeta.img"),
        )

        targets = sign_view._vbmeta_generation_targets(profile, ws.images)

        assert [target.partition for target in targets] == ["vbmeta_system"]


class TestDependencyExpansion:
    def test_selected_vbmeta_pulls_in_included_partitions(self) -> None:
        profile = _profile(include_vbmeta_system=True)

        expanded = sign_view._expand_with_included_partitions(profile, ["vbmeta", "boot"])

        assert expanded == ["vbmeta", "boot", "dtbo", "vbmeta_system", "pvmfw"]

    def test_non_vbmeta_selection_is_unchanged(self) -> None:
        profile = _profile()

        expanded = sign_view._expand_with_included_partitions(profile, ["boot", "dtbo"])

        assert expanded == ["boot", "dtbo"]

    def test_has_vbmeta_partition_matches_profile_image_name(self) -> None:
        profile = _profile()
        profile.partitions["custom"] = _partition("myvbmeta.img", DescriptorType.VBMETA)

        assert sign_view._has_vbmeta_partition(profile, ["myvbmeta"]) is True
        assert sign_view._has_vbmeta_partition(profile, ["boot"]) is False


class _FakeResult:
    executed = False
    success_count = 0
    fail_count = 0
    issues: tuple[object, ...] = ()
    plan = SigningPlan(profile_id="current", steps=(), vbmeta_order=())


class _FakeUseCase:
    last_request: SignImagesRequest | None = None

    def __init__(self, _ws: object, _avb: object) -> None:
        pass

    def execute(self, request: SignImagesRequest) -> _FakeResult:
        type(self).last_request = request
        return _FakeResult()


class _FakeSelector:
    """SelectorWidget replacement returning pre-programmed choices."""

    answers: list[list[int]] = []
    items: list[list[str]] = []

    def __init__(self, _title: str, items: list[str], multi_select: bool = False) -> None:
        self._items = items
        type(self).items.append(list(items))

    def run(self, _stdscr: object) -> list[int]:
        return type(self).answers.pop(0)


class TestSignViewFlow:
    def _patch(
        self,
        monkeypatch: object,
        *,
        answers: list[list[int]],
        messages: list[tuple[str, list[str]]],
    ) -> None:
        init_i18n("en")
        _FakeSelector.answers = answers
        _FakeSelector.items = []
        _FakeUseCase.last_request = None
        monkeypatch.setattr(sign_view, "SelectorWidget", _FakeSelector)  # type: ignore[attr-defined]
        monkeypatch.setattr(sign_view, "confirm_dialog", lambda *_a, **_k: True)  # type: ignore[attr-defined]
        monkeypatch.setattr(  # type: ignore[attr-defined]
            sign_view,
            "message_screen",
            lambda _s, title, lines: messages.append((title, list(lines))),
        )
        monkeypatch.setattr(sign_view, "SignImagesUseCase", _FakeUseCase)  # type: ignore[attr-defined]

    def test_generation_options_are_listed(self, tmp_path: Path, monkeypatch: object) -> None:
        profile = _profile()
        ws = _workspace(
            tmp_path,
            profile,
            ("boot.img", "dtbo.img", "pvmfw.img", "recovery.img"),
        )
        messages: list[tuple[str, list[str]]] = []
        # Existing images occupy indices 0..3, then vbmeta and vbmeta_system.
        self._patch(monkeypatch, answers=[[4], [0]], messages=messages)

        sign_view.show(object(), ws, object())

        assert _FakeSelector.items[0] == [
            "boot",
            "dtbo",
            "pvmfw",
            "recovery",
            "vbmeta.img (generate)",
            "vbmeta_system.img (generate)",
        ]
        # Selecting vbmeta also signs the partition whose descriptor it embeds.
        assert _FakeUseCase.last_request is not None
        assert _FakeUseCase.last_request.image_names == ("vbmeta", "dtbo")
        assert messages[-1][0] == "Signing Results"

    def test_missing_inputs_are_prompted(self, tmp_path: Path, monkeypatch: object) -> None:
        profile = _profile()
        ws = _workspace(tmp_path, profile, ("boot.img", "dtbo.img", "recovery.img"))
        messages: list[tuple[str, list[str]]] = []
        self._patch(monkeypatch, answers=[[]], messages=messages)

        sign_view.show(object(), ws, object())

        assert messages[0][0] == "Cannot Generate vbmeta Images"
        joined = "\n".join(messages[0][1])
        assert "vbmeta_system.img" in joined
        assert "pvmfw.img" in joined
        # vbmeta itself is still generatable, so it is offered next to the
        # existing images.
        assert "vbmeta.img (generate)" in _FakeSelector.items[0]
        assert "vbmeta_system.img (generate)" not in _FakeSelector.items[0]
