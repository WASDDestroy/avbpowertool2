"""Smoke test — verify the package is importable and avbtool patch applied."""

import importlib
from pathlib import Path


def test_package_importable():
    """The avbpowertool package should be importable."""
    import avbpowertool
    assert hasattr(avbpowertool, "__version__")


def test_version_string():
    import avbpowertool._version
    assert avbpowertool._version.__version__ == "2.0.0.dev0"


def test_fec_encoder_importable():
    """The vendor FEC encoder module should be importable."""
    from avbpowertool.vendor.fec_encoder import calc_fec_data_size, generate_fec_data
    assert callable(calc_fec_data_size)
    assert callable(generate_fec_data)


def test_fec_calc_fec_data_size():
    """calc_fec_data_size should return a positive integer."""
    from avbpowertool.vendor.fec_encoder import calc_fec_data_size
    # For an image of 4096 bytes with 2 roots, chunk_size = 253
    # ceil(4096 / 253) = 17 chunks, 17 * 2 = 34 bytes
    size = calc_fec_data_size(4096, 2)
    assert isinstance(size, int)
    assert size > 0


def test_avbtool_fec_patch_exists():
    """avbtool.py should contain the FEC fallback patch."""
    avbtool_path = Path(__file__).parent.parent / "avbtool.py"
    content = avbtool_path.read_text(encoding="utf-8")
    assert "AVBPowerTool2" in content
    assert "avbpowertool.vendor.fec_encoder" in content


def test_package_modules_exist():
    """All expected package modules should be importable (init files exist)."""
    modules = [
        "avbpowertool",
        "avbpowertool.domain",
        "avbpowertool.application",
        "avbpowertool.application.services",
        "avbpowertool.infrastructure",
        "avbpowertool.infrastructure.avbtool",
        "avbpowertool.infrastructure.persistence",
        "avbpowertool.infrastructure.filesystem",
        "avbpowertool.infrastructure.fec",
        "avbpowertool.presentation",
        "avbpowertool.presentation.cli",
        "avbpowertool.presentation.tui",
        "avbpowertool.presentation.tui.views",
        "avbpowertool.vendor",
    ]
    for mod_name in modules:
        mod = importlib.import_module(mod_name)
        assert mod is not None, f"Failed to import {mod_name}"


def test_fixture_files_exist():
    """All expected fixture files should exist."""
    fixtures_dir = Path(__file__).parent / "fixtures" / "avbtool_output"
    expected = [
        "hash_descriptor.txt",
        "hashtree_descriptor.txt",
        "vbmeta_no_descriptors.txt",
        "vbmeta_with_chain.txt",
        "hash_with_props.txt",
        "no_footer_stderr.txt",
    ]
    for name in expected:
        assert (fixtures_dir / name).exists(), f"Missing fixture: {name}"
