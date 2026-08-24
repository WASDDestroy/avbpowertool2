"""Cross-platform FEC encoder for AVB signing.

Uses numpy for fast vectorized Reed-Solomon RS(255, N) encoding,
with optional fallback to reedsolo (pure Python).

Algorithm: RS(255, N) over GF(256) with fcr=1 (conventional RS)
  - N = 255 - num_roots
  - Data is split into chunks of (255 - num_roots) bytes
  - Each chunk is independently RS-encoded, producing num_roots parity bytes
  - Parity bytes from all chunks are concatenated to form the FEC data
"""

from __future__ import annotations

import logging
import math
import struct
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GF_PRIMITIVE = 0x11D
_RS_CODEWORD_SIZE = 255
_FEC_FOOTER_FORMAT = "<LLLLLQ32s"
_FEC_MAGIC = 0xFECFECFE
_FEC_FOOTER_SIZE = struct.calcsize(_FEC_FOOTER_FORMAT)
_LARGE_FILE_THRESHOLD = 100 * 1024 * 1024  # 100 MB

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
    for a in range(256):
        for b in range(256):
            if a == 0 or b == 0:
                table[a, b] = 0
            else:
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
# RS encoding matrix
# ---------------------------------------------------------------------------


def _rs_generator_poly(nsym: int, fcr: int = 1) -> object:
    """Compute generator polynomial for RS(nsym) with first root alpha^fcr."""
    _init_gf_tables()
    import numpy as np

    g = np.zeros(nsym + 1, dtype=np.uint8)
    g[0] = 1

    for i in range(nsym):
        r = fcr + i
        alpha_r = 1
        for _ in range(r):
            alpha_r = _gf_mul_table[alpha_r, 2]  # type: ignore[index]

        g_new = np.zeros(nsym + 1, dtype=np.uint8)
        g_new[1:] = g[:-1]

        for j in range(len(g)):
            if g[j] != 0:
                g_new[j] ^= _gf_mul_table[g[j], alpha_r]  # type: ignore[index]

        g = g_new

    return g


def _compute_enc_matrix(nsym: int) -> object:
    """Return the RS encoding matrix (chunk_size x nsym)."""
    if nsym in _enc_matrices:
        return _enc_matrices[nsym]

    _init_gf_tables()
    import numpy as np

    chunk_size = _RS_CODEWORD_SIZE - nsym

    # Try reedsolo first for guaranteed correctness
    try:
        from reedsolo import RSCodec

        rs = RSCodec(nsym=nsym, fcr=1)
        m = np.zeros((chunk_size, nsym), dtype=np.uint8)
        msg = bytearray(chunk_size)
        for i in range(chunk_size):
            msg[i] = 1
            encoded = rs.encode(bytes(msg))
            m[i] = list(encoded[chunk_size:])
            msg[i] = 0
        _enc_matrices[nsym] = m
        return m
    except ImportError:
        pass

    # Fallback: numpy LFSR
    gen = _rs_generator_poly(nsym, fcr=1)
    g_lower = gen[:-1].copy()  # type: ignore[union-attr]

    m = np.zeros((chunk_size, nsym), dtype=np.uint8)

    for pos in range(chunk_size):
        total_len = chunk_size + nsym
        par = np.zeros(total_len, dtype=np.uint8)

        for j in range(nsym):
            par[pos + 1 + j] = g_lower[j]  # type: ignore[index]

        for i in range(pos + 1, chunk_size):
            coef = par[i]
            if coef:
                for j in range(nsym):
                    idx = i + 1 + j
                    if idx < total_len:
                        par[idx] ^= _gf_mul_table[int(coef), int(g_lower[j])]  # type: ignore[index]

        m[pos] = par[chunk_size : chunk_size + nsym]

    _enc_matrices[nsym] = m
    return m


# ---------------------------------------------------------------------------
# Numpy-based encoding (primary)
# ---------------------------------------------------------------------------


