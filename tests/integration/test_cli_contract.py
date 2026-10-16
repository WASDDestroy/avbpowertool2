"""CLI contract tests — parser shape, --help, --json, exit codes."""

from __future__ import annotations

import json
import os
from io import StringIO
from pathlib import Path

from avbpowertool.domain.models import (
    AvbProfile,
    DescriptorType,
    PartitionConfig,
    SigningAlgorithm,
)
from avbpowertool.infrastructure.persistence.profile_codec import encode_profile
from avbpowertool.presentation.cli.parser import build_parser, main


class TestParserShape:
    def test_help_exits_zero(self) -> None:
        out = StringIO()
        try:
            code = main(["--help"], out=out)
        except SystemExit as exc:
            code = exc.code
        assert code == 0

    def test_image_inspect_help(self) -> None:
        out = StringIO()
        try:
            code = main(["image", "inspect", "--help"], out=out)
        except SystemExit as exc:
            code = exc.code
        assert code == 0

    def test_image_sign_help(self) -> None:
        out = StringIO()
        try:
            code = main(["image", "sign", "--help"], out=out)
        except SystemExit as exc:
            code = exc.code
        assert code == 0

    def test_config_show_help(self) -> None:
        out = StringIO()
        try:
            code = main(["config", "show", "--help"], out=out)
        except SystemExit as exc:
            code = exc.code
        assert code == 0

    def test_config_list_help(self) -> None:
        out = StringIO()
        try:
            code = main(["config", "list", "--help"], out=out)
        except SystemExit as exc:
            code = exc.code
        assert code == 0

    def test_config_import_legacy_help(self) -> None:
        out = StringIO()
        try:
            code = main(["config", "import-legacy", "--help"], out=out)
        except SystemExit as exc:
            code = exc.code
        assert code == 0

    def test_config_edit_help(self) -> None:
        out = StringIO()
        try:
            code = main(["config", "edit", "--help"], out=out)
        except SystemExit as exc:
            code = exc.code
        assert code == 0


class TestAboutCommand:
    def test_about_outputs_version(self) -> None:
        out = StringIO()
        code = main(["about"], out=out)
        assert code == 0
        output = out.getvalue()
        assert "AVBPowerTool" in output


class TestDeprecatedAliases:
    def test_read_alias_warns(self) -> None:
        """The 'read' alias should produce a deprecation warning."""
        out = StringIO()
        err = StringIO()
        # read needs images but we just want to check the warning
        # It will fail with missing images, but should still warn
        import sys

        old_stderr = sys.stderr
        sys.stderr = err
        try:
            main(["read"], out=out)
        except SystemExit:
            pass
        finally:
            sys.stderr = old_stderr
        # The deprecated warning should appear
        assert "deprecated" in err.getvalue().lower() or "warning" in err.getvalue().lower()


class TestJsonOutput:
    def test_config_list_json_empty(self, tmp_path: Path) -> None:
        """config list --json should produce valid JSON even with no profiles."""
        import os

        # Change to tmp workspace
        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        (tmp_path / "profiles").mkdir(exist_ok=True)
        (tmp_path / "Logs").mkdir(exist_ok=True)
        (tmp_path / ".avbpowertool-staging").mkdir(exist_ok=True)
        (tmp_path / "avbtool.py").write_text("# placeholder")

        out = StringIO()
        try:
            code = main(["config", "list", "--json"], out=out)
            output = out.getvalue()
            data = json.loads(output)
            assert code == 0
            assert "profiles" in data
            assert isinstance(data["profiles"], list)
        finally:
            os.chdir(old_cwd)

    def test_about_no_json_flag(self) -> None:
        """about command works without --json."""
        out = StringIO()
        code = main(["about"], out=out)
        assert code == 0
        assert "AVBPowerTool" in out.getvalue()


