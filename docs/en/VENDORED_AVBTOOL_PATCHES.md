# Vendored `avbtool.py` — Patch Registry

This document records every local patch applied to the vendored
[`avbtool.py`](../../avbtool.py) relative to pristine AOSP upstream, so that
patches can be **re-applied quickly when a newer upstream `avbtool` is
adopted**.

- Upstream baseline: **AOSP avbtool 1.3.0** (`AVB_VERSION_MAJOR/MINOR/SUB = 1/3/0`,
  in sync with `libavb/avb_version.h`).
- Pristine copy kept at the repository root as
  [`avbtool_reference.py`](../../avbtool_reference.py).
- Patched copy: [`avbtool.py`](../../avbtool.py).

## Contents

1. [Conventions](#conventions)
2. [Patch inventory](#patch-inventory)
3. [PATCH-CRYPTO: in-process cryptography backend](#patch-crypto-in-process-cryptography-backend)
4. [PATCH-FEC: pure-Python FEC encoder fallback](#patch-fec-pure-python-fec-encoder-fallback)
5. [Re-patching procedure for a new upstream version](#re-patching-procedure-for-a-new-upstream-version)
6. [Verification checklist](#verification-checklist)

## Conventions

Every patch site is marked with a comment containing the literal string
`PATCH: AVBPowerTool2`. Find them all with:

```shell
grep -n "PATCH: AVBPowerTool2" avbtool.py   # expect exactly 6 sites
```

To inspect the full diff against the reference snapshot:

```shell
git diff --no-index --no-prefix avbtool_reference.py avbtool.py
```

Design rules shared by all patches:

- **Fallback, never replace.** The original upstream code path (usually an
  `openssl(1)` or external-tool subprocess call) is always preserved and used
  when the fast/in-process path is unavailable. Patches wrap or branch around
  upstream code; they do not delete it.
- **No new top-level imports in `avbtool.py`.** All third-party imports are
  lazy (inside functions) so the vendored file keeps running standalone with
  only the Python standard library.
- **Byte-for-byte output compatibility.** Signatures, hashes, and image bytes
  produced by patched code must be identical to what upstream produces.

## Patch inventory

| ID | Purpose | Hook points | Fallback |
|---|---|---|---|
| PATCH-CRYPTO | RSA key operations via the `cryptography` package instead of shelling out to `openssl` | `RSAPublicKey.__init__`, `RSAPublicKey.sign`, `verify_vbmeta_signature` | original `openssl` subprocess calls (permanent per-process downgrade on any failure) |
| PATCH-FEC | FEC size calculation / generation via `avbpowertool.vendor.fec_encoder` instead of the Android `fec` binary | `calc_fec_data_size`, `generate_fec_data` | original `fec` tool subprocess calls (on `ImportError`) |

## PATCH-CRYPTO: in-process cryptography backend

### Motivation

Upstream implements all RSA operations by invoking the `openssl` command-line
tool, which must be installed and findable on `PATH`. The third-party
[`cryptography`](https://cryptography.io/) package is a mandatory dependency
of the package, so key operations run in-process instead — faster and with no
external tool dependency.

Escape hatch: set environment variable `AVB_CRYPTO_BACKEND=openssl` to force
the original subprocess implementation (useful to compare backends or to rule
out the in-process one when debugging).

### New module-level helpers

Inserted immediately after the `CERT_USAGE_UNLOCK` constant and before
`class AvbError` (at avbtool 1.3.0: around line 66). Adds no new imports at
module scope:

```python
_CRYPTOGRAPHY_USABLE = None  # None: undecided, True: usable, False: fallback


def _use_cryptography():
  """Return True if the in-process cryptography backend should be used.

  The import is deliberately lazy ('import on demand'): avbtool.py stays
  runnable without the third-party package, CLI start-up pays no import
  cost when no key operations are performed, and the decision is cached
  for the lifetime of the process.
  """
  global _CRYPTOGRAPHY_USABLE
  if _CRYPTOGRAPHY_USABLE is None:
    if os.environ.get('AVB_CRYPTO_BACKEND', '').strip().lower() == 'openssl':
      _CRYPTOGRAPHY_USABLE = False
    else:
      try:
        import cryptography  # noqa: F401

        _CRYPTOGRAPHY_USABLE = True
      except Exception:
        _CRYPTOGRAPHY_USABLE = False
  return _CRYPTOGRAPHY_USABLE


def _downgrade_to_openssl(exc):
  """Permanently switch this process back to the openssl subprocess."""
  global _CRYPTOGRAPHY_USABLE
  if _CRYPTOGRAPHY_USABLE is not False:
    sys.stderr.write(
        'avbtool: cryptography backend unusable (%s: %s); '
        'falling back to openssl subprocess.\n' % (type(exc).__name__, exc))
  _CRYPTOGRAPHY_USABLE = False


def _cryptography_load_public_numbers(key_path):
  """Return RSAPublicNumbers for a PEM file with a private or public key."""
  from cryptography.hazmat.primitives import serialization

  with open(key_path, 'rb') as f:
    data = f.read()
  try:
    private_key = serialization.load_pem_private_key(data, password=None)
  except Exception:
    # Not a readable private key - retry as a public key. This mirrors the
    # openssl implementation's '-pubin' retry for public-key-only files.
    public_key = serialization.load_pem_public_key(data)
    return public_key.public_numbers()
  return private_key.private_numbers().public_numbers


def _cryptography_modulus(key_path):
  """Read the RSA modulus from |key_path| (replaces 'openssl rsa -modulus')."""
  return _cryptography_load_public_numbers(key_path).n


def _cryptography_sign_raw(key_path, padded_data):
  """Apply the raw RSA private-key operation to already-padded data.

  Replaces 'openssl rsautl -sign -raw': |padded_data| is expected to be
  the complete PKCS#1 v1.5 padded block, so no additional padding is
  applied here - matching the historical byte-for-byte behaviour.
  """
  from cryptography.hazmat.primitives import serialization

  with open(key_path, 'rb') as f:
    data = f.read()
  private_key = serialization.load_pem_private_key(data, password=None)
  numbers = private_key.private_numbers()
  n = numbers.public_numbers.n
  m = int.from_bytes(bytes(padded_data), 'big')
  if m >= n:
    raise ValueError('Padded data block is larger than the RSA modulus')
  signature_int = pow(m, numbers.d, n)
  key_num_bytes = (n.bit_length() + 7) // 8
  return signature_int.to_bytes(key_num_bytes, 'big')


def _cryptography_verify_raw(modulus, exponent, sig_blob, expected_em):
  """Verify a raw RSA signature against an expected padded block.

  Replaces the 'openssl asn1parse -genconf' + 'openssl rsautl -verify
  -pubin -raw' pair: computing sig^e mod n over the embedded public-key
  blob makes the DER construction unnecessary.
  """
  sig_len = len(sig_blob)
  em = pow(int.from_bytes(bytes(sig_blob), 'big'), exponent, int(modulus))
  return em.to_bytes(sig_len, 'big') == bytes(expected_em)
```

Semantics of the shared state:

| State (`_CRYPTOGRAPHY_USABLE`) | Meaning |
|---|---|
| `None` | undecided yet; decided lazily on first use |
| `True` | `cryptography` importable and not disabled → use in-process backend |
| `False` | use openssl subprocess; sticky for the rest of the process |

Any exception inside a `_cryptography_*` helper triggers
`_downgrade_to_openssl(exc)` (one-time stderr notice) after which **all**
subsequent key operations in the same process use openssl.

### Hook point 1 of 3 — `RSAPublicKey.__init__` (modulus extraction)

Anchor: inside `class RSAPublicKey`, the block that upstream starts with
`args = ['openssl', 'rsa', '-in', key_path, '-modulus', '-noout']`.

Replace the upstream body with: try `_cryptography_modulus()` first; on any
exception downgrade and fall through to the untouched upstream openssl flow
(including its `-pubin` retry for public-key-only PEM files):

```python
    # PATCH: AVBPowerTool2 - use in-process cryptography when available,
    # fall back to the historical openssl(1) subprocess.
    modulus_int = None
    if _use_cryptography():
      try:
        modulus_int = _cryptography_modulus(key_path)
      except Exception as exc:
        _downgrade_to_openssl(exc)
    if modulus_int is not None:
      modulus_hexstr = '%x' % modulus_int
    else:
      args = ['openssl', 'rsa', '-in', key_path, '-modulus', '-noout']
      p = subprocess.Popen(args,
                           stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
      (pout, perr) = p.communicate()
      if p.wait() != 0:
        # Could be just a public key is passed, try that.
        args.append('-pubin')
        p = subprocess.Popen(args,
                             stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        (pout, perr) = p.communicate()
        if p.wait() != 0:
          raise AvbError('Error getting public key: {}'.format(perr))

      if not pout.lower().startswith(self.MODULUS_PREFIX):
        raise AvbError('Unexpected modulus output')

      modulus_hexstr = pout[len(self.MODULUS_PREFIX):]

    # ... upstream continues unchanged:
    self.key_path = key_path
    self.modulus = int(modulus_hexstr, 16)
```

Note how the in-process result is converted back into the same
`modulus_hexstr` variable so everything downstream is untouched. (Upstream
assumes exponent 65537; the in-process helper reads the real exponent from
the key but only `.n` is consumed here, matching upstream behaviour.)

### Hook point 2 of 3 — `RSAPublicKey.sign` (raw signing)

Anchor: in `RSAPublicKey.sign`, the `else:` branch taken when **no custom
`signing_helper` program was requested**, right before upstream spawns
`openssl rsautl -sign -raw`. Insert the in-process attempt there; custom
signing-helper programs keep priority and are never intercepted:

```python
        # PATCH: AVBPowerTool2 - apply the raw private-key operation
        # in-process when cryptography is available; the block handed to
        # us is already PKCS#1 v1.5 padded, exactly like 'rsautl -raw'.
        if _use_cryptography():
          try:
            signature = _cryptography_sign_raw(self.key_path,
                                               padding_and_hash)
          except AvbError:
            raise
          except Exception as exc:
            _downgrade_to_openssl(exc)
          else:
            if len(signature) != algorithm.signature_num_bytes:
              raise AvbError('Error signing: Invalid length of signature')
            return signature
        p = subprocess.Popen(
            ['openssl', 'rsautl', '-sign', '-inkey', self.key_path, '-raw'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
```

Behaviour contract:

- `padding_and_hash` arrives already PKCS#1 v1.5 padded from upstream code;
  the helper performs the bare `pow(m, d, n)` — identical semantics to
  `rsautl -raw`.
- Signature length is validated against `algorithm.signature_num_bytes`
  exactly like the upstream openssl path does afterwards.
- An `AvbError` raised while loading/using the key propagates (it is a
  user-facing error); any other exception downgrades to openssl and re-runs
  via subprocess.

### Hook point 3 of 3 — `verify_vbmeta_signature`

Anchor: module-level function `verify_vbmeta_signature(vbmeta_header,
vbmeta_blob)`, where upstream constructs an ASN.1 config to rebuild the
public key DER and then runs `openssl rsautl -verify -pubin -raw`.
Wrap the entire upstream block in `if verified is None:` and try the
in-process check first:

```python
  # PATCH: AVBPowerTool2 - compute sig^e mod n in-process when cryptography
  # is available; this replaces both the 'asn1parse -genconf' DER public-key
  # construction and the 'rsautl -verify -pubin -raw' invocation below.
  verified = None
  if _use_cryptography():
    try:
      verified = _cryptography_verify_raw(modulus, exponent, sig_blob,
                                          padding_and_digest)
    except Exception as exc:
      verified = None
      _downgrade_to_openssl(exc)

  if verified is None:
    # ... entire upstream openssl body, indented one level, with its final
    # comparison changed to record the result instead of returning early:
    ...
        verified = (pout == padding_and_digest)

  if not verified:
    sys.stderr.write('Signature not correct\n')
    return False
  return True
```

Two structural edits inside the wrapped upstream body:

1. The whole `asn1_str` / temp-file / two-`Popen` sequence is indented under
   `if verified is None:` — otherwise unchanged.
2. Upstream ends with `if pout != padding_and_digest: ... return False` /
   `return True`; the patch records `verified = (pout == padding_and_digest)`
   and moves the "Signature not correct" verdict below the wrapper so both
   backends share the same exit path.

The public key here comes from the vbmeta blob itself (modulus parsed from
the embedded blob, exponent hardcoded `65537` by upstream), which is why the
helper takes `(modulus, exponent)` rather than a key file path.

## PATCH-FEC: pure-Python FEC encoder fallback

### Motivation

Upstream computes Forward Error Correction data by invoking the Android
`fec` tool binary, which is not available on typical developer machines
(notably Windows). The project ships
[`avbpowertool/vendor/fec_encoder.py`](../../avbpowertool/vendor/fec_encoder.py)
— a cross-platform RS(255, N) encoder (numpy fast path, reedsolo fallback;
both are mandatory dependencies of the package). Both patched functions try
the Python implementation first and fall back to the external tool.

### Hook point 1 of 2 — `calc_fec_data_size`

Anchor: module-level function `calc_fec_data_size(image_size, num_roots)`,
at the very top of its body (before the `fec --print-fec-size` subprocess):

```python
  # PATCH: AVBPowerTool2 — try Python FEC encoder first
  try:
    from avbpowertool.vendor.fec_encoder import calc_fec_data_size as _py_calc_fec
    return _py_calc_fec(image_size, num_roots)
  except ImportError:
    pass
  # ... upstream body follows unchanged
```

### Hook point 2 of 2 — `generate_fec_data`

Anchor: module-level function `generate_fec_data(image_filename,
num_roots)`, at the very top of its body (before the `tempfile` /
`fec --encode` subprocess flow):

```python
  # PATCH: AVBPowerTool2 — try Python FEC encoder first
  try:
    from avbpowertool.vendor.fec_encoder import generate_fec_data as _py_fec
    return _py_fec(image_filename, num_roots)
  except ImportError:
    pass
  # ... upstream body follows unchanged
```

### Behaviour notes

- Only `ImportError` falls back to the external `fec` tool. If
  `fec_encoder` imports but neither numpy nor reedsolo is installed (unusual:
  both are mandatory dependencies, so a normal install always provides them),
  it raises `RuntimeError("No FEC encoding method available...")`, which
  propagates.
- Import resolution relies on Python putting the *script directory* first on
  `sys.path`: the runner invokes `[sys.executable, <workspace>/avbtool.py]`
  and `avbtool.py` sits next to the `avbpowertool/` package, so
  `avbpowertool.vendor.fec_encoder` resolves. If `avbtool.py` were copied
  away from the package, the import raises `ImportError` and the external
  `fec` tool is used.
- `calc_fec_data_size` from the Python encoder is pure arithmetic
  (`num_roots * ceil(image_size / chunk_size)`), matching the `fec` tool's
  printed size exactly.

## Re-patching procedure for a new upstream version

1. Save the new upstream script as `avbtool_reference.py` (replace the old
   snapshot) and copy it verbatim to `avbtool.py`.
2. Update the baseline version noted at the top of this document if it
   changed.
3. Apply **PATCH-FEC** first (two small insertions at the top of
   `calc_fec_data_size` and `generate_fec_data` — locate the functions by
   name, not line number).
4. Apply **PATCH-CRYPTO**:
   1. Insert the helper block after the `CERT_USAGE_UNLOCK` constant.
   2. Patch `RSAPublicKey.__init__` modulus parsing.
   3. Patch the no-signing-helper branch of `RSAPublicKey.sign`.
   4. Wrap the openssl body of `verify_vbmeta_signature` as shown above.
5. Run the verification checklist below.
6. Commit both files together with this document updated (line-number hints
   may shift; symbol anchors must not).

If upstream refactors one of the anchored functions (renamed, split, logic
changed), re-read the surrounding upstream code and adapt the hook while
preserving the design rules: keep the original path reachable, keep imports
lazy, mark the site with `# PATCH: AVBPowerTool2 ...`.

## Verification checklist

```shell
# 1. Exactly six patch markers present
grep -c "PATCH: AVBPowerTool2" avbtool.py          # expect: 6

# 2. Diff vs. reference touches only the documented regions
git diff --no-index --stat avbtool_reference.py avbtool.py

# 3. Package tests (includes test_avbtool_fec_patch_exists smoke test)
uv run pytest tests/

# 4. Crypto backend sanity:
uv run python avbtool.py version
$env:AVB_CRYPTO_BACKEND='openssl'; uv run python avbtool.py version  # forced fallback still works
```

Functional checks worth doing once after a major rebase: sign one image with
each backend (`AVB_CRYPTO_BACKEND=openssl` vs unset) and confirm the outputs
are byte-identical; generate FEC data with the Python encoder and compare
against the `fec` tool if it is available.