def _generate_fec_data_numpy(image_filename: str, num_roots: int) -> bytes:
    """Generate FEC parity using numpy vectorized RS encoding."""
    _init_gf_tables()
    import numpy as np

    chunk_size = _RS_CODEWORD_SIZE - num_roots
    m = _compute_enc_matrix(num_roots)

    file_size = Path(image_filename).stat().st_size

    if file_size >= _LARGE_FILE_THRESHOLD:
        logger.warning(
            "FEC encoding large file (%d MB) using numpy, this will take a while...",
            round(file_size / (1024 * 1024)),
        )

    target_batch_bytes = 256 * 1024 * 1024
    chunks_per_batch = max(1, target_batch_bytes // chunk_size)
    batch_bytes = chunks_per_batch * chunk_size

    fec_data = bytearray()
    t_last_log = time.monotonic()
    total_read = 0

    with open(image_filename, "rb") as f:
        while True:
            buf = f.read(batch_bytes)
            if not buf:
                break

            buf = bytearray(buf)
            buf_len = len(buf)

            pad_len = (chunk_size - buf_len % chunk_size) % chunk_size
            if pad_len:
                buf.extend(b"\0" * pad_len)
                buf_len += pad_len

            n_chunks = buf_len // chunk_size
            data_2d = np.frombuffer(buf, dtype=np.uint8).reshape(n_chunks, chunk_size)

            parity = np.zeros((n_chunks, num_roots), dtype=np.uint8)
            for j in range(num_roots):
                col = np.zeros(n_chunks, dtype=np.uint8)
                for i in range(chunk_size):
                    m_ij = m[i, j]  # type: ignore[index]
                    if m_ij:
                        col ^= _gf_mul_vector(data_2d[:, i], m_ij)
                parity[:, j] = col

            fec_data.extend(parity.tobytes())
            total_read += buf_len

            now = time.monotonic()
            if now - t_last_log >= 30:
                pct = 100.0 * total_read / max(file_size, 1)
                logger.warning(
                    "FEC encoding progress: %d/%d MB (%.0f%%)",
                    round(total_read / (1024 * 1024)),
                    round(file_size / (1024 * 1024)),
                    pct,
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
    chunk_size = _RS_CODEWORD_SIZE - num_roots

    if file_size >= 10 * 1024 * 1024:
        n_chunks = math.ceil(file_size / chunk_size)
        est_min = n_chunks * 0.0002 / 60
        logger.warning(
            "FEC: reedsolo fallback for %d MB file (%d chunks). "
            "Estimated %.0f minutes. Install numpy for fast encoding.",
            round(file_size / (1024 * 1024)),
            n_chunks,
            max(est_min, 0.1),
        )

    rs = RSCodec(nsym=num_roots, fcr=1)
    fec_data = bytearray()
    carryover = b""
    total = 0
    t_last = time.monotonic()

    with open(image_filename, "rb") as f:
        while True:
            buffer = f.read(1024 * 1024)
            if not buffer:
                break
            data = carryover + buffer
            carryover = b""

            num_full = len(data) // chunk_size
            for k in range(num_full):
                chunk = data[k * chunk_size : (k + 1) * chunk_size]
                encoded = rs.encode(chunk)
                fec_data.extend(encoded[-num_roots:])

            leftover_start = num_full * chunk_size
            carryover = data[leftover_start:]

            total += len(buffer)
            now = time.monotonic()
            if now - t_last >= 30:
                logger.warning(
                    "FEC (reedsolo) progress: %d/%d MB (%.0f%%)",
                    round(total / (1024 * 1024)),
                    round(file_size / (1024 * 1024)),
                    100.0 * total / max(file_size, 1),
                )
                t_last = now

    if carryover:
        chunk = carryover.ljust(chunk_size, b"\0")
        encoded = rs.encode(chunk)
        fec_data.extend(encoded[-num_roots:])

    return bytes(fec_data)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def calc_fec_data_size(image_size: int, num_roots: int) -> int:
    """Calculate how much space FEC data will take.

    Uses pure math — no subprocess or external tool needed.
    """
    chunk_size = _RS_CODEWORD_SIZE - num_roots
    return num_roots * math.ceil(image_size / chunk_size)


def generate_fec_data(image_filename: str, num_roots: int) -> bytes:
    """Generate FEC codes for an image.

    Priority:
      1. Numpy vectorized encoder (fast, cross-platform)
      2. Reedsolo library (slow fallback)

    Arguments:
      image_filename: Path to the image file.
      num_roots: Number of FEC roots.

    Returns:
      The FEC parity data as bytes.

    Raises:
      ValueError: If the image doesn't exist.
      RuntimeError: If no FEC encoding method is available.
    """
    if not Path(image_filename).exists():
        raise ValueError(f"Image file not found: {image_filename}")

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
        "No FEC encoding method available. Install numpy or reedsolo: pip install avbpowertool[fec]"
    )
