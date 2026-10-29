"""Cross-platform FEC encoder for AVB signing.

This is a re-implementation of the AOSP ``libfec`` forward-error-correction
encoder (``system/extras/libfec``) so that images can be signed on hosts
where the Android ``fec`` binary is unavailable (notably Windows).

The format is *not* a plain concatenation of RS(255, N) codewords.  AOSP
uses a fixed 4096-byte block size and a byte-interleaved layout:

  * ``rsn = 255 - num_roots`` is the number of data symbols per codeword.
  * The image is split into 4096-byte blocks; every ``rsn`` blocks form a
    "round".  The last round is zero-padded.
  * A round contains 4096 codewords.  Codeword ``c`` is formed by taking
    byte ``c`` of every data block in the round, i.e. the input is read in
    columns of ``rounds * 4096`` bytes.
  * Each codeword is RS-encoded with the libfec parameters
    ``init_rs_char(8, 0x11d, fcr=0, prim=1, nroots, pad=0)``, i.e. the
    generator polynomial roots start at ``alpha**0`` (``fcr=0``).

The parity bytes for the whole image are emitted codeword by codeword,
which is exactly what ``fec --encode`` writes before its 4096-byte header
block.  ``avbtool`` only uses that leading parity payload.
"""

from __future__ import annotations

import logging
import math
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (must match system/extras/libfec)
# ---------------------------------------------------------------------------

_GF_PRIMITIVE = 0x11D
_RS_CODEWORD_SIZE = 255
_RS_FCR = 0  # init_rs_char(8, 0x11d, 0, 1, nroots, 0)
_FEC_BLOCK_SIZE = 4096  # FEC_BLOCKSIZE
_LARGE_FILE_THRESHOLD = 100 * 1024 * 1024  # 100 MB
_BATCH_TARGET_BYTES = 64 * 1024 * 1024  # per-batch working set

# ---------------------------------------------------------------------------
# GF(256) tables
# ---------------------------------------------------------------------------

_gf_mul_table = None  # numpy 256x256 uint8
_enc_matrices: dict[int, object] = {}  # nsym -> numpy encoding matrix


def _init_gf_tables() -> None:
    """Build the full GF(256) multiplication lookup table (64 KB)."""
    global _gf_mul_table
    if _gf_mul_table is not None:
        return

    import numpy as np

    gf_exp = [0] * 512
    gf_log = [0] * 256
    x = 1
    for i in range(255):
        gf_exp[i] = x
        gf_log[x] = i
        x <<= 1
        if x & 0x100:
            x ^= _GF_PRIMITIVE
    gf_exp[255:512] = gf_exp[0:255]
    gf_log[0] = 0

    table = np.zeros((256, 256), dtype=np.uint8)
    for a in range(1, 256):
        for b in range(1, 256):
            table[a, b] = gf_exp[gf_log[a] + gf_log[b]]
    _gf_mul_table = table


def _gf_mul_vector(a_col: object, b_scalar: int) -> object:
    """Multiply every element of uint8 array a_col by uint8 scalar b_scalar."""
    _init_gf_tables()
    if b_scalar == 0:
        import numpy as np

        return np.zeros_like(a_col)  # type: ignore[arg-type]
    if b_scalar == 1:
        return a_col.copy()  # type: ignore[union-attr]
    return _gf_mul_table[a_col, b_scalar]  # type: ignore[index]


# ---------------------------------------------------------------------------
# RS generator polynomial / encoding matrix
# ---------------------------------------------------------------------------


def _gf_pow_two(exponent: int) -> int:
    """Return alpha**exponent in GF(256), alpha = 2."""
    _init_gf_tables()
    value = 1
    for _ in range(exponent):
        value = int(_gf_mul_table[value, 2])  # type: ignore[index]
    return value


def _rs_generator_poly(nsym: int) -> list[int]:
    """Return the libfec generator polynomial, low-order coefficient first.

    ``g(x) = product(x + alpha**i) for i in [fcr, fcr + nsym)`` with fcr=0.
    """
    g = [0] * (nsym + 1)
    g[0] = 1

    for i in range(nsym):
        root = _gf_pow_two(_RS_FCR + i)
        g_new = [0] * (nsym + 1)
        for degree in range(nsym + 1):
            coeff = g[degree]
            if coeff == 0:
                continue
            # g(x) * x
            if degree + 1 <= nsym:
                g_new[degree + 1] ^= coeff
            # g(x) * alpha**i
            g_new[degree] ^= int(_gf_mul_table[coeff, root])  # type: ignore[index]
        g = g_new

    return g