class TestLegacyImportCli:
    LEGACY_FIXTURES = Path(__file__).parent.parent / "fixtures" / "legacy"

    def _make_v1_archive(self, tmp_path: Path, name: str = "legacy.zip") -> Path:
        import zipfile

        archive = tmp_path / name
        with zipfile.ZipFile(archive, "w") as zf:
            zf.write(
                self.LEGACY_FIXTURES / "imageInfo.json",
                "Configs/ZUXOS_411/imageInfo.json",
            )
            for f in sorted((self.LEGACY_FIXTURES / "keys").iterdir()):
                zf.write(f, f"Keys/ZUXOS_411/{f.name}")
            zf.writestr("this_is_a_config_file_of_avbpowertool", "x")
        return archive

    def _enter_workspace(self, tmp_path: Path) -> None:
        import os

        (tmp_path / "profiles").mkdir(exist_ok=True)
        (tmp_path / "Logs").mkdir(exist_ok=True)
        (tmp_path / ".avbpowertool-staging").mkdir(exist_ok=True)
        (tmp_path / "avbtool.py").write_text("# placeholder")
        os.chdir(tmp_path)

    def test_import_legacy_json(self, tmp_path: Path) -> None:
        import os

        archive = self._make_v1_archive(tmp_path)
        old_cwd = os.getcwd()
        try:
            self._enter_workspace(tmp_path)
            out = StringIO()
            code = main(["config", "import-legacy", str(archive), "--json"], out=out)
            data = json.loads(out.getvalue())
            assert code == 0
            assert data["profile_id"] == "ZUXOS_411"
            assert data["partition_count"] == 15
            assert data["key_count"] == 2
            assert data["issues"] == []
        finally:
            os.chdir(old_cwd)

    def test_import_legacy_text_custom_name(self, tmp_path: Path) -> None:
        import os

        archive = self._make_v1_archive(tmp_path)
        old_cwd = os.getcwd()
        try:
            self._enter_workspace(tmp_path)
            out = StringIO()
            code = main(
                ["config", "import-legacy", str(archive), "--name", "my_device"],
                out=out,
            )
            assert code == 0
            assert "my_device" in out.getvalue()
        finally:
            os.chdir(old_cwd)


class TestExitCodes:
    def test_no_command_would_launch_tui(self) -> None:
        """No subcommand should attempt to launch TUI (bootstrap + App)."""
        # We can't test the actual TUI in headless mode, but we can verify
        # the code path exists by checking that the parser doesn't error
        # and the action_id is None.
        parser = build_parser()
        args = parser.parse_args([])
        assert getattr(args, "action_id", None) is None
        assert getattr(args, "command", None) is None


def _prepare_workspace(root: Path) -> Path:
    """Create an empty workspace layout (no profiles, no active profile)."""
    (root / "Images").mkdir(exist_ok=True)
    (root / "profiles").mkdir(exist_ok=True)
    (root / "Logs").mkdir(exist_ok=True)
    (root / ".avbpowertool-staging").mkdir(exist_ok=True)
    (root / "avbtool.py").write_text("# placeholder", encoding="utf-8")
    return root


def _write_profile(
    root: Path, profile_id: str, partitions: dict[str, PartitionConfig] | None = None
) -> None:
    """Write a minimal profile.json + key store for *profile_id*."""
    profile_dir = root / "profiles" / profile_id
    (profile_dir / "keys").mkdir(parents=True, exist_ok=True)
    profile = AvbProfile(id=profile_id, name=profile_id, partitions=partitions or {})
    (profile_dir / "profile.json").write_text(
        json.dumps(encode_profile(profile), indent=2), encoding="utf-8"
    )


def _activate(root: Path, profile_id: str) -> None:
    (root / ".active-profile").write_text(profile_id, encoding="utf-8")


