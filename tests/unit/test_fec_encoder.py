"""Known-answer tests for the AOSP-compatible FEC encoder.

The expected parity blobs in ``tests/fixtures/fec`` were produced by the
native AOSP ``fec`` encoder (``/avbpowertool/bin/fec`` on an Android
recovery device, compiled from the libfec sources).  The input images are
generated from a deterministic byte pattern, so only the parity fixtures
need to be stored.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from avbpowertool.vendor.fec_encoder import (
    _generate_fec_data_numpy,
    _generate_fec_data_reedsolo,
    calc_fec_data_size,
    generate_fec_data,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "fec"


def _image(size: int) -> bytes:
    return bytes((i * 37 + 11) & 0xFF for i in range(size))


@pytest.mark.parametrize(
    ("image_size", "num_roots", "expected"),
    [
        # Values from `fec --print-fec-size` (parity + 4096-byte header).
        (0, 2, 0),
        (1, 2, 12288),
        (4095, 2, 12288),
        (4096, 2, 12288),
        (4097, 8, 36864),
        (1040384, 2, 20480),
        (1048576, 2, 20480),
        (1048576, 8, 69632),
        (2097152, 2, 28672),
        (12095488, 2, 102400),
        (12095488, 8, 397312),
        # Invalid roots match the native tool's 0 result.
        (4096, 0, 0),
        (4096, 255, 0),
    ],
)
def test_calc_fec_data_size(image_size: int, num_roots: int, expected: int) -> None:
    assert calc_fec_data_size(image_size, num_roots) == expected


@pytest.mark.parametrize(
    ("fixture", "image_size", "num_roots"),
    [
        ("image_4096_roots2.fec", 4096, 2),
        ("image_12288_roots8.fec", 12288, 8),
        # 254 blocks -> two rounds, exercising the round/interleave padding.
        ("image_1040384_roots2.fec", 1040384, 2),
    ],
)
def test_generate_fec_data_matches_native(
    tmp_path: Path, fixture: str, image_size: int, num_roots: int
) -> None:
    image_path = tmp_path / "image.bin"
    image_path.write_bytes(_image(image_size))
    expected = (FIXTURES / fixture).read_bytes()

    assert generate_fec_data(str(image_path), num_roots) == expected
    assert _generate_fec_data_numpy(str(image_path), num_roots) == expected
    assert _generate_fec_data_reedsolo(str(image_path), num_roots) == expected


@pytest.mark.parametrize("num_roots", [1, 2, 3, 8, 16, 32])
def test_numpy_and_reedsolo_agree(tmp_path: Path, num_roots: int) -> None:
    image_path = tmp_path / "image.bin"
    image_path.write_bytes(_image(12288))

    assert _generate_fec_data_numpy(str(image_path), num_roots) == (
        _generate_fec_data_reedsolo(str(image_path), num_roots)
    )


def test_generate_fec_data_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Image file not found"):
        generate_fec_data(str(tmp_path / "missing.bin"), 2)


@pytest.mark.parametrize("num_roots", [0, 255, -1])
def test_generate_fec_data_invalid_roots(tmp_path: Path, num_roots: int) -> None:
    image_path = tmp_path / "image.bin"
    image_path.write_bytes(_image(4096))
    with pytest.raises(ValueError, match="Invalid FEC roots"):
        generate_fec_data(str(image_path), num_roots)