def _compute_enc_matrix(nsym: int) -> object:
    """Return the RS encoding matrix (chunk_size x nsym).

    Row ``pos`` holds the parity contribution of the message byte at
    position ``pos``.  The matrix is derived by reducing ``x**n`` modulo
    the generator polynomial, which matches libfec's systematic encoder.
    """
    if nsym in _enc_matrices:
        return _enc_matrices[nsym]

    _init_gf_tables()
    import numpy as np

    chunk_size = _RS_CODEWORD_SIZE - nsym
    gen = _rs_generator_poly(nsym)

    # x**nsym mod g(x); g is monic, so this is g without its leading term.
    remainder = gen[:nsym]

    matrix = np.zeros((chunk_size, nsym), dtype=np.uint8)
    for pos in range(chunk_size - 1, -1, -1):
        # Codeword layout is [message..., parity...]; parity[0] is the
        # highest-order remainder coefficient.
        for i in range(nsym):
            matrix[pos, i] = remainder[nsym - 1 - i]

        # Advance to the next message position: multiply by x, then reduce.
        overflow = remainder[nsym - 1]
        shifted = [0] * nsym
        for degree in range(1, nsym):
            shifted[degree] = remainder[degree - 1]
        if overflow:
            for degree in range(nsym):
                shifted[degree] ^= int(
                    _gf_mul_table[overflow, gen[degree]]  # type: ignore[index]
                )
        remainder = shifted

    _enc_matrices[nsym] = matrix
    return matrix


# ---------------------------------------------------------------------------
# FEC layout helpers
# ---------------------------------------------------------------------------


def _fec_layout(image_size: int, num_roots: int) -> tuple[int, int, int]:
    """Return ``(rsn, rounds, codewords)`` for the AOSP FEC layout."""
    if num_roots <= 0 or num_roots >= _RS_CODEWORD_SIZE:
        raise ValueError(f"Invalid FEC roots: {num_roots}")

    if image_size <= 0:
        return _RS_CODEWORD_SIZE - num_roots, 0, 0

    blocks = math.ceil(image_size / _FEC_BLOCK_SIZE)
    rsn = _RS_CODEWORD_SIZE - num_roots
    rounds = math.ceil(blocks / rsn)
    return rsn, rounds, rounds * _FEC_BLOCK_SIZE


# ---------------------------------------------------------------------------
# Numpy-based encoding (primary)
# ---------------------------------------------------------------------------