class TestProfileResolutionCli:
    """``current`` must resolve to the active profile; --profile wins."""

    def test_config_show_without_active_profile(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            os.chdir(tmp_path)
            out = StringIO()
            code = main(["config", "show", "--json"], out=out)
        finally:
            os.chdir(old_cwd)

        data = json.loads(out.getvalue())
        assert code != 0
        assert data["issues"][0]["error_code"] == "config.no_active_profile"

    def test_config_show_uses_literal_current_profile(self, tmp_workspace: Path) -> None:
        """A profile really named ``current`` (conftest layout) still works."""
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_workspace)
            out = StringIO()
            code = main(["config", "show", "--json"], out=out)
        finally:
            os.chdir(old_cwd)

        data = json.loads(out.getvalue())
        assert code == 0
        assert data["config_name"] == "current"
        assert data["issues"] == []

    def test_config_show_resolves_active_and_explicit_profile(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            _write_profile(tmp_path, "device_x")
            _write_profile(tmp_path, "device_y")
            _activate(tmp_path, "device_x")
            os.chdir(tmp_path)

            default_out = StringIO()
            default_code = main(["config", "show", "--json"], out=default_out)
            explicit_out = StringIO()
            explicit_code = main(
                ["config", "show", "--profile", "device_y", "--json"], out=explicit_out
            )
        finally:
            os.chdir(old_cwd)

        assert default_code == 0
        assert json.loads(default_out.getvalue())["config_name"] == "device_x"
        assert explicit_code == 0
        assert json.loads(explicit_out.getvalue())["config_name"] == "device_y"

    def test_config_validate_uses_active_profile(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            _write_profile(tmp_path, "device_x")
            _activate(tmp_path, "device_x")
            os.chdir(tmp_path)

            out = StringIO()
            code = main(["config", "validate", "--json"], out=out)
        finally:
            os.chdir(old_cwd)

        data = json.loads(out.getvalue())
        assert code == 0
        assert data["config_name"] == "device_x"

    def test_image_sign_dry_run_uses_active_profile(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            _write_profile(
                tmp_path,
                "device_a",
                partitions={
                    "boot": PartitionConfig(
                        image="boot.img",
                        descriptor=DescriptorType.HASH,
                        algorithm=SigningAlgorithm.SHA256_RSA4096,
                        key_id="testkey_rsa4096",
                        partition_name="boot",
                        rollback_index=0,
                        salt="abcdef",
                    ),
                },
            )
            key_dir = tmp_path / "profiles" / "device_a" / "keys"
            (key_dir / "testkey_rsa4096.pem").write_text("fake key", encoding="utf-8")
            (key_dir / "testkey_rsa4096_pub.bin").write_bytes(b"fake public key")
            (key_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "testkey_rsa4096": {
                            "private_key": "testkey_rsa4096.pem",
                            "public_key": "testkey_rsa4096_pub.bin",
                        }
                    }
                ),
                encoding="utf-8",
            )
            (tmp_path / "Images" / "boot.img").write_bytes(b"fake boot image")
            _activate(tmp_path, "device_a")
            os.chdir(tmp_path)

            out = StringIO()
            code = main(["image", "sign", "boot", "--dry-run", "--json"], out=out)
        finally:
            os.chdir(old_cwd)

        data = json.loads(out.getvalue())
        assert code == 0
        assert data["issues"] == []
        assert data["plan"]["profile_id"] == "device_a"
        assert [s["operation"] for s in data["plan"]["steps"]] == ["add_hash_footer"]


class TestConfigEditCli:
    """End-to-end ``config edit --append`` / ``--remove`` wiring."""

    def _write_vbmeta_profile(self, root: Path) -> None:
        _write_profile(
            root,
            "device_a",
            partitions={
                "vbmeta": PartitionConfig(
                    image="vbmeta.img",
                    descriptor=DescriptorType.VBMETA,
                    algorithm=SigningAlgorithm.SHA256_RSA4096,
                    key_id="testkey_rsa4096",
                    partition_name="vbmeta",
                    chain_partitions=("boot:3:old_boot.pem.bin",),
                    included_partitions=("boot", "odm"),
                ),
            },
        )

    def test_config_edit_append_and_remove_json(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            self._write_vbmeta_profile(tmp_path)
            os.chdir(tmp_path)

            out = StringIO()
            code = main(
                [
                    "config",
                    "edit",
                    "vbmeta",
                    "--profile",
                    "device_a",
                    "--append",
                    "chain_partitions=boot:4:new_boot.pem.bin",
                    "--append",
                    "included_partitions=dtbo",
                    "--remove",
                    "included_partitions=odm",
                    "--json",
                ],
                out=out,
            )
            on_disk = json.loads(
                (tmp_path / "profiles" / "device_a" / "profile.json").read_text(encoding="utf-8")
            )
        finally:
            os.chdir(old_cwd)

        data = json.loads(out.getvalue())
        assert code == 0
        assert data["issues"] == []
        assert data["profile_id"] == "device_a"
        assert data["partition_name"] == "vbmeta"

        vbmeta = on_disk["partitions"]["vbmeta"]
        assert vbmeta["chain_partitions"] == ["boot:4:new_boot.pem.bin"]
        assert vbmeta["included_partitions"] == ["boot", "dtbo"]

    def test_config_edit_unset_and_set_json(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            self._write_vbmeta_profile(tmp_path)
            os.chdir(tmp_path)

            out = StringIO()
            code = main(
                [
                    "config",
                    "edit",
                    "vbmeta",
                    "--profile",
                    "device_a",
                    "--set",
                    "algorithm=SHA256_RSA2048",
                    "--unset",
                    "included_partitions",
                    "--json",
                ],
                out=out,
            )
            on_disk = json.loads(
                (tmp_path / "profiles" / "device_a" / "profile.json").read_text(encoding="utf-8")
            )
        finally:
            os.chdir(old_cwd)

        data = json.loads(out.getvalue())
        assert code == 0
        assert data["issues"] == []
        vbmeta = on_disk["partitions"]["vbmeta"]
        assert vbmeta["algorithm"] == "SHA256_RSA2048"
        assert "included_partitions" not in vbmeta

    def test_config_edit_conflicting_forms_exit_1(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            self._write_vbmeta_profile(tmp_path)
            os.chdir(tmp_path)

            out = StringIO()
            code = main(
                [
                    "config",
                    "edit",
                    "vbmeta",
                    "--profile",
                    "device_a",
                    "--set",
                    "included_partitions=boot",
                    "--append",
                    "included_partitions=dtbo",
                    "--json",
                ],
                out=out,
            )
        finally:
            os.chdir(old_cwd)

        data = json.loads(out.getvalue())
        assert code == 1
        assert data["issues"][0]["error_code"] == "config.invalid_option_combination"

    def test_config_edit_malformed_append_exits_2(self, tmp_path: Path) -> None:
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            self._write_vbmeta_profile(tmp_path)
            os.chdir(tmp_path)

            out = StringIO()
            code = main(
                ["config", "edit", "vbmeta", "--append", "chain_partitions"],
                out=out,
            )
        finally:
            os.chdir(old_cwd)

        assert code == 2

    def test_config_edit_bare_chain_append_exits_1_without_writing(self, tmp_path: Path) -> None:
        """A bare chain name is not a valid --append item: exit 1, no write."""
        old_cwd = os.getcwd()
        try:
            _prepare_workspace(tmp_path)
            self._write_vbmeta_profile(tmp_path)
            profile_path = tmp_path / "profiles" / "device_a" / "profile.json"
            before = profile_path.read_bytes()
            os.chdir(tmp_path)

            out = StringIO()
            code = main(
                [
                    "config",
                    "edit",
                    "vbmeta",
                    "--profile",
                    "device_a",
                    "--append",
                    "chain_partitions=recovery",
                    "--json",
                ],
                out=out,
            )
            after = profile_path.read_bytes()
        finally:
            os.chdir(old_cwd)

        data = json.loads(out.getvalue())
        assert code == 1
        assert data["issues"][0]["error_code"] == "config.invalid_field"
        assert "PART:SLOT:KEYFILE" in data["issues"][0]["message"]
        assert after == before


class TestParserBuilds:
    def test_build_parser_returns_parser(self) -> None:
        parser = build_parser()
        assert parser is not None
        assert parser.prog == "avbpowertool"

    def test_parser_has_all_subcommands(self) -> None:
        parser = build_parser()
        # Verify key subcommands exist by parsing
        args = parser.parse_args(["image", "inspect", "boot"])
        assert args.command == "image"
        assert args.image_command == "inspect"
        assert args.images == ["boot"]

    def test_profile_flag_on_profile_resolving_subcommands(self) -> None:
        parser = build_parser()
        assert parser.parse_args(["image", "sign", "boot"]).profile == "current"
        assert parser.parse_args(["config", "show"]).profile == "current"
        assert parser.parse_args(["config", "validate"]).profile == "current"
        assert parser.parse_args(["config", "show", "--profile", "device_a"]).profile == "device_a"
        assert (
            parser.parse_args(["image", "sign", "boot", "--profile", "device_a"]).profile
            == "device_a"
        )
