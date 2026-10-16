"""CLI contract tests for ``config check-chains``.

The command is read-only: every test builds its own workspace under
``tmp_path`` and asserts that neither ``profile.json`` nor the key store
changed.
"""

from __future__ import annotations

import json
import os
from io import StringIO
from pathlib import Path

import pytest

from avbpowertool.domain.models import (
    AvbProfile,
    DescriptorType,
    PartitionConfig,
    SigningAlgorithm,
)
from avbpowertool.infrastructure.persistence.profile_codec import encode_profile
from avbpowertool.presentation.actions import ActionId
from avbpowertool.presentation.cli.parser import build_parser, main

PUBLIC_KEY_4096 = b"public key of the 4096 test key"
PUBLIC_KEY_2048 = b"public key of the 2048 test key"


def _prepare_workspace(root: Path) -> Path:
    """Create an empty workspace layout (no profiles, no active profile)."""
    (root / "Images").mkdir(exist_ok=True)
    (root / "profiles").mkdir(exist_ok=True)
    (root / "Logs").mkdir(exist_ok=True)
    (root / ".avbpowertool-staging").mkdir(exist_ok=True)
    (root / "avbtool.py").write_text("# placeholder", encoding="utf-8")
    return root


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


def _write_profile(root: Path, profile_id: str, partitions: dict[str, PartitionConfig]) -> Path:
    profile_dir = root / "profiles" / profile_id
    (profile_dir / "keys").mkdir(parents=True, exist_ok=True)
    profile_json = profile_dir / "profile.json"
    profile_json.write_text(
        json.dumps(
            encode_profile(AvbProfile(id=profile_id, name=profile_id, partitions=partitions))
        ),
        encoding="utf-8",
    )
    return profile_json


