"""Tests for the declarative command spec (port of the Android data model)."""

from __future__ import annotations

from avbpowertool.domain.command_spec import (
    COMMANDS,
    ArgType,
    CommandArg,
    spec_for,
)
from avbpowertool.domain.models import PartitionConfig


class TestCommandRegistry:
    def test_all_five_commands_present(self) -> None:
        assert set(COMMANDS) == {
            "add_hash_footer",
            "add_hashtree_footer",
            "make_vbmeta_image",
            "info_image",
            "extract_public_key",
        }

    def test_spec_for_unknown_returns_none(self) -> None:
        assert spec_for("does_not_exist") is None

    def test_every_config_field_resolves_on_partition_config(self) -> None:
        """Every config_field referenced by a CommandArg must be a real
        PartitionConfig field — guarantees the spec cannot drift from the
        domain model."""
        allowed = set(PartitionConfig.__dataclass_fields__)
        for command_id, spec in COMMANDS.items():
            for arg in list(spec.inputs) + list(spec.outputs) + list(spec.args):
                if arg.config_field and arg.config_field not in allowed:
                    raise AssertionError(f"{command_id}: unknown config field {arg.config_field!r}")


class TestAddHashFooterSpec:
    def _spec(self) -> object:
        return COMMANDS["add_hash_footer"]

    def test_image_input_required(self) -> None:
        image = COMMANDS["add_hash_footer"].inputs[0]
        assert image.flag == "--image"
        assert image.required is True

    def test_partition_size_present(self) -> None:
        arg = _arg("add_hash_footer", "partition_size")
        assert arg.flag == "--partition_size"
        assert arg.arg_type == ArgType.SIZE

    def test_dynamic_partition_size_bool(self) -> None:
        arg = _arg("add_hash_footer", "dynamic_partition_size")
        assert arg.arg_type == ArgType.BOOL

    def test_hash_algorithm_default_sha256(self) -> None:
        arg = _arg("add_hash_footer", "hash_algorithm")
        assert arg.default == "sha256"

    def test_algorithm_default_none(self) -> None:
        arg = _arg("add_hash_footer", "algorithm")
        assert arg.default == "NONE"

    def test_advanced_flags(self) -> None:
        assert _arg("add_hash_footer", "signing_helper").advanced is True
        assert _arg("add_hash_footer", "output_vbmeta_image").advanced is True
        assert _arg("add_hash_footer", "flags").advanced is False


class TestAddHashtreeFooterSpec:
    def test_block_size_default_4096(self) -> None:
        arg = _arg("add_hashtree_footer", "block_size")
        assert arg.arg_type == ArgType.INT
        assert arg.default == 4096

    def test_fec_options(self) -> None:
        assert _arg("add_hashtree_footer", "fec_num_roots").default == 2
        assert _arg("add_hashtree_footer", "do_not_generate_fec").arg_type == ArgType.BOOL

    def test_no_dynamic_partition_size(self) -> None:
        """add_hashtree_footer has no --dynamic_partition_size option."""
        fields = {a.config_field for a in COMMANDS["add_hashtree_footer"].args}
        assert "dynamic_partition_size" not in fields


class TestMakeVbmetaSpec:
    def test_output_required(self) -> None:
        out = COMMANDS["make_vbmeta_image"].outputs[0]
        assert out.flag == "--output"
        assert out.required is True

    def test_padding_size_advanced(self) -> None:
        arg = _arg("make_vbmeta_image", "padding_size")
        assert arg.advanced is True
        assert arg.default == 0


class TestInfoImageSpec:
    def test_image_required_and_cert(self) -> None:
        image = COMMANDS["info_image"].inputs[0]
        assert image.required is True
        cert_args = [a for a in COMMANDS["info_image"].args if a.flag == "--cert"]
        assert cert_args
        assert cert_args[0].arg_type == ArgType.BOOL


class TestExtractPublicKeySpec:
    def test_key_required_output_required(self) -> None:
        key = _arg("extract_public_key", "key_id")
        assert key.required is True
        out = COMMANDS["extract_public_key"].outputs[0]
        assert out.required is True


def _arg(command_id: str, config_field: str) -> CommandArg:
    """Return the CommandArg bound to a PartitionConfig field."""
    spec = COMMANDS[command_id]
    for arg in list(spec.inputs) + list(spec.outputs) + list(spec.args):
        if arg.config_field == config_field:
            return arg
    raise AssertionError(f"{command_id}: no arg for field {config_field!r}")