def _generate_fec_data_numpy(image_filename: str, num_roots: int) -> bytes:
    """Generate FEC parity using numpy vectorized RS encoding."""
    import mmap

    _init_gf_tables()
    import numpy as np

    file_size = Path(image_filename).stat().st_size
    rsn, rounds, codewords = _fec_layout(file_size, num_roots)
    if codewords == 0:
        return b""

    matrix = _compute_enc_matrix(num_roots)

    if file_size >= _LARGE_FILE_THRESHOLD:
        logger.warning(
            "FEC encoding large file (%d MB) using numpy, this will take a while...",
            round(file_size / (1024 * 1024)),
        )

    # Each codeword consumes one byte per data block, so a batch holds
    # roughly batch_codewords * 255 bytes across data + parity.
    batch_codewords = max(1, _BATCH_TARGET_BYTES // _RS_CODEWORD_SIZE)

    fec_data = bytearray()
    t_last_log = time.monotonic()

    with open(image_filename, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        for c0 in range(0, codewords, batch_codewords):
            batch_len = min(batch_codewords, codewords - c0)

            # data[c, j] = byte at offset j * codewords + (c0 + c).
            data = np.zeros((batch_len, rsn), dtype=np.uint8)
            for j in range(rsn):
                offset = j * codewords + c0
                if offset >= file_size:
                    break
                count = min(batch_len, file_size - offset)
                data[:count, j] = np.frombuffer(mm, dtype=np.uint8, count=count, offset=offset)

            parity = np.zeros((batch_len, num_roots), dtype=np.uint8)
            for j in range(num_roots):
                column = np.zeros(batch_len, dtype=np.uint8)
                for i in range(rsn):
                    coeff = int(matrix[i, j])  # type: ignore[index]
                    if coeff:
                        column ^= _gf_mul_vector(data[:, i], coeff)
                parity[:, j] = column

            fec_data.extend(parity.tobytes())

            now = time.monotonic()
            if now - t_last_log >= 30:
                done = c0 + batch_len
                logger.warning(
                    "FEC encoding progress: %d/%d codewords (%.0f%%)",
                    done,
                    codewords,
                    100.0 * done / codewords,
                )
                t_last_log = now

    return bytes(fec_data)


# ---------------------------------------------------------------------------
# Reedsolo fallback (slow pure Python)
# ---------------------------------------------------------------------------


def _generate_fec_data_reedsolo(image_filename: str, num_roots: int) -> bytes:
    """Generate FEC parity using the reedsolo library."""
    from reedsolo import RSCodec

    file_size = Path(image_filename).stat().st_size
    rsn, rounds, codewords = _fec_layout(file_size, num_roots)
    if codewords == 0:
        return b""

    if file_size >= 10 * 1024 * 1024:
        logger.warning(
            "FEC: reedsolo fallback for %d MB file (%d codewords). "
            "Install numpy for fast encoding.",
            round(file_size / (1024 * 1024)),
            codewords,
        )

    rs = RSCodec(nsym=num_roots, fcr=_RS_FCR)
    batch_codewords = max(1, (4 * 1024 * 1024) // rsn)

    fec_data = bytearray()
    t_last = time.monotonic()

    with open(image_filename, "rb") as f:
        for c0 in range(0, codewords, batch_codewords):
            batch_len = min(batch_codewords, codewords - c0)

            columns: list[bytes] = []
            for j in range(rsn):
                offset = j * codewords + c0
                if offset >= file_size:
                    columns.extend([b""] * (rsn - j))
                    break
                f.seek(offset)
                columns.append(f.read(min(batch_len, file_size - offset)))

            for c in range(batch_len):
                message = bytearray(rsn)
                for j in range(rsn):
                    column = columns[j]
                    if c < len(column):
                        message[j] = column[c]
                encoded = rs.encode(bytes(message))
                fec_data.extend(encoded[-num_roots:])

            now = time.monotonic()
            if now - t_last >= 30:
                done = c0 + batch_len
                logger.warning(
                    "FEC (reedsolo) progress: %d/%d codewords (%.0f%%)",
                    done,
                    codewords,
                    100.0 * done / codewords,
                )
                t_last = now

    return bytes(fec_data)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def calc_fec_data_size(image_size: int, num_roots: int) -> int:
    """Calculate how much space FEC data will take.

    Mirrors ``fec --print-fec-size``: parity bytes plus one 4096-byte
    header block.  Returns 0 for invalid arguments, like the native tool.
    """
    if image_size <= 0 or num_roots <= 0 or num_roots >= _RS_CODEWORD_SIZE:
        return 0

    blocks = math.ceil(image_size / _FEC_BLOCK_SIZE)
    rsn = _RS_CODEWORD_SIZE - num_roots
    rounds = math.ceil(blocks / rsn)
    return rounds * num_roots * _FEC_BLOCK_SIZE + _FEC_BLOCK_SIZE


def generate_fec_data(image_filename: str, num_roots: int) -> bytes:
    """Generate FEC parity for an image.

    Priority:
      1. Numpy vectorized encoder (fast, cross-platform)
      2. Reedsolo library (slow fallback)

    Arguments:
      image_filename: Path to the image file.
      num_roots: Number of FEC roots.

    Returns:
      The FEC parity data as bytes (without the native 4096-byte header).

    Raises:
      ValueError: If the image doesn't exist or the roots are invalid.
      RuntimeError: If no FEC encoding method is available.
    """
    if not Path(image_filename).exists():
        raise ValueError(f"Image file not found: {image_filename}")
    if num_roots <= 0 or num_roots >= _RS_CODEWORD_SIZE:
        raise ValueError(f"Invalid FEC roots: {num_roots}")

    try:
        import numpy  # noqa: F401

        logger.info("FEC: using numpy encoder for %s", Path(image_filename).name)
        return _generate_fec_data_numpy(image_filename, num_roots)
    except ImportError:
        pass

    try:
        from reedsolo import RSCodec  # noqa: F401

        logger.info("FEC: using reedsolo encoder for %s", Path(image_filename).name)
        return _generate_fec_data_reedsolo(image_filename, num_roots)
    except ImportError:
        pass

    raise RuntimeError(
        "No FEC encoding method available. numpy and reedsolo are mandatory "
        "dependencies of avbpowertool — reinstall the package "
        "(pip install --force-reinstall avbpowertool)."
    )