def _write_key_store(
    root: Path, profile_id: str, chain_public_key: bytes = PUBLIC_KEY_4096
) -> Path:
    """Two keys (4096 + 2048); ``boot`` signs with the 4096 one."""
    key_dir = root / "profiles" / profile_id / "keys"
    key_dir.mkdir(parents=True, exist_ok=True)
    (key_dir / "manifest.json").write_text(
        json.dumps(
            {
                "k4096": {"private_key": "k4096.pem", "public_key": "k4096.pem.bin"},
                "k2048": {"private_key": "k2048.pem", "public_key": "k2048.pem.bin"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (key_dir / "k4096.pem").write_bytes(b"private 4096")
    (key_dir / "k4096.pem.bin").write_bytes(PUBLIC_KEY_4096)
    (key_dir / "k2048.pem").write_bytes(b"private 2048")
    (key_dir / "k2048.pem.bin").write_bytes(PUBLIC_KEY_2048)
    (key_dir / "chain.bin").write_bytes(chain_public_key)
    return key_dir


def _profile_with_chain(chain: str, *, chained_algorithm: SigningAlgorithm | None = None):
    boot = _partition("boot", algorithm=chained_algorithm or SigningAlgorithm.SHA256_RSA4096)
    vbmeta = _partition("vbmeta", descriptor=DescriptorType.VBMETA, chain_partitions=(chain,))
    return {"boot": boot, "vbmeta": vbmeta}


def _run(argv: list[str]) -> tuple[int, str]:
    out = StringIO()
    try:
        code = main(argv, out=out)
    except SystemExit as exc:  # argparse --help / usage errors
        code = exc.code if isinstance(exc.code, int) else 2
    return code, out.getvalue()


class TestCheckChainsParser:
    def test_help_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, _text = _run(["config", "check-chains", "--help"])
        assert code == 0
        # argparse writes --help to the real stdout, not to ``out``.
        assert "check-chains" in capsys.readouterr().out

    def test_parser_shape(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["config", "check-chains"])
        assert args.action_id == ActionId.CONFIG_CHECK_CHAINS
        assert args.profile == "current"
        assert args.json is False
        explicit = parser.parse_args(["config", "check-chains", "--profile", "device_a", "--json"])
        assert explicit.profile == "device_a"
        assert explicit.json is True

    def test_action_id_value_is_stable(self) -> None:
        assert ActionId.CONFIG_CHECK_CHAINS == "config.check_chains"


class TestCheckChainsCli:
    def test_consistent_chain_exits_zero(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            _write_profile(tmp_path, "device_a", _profile_with_chain("boot:3:k4096.pem.bin"))
            _write_key_store(tmp_path, "device_a")
            os.chdir(tmp_path)

            code, text = _run(["config", "check-chains", "--profile", "device_a", "--json"])
        finally:
            os.chdir(old_cwd)

        data = json.loads(text)
        assert code == 0
        assert data == {"profile_id": "device_a", "checked": 1, "issues": []}

    def test_key_mismatch_exits_one(self, tmp_path: Path) -> None:
        """``chain.*`` issues must exit 1, not 0."""
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            _write_profile(tmp_path, "device_a", _profile_with_chain("boot:3:k2048.pem.bin"))
            _write_key_store(tmp_path, "device_a")
            os.chdir(tmp_path)

            code, text = _run(["config", "check-chains", "--profile", "device_a", "--json"])
        finally:
            os.chdir(old_cwd)

        data = json.loads(text)
        assert code == 1
        assert data["profile_id"] == "device_a"
        assert data["checked"] == 1
        assert [i["error_code"] for i in data["issues"]] == ["chain.key_mismatch"]

    def test_unsigned_chained_partition_exits_one(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            _write_profile(
                tmp_path,
                "device_a",
                _profile_with_chain(
                    "boot:3:k4096.pem.bin", chained_algorithm=SigningAlgorithm.NONE
                ),
            )
            _write_key_store(tmp_path, "device_a")
            os.chdir(tmp_path)

            code, text = _run(["config", "check-chains", "--profile", "device_a", "--json"])
        finally:
            os.chdir(old_cwd)

        data = json.loads(text)
        assert code == 1
        assert [i["error_code"] for i in data["issues"]] == ["chain.chained_partition_unsigned"]

    def test_unknown_profile_exits_one(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            _write_profile(tmp_path, "device_a", _profile_with_chain("boot:3:k4096.pem.bin"))
            os.chdir(tmp_path)

            code, text = _run(["config", "check-chains", "--profile", "ghost", "--json"])
        finally:
            os.chdir(old_cwd)

        data = json.loads(text)
        assert code == 1
        assert data["issues"][0]["error_code"] == "config.not_found"
        assert data["checked"] == 0

    def test_resolves_the_active_profile(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            _write_profile(tmp_path, "device_a", _profile_with_chain("boot:3:k4096.pem.bin"))
            _write_key_store(tmp_path, "device_a")
            (tmp_path / ".active-profile").write_text("device_a", encoding="utf-8")
            os.chdir(tmp_path)

            code, text = _run(["config", "check-chains", "--json"])
        finally:
            os.chdir(old_cwd)

        data = json.loads(text)
        assert code == 0
        assert data["profile_id"] == "device_a"

    def test_text_output_lists_ok_and_fail(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            _write_profile(
                tmp_path,
                "device_a",
                _profile_with_chain("boot:3:k4096.pem.bin"),
            )
            _write_key_store(tmp_path, "device_a")
            os.chdir(tmp_path)

            ok_code, ok_text = _run(["config", "check-chains", "--profile", "device_a"])

            _write_profile(
                tmp_path,
                "device_a",
                _profile_with_chain("boot:3:k2048.pem.bin"),
            )
            fail_code, fail_text = _run(["config", "check-chains", "--profile", "device_a"])
        finally:
            os.chdir(old_cwd)

        assert ok_code == 0
        assert "OK" in ok_text
        assert "boot:3:k4096.pem.bin" in ok_text
        assert fail_code == 1
        assert "FAIL" in fail_text
        assert "boot:3:k2048.pem.bin" in fail_text
        assert "chain.key_mismatch" in fail_text

    def test_command_is_read_only(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            profile_json = _write_profile(
                tmp_path, "device_a", _profile_with_chain("boot:3:k2048.pem.bin")
            )
            key_dir = _write_key_store(tmp_path, "device_a")
            profile_before = profile_json.read_bytes()
            manifest_before = (key_dir / "manifest.json").read_bytes()
            listing_before = sorted(p.name for p in key_dir.iterdir())
            os.chdir(tmp_path)

            code, _text = _run(["config", "check-chains", "--profile", "device_a", "--json"])

            assert profile_json.read_bytes() == profile_before
            assert (key_dir / "manifest.json").read_bytes() == manifest_before
            assert sorted(p.name for p in key_dir.iterdir()) == listing_before
        finally:
            os.chdir(old_cwd)

        assert code == 1
