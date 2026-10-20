<p align="center">
  <a href="https://sbruices.github.io/AUDP-ECM-Website/"><img src="https://sbruices.github.io/AUDP-ECM-Website/assets/logo-1200.png" alt="AUDP-ECM — AUDP Error Correction Mathematics Engine" width="560"></a>
</p>

# audp-ecm (Python)

[![CI](https://github.com/SbruiceS/AUDP-ECM-Python/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/SbruiceS/AUDP-ECM-Python/actions/workflows/ci.yml)
[![Release](https://github.com/SbruiceS/AUDP-ECM-Python/actions/workflows/release.yml/badge.svg)](https://github.com/SbruiceS/AUDP-ECM-Python/actions/workflows/release.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB)](docs/index.md#compatibility)
[![Wheels](https://img.shields.io/badge/wheels-abi3%20%7C%20linux%20%7C%20windows%20%7C%20macOS-informational)](docs/releasing.md)
[![Unsafe](https://img.shields.io/badge/unsafe-forbidden-success)](docs/security.md)
[![License](https://img.shields.io/badge/license-proprietary%20(ASPF)-lightgrey)](LICENSE)
[![Website](https://img.shields.io/badge/website-AUDP--ECM-0b7285)](https://sbruices.github.io/AUDP-ECM-Website/)
[![Live demo](https://img.shields.io/badge/live%20demo-try%20it-2e9e3a)](https://sbruices.github.io/AUDP-ECM-Website/#demo)

Python bindings for **AUDP-ECM**, the AUDP Error Correction Mathematics Engine:
Reed–Solomon over GF(256), binary BCH, CRC-16/CCITT-FALSE, and a
burst-resilient pipeline that interleaves across codewords.

Built with [PyO3](https://pyo3.rs) on the Rust core. One `abi3` wheel per
platform supports CPython ≥ 3.10. No runtime dependencies.

> **Not cryptography.** CRC and Reed–Solomon correct channel noise; they do
> not authenticate data. Use a MAC/AEAD in a separate layer.

## Documentation

| | |
|---|---|
| [docs/api.md](docs/api.md) | API reference |
| [docs/security.md](docs/security.md) | Security model and guarantees |
| [docs/development.md](docs/development.md) | Building, tests, CI |
| [docs/releasing.md](docs/releasing.md) | CD pipeline and release verification |

## Install

```bash
pip install audp-ecm
```

Wheels (abi3, CPython ≥ 3.10): Linux x86_64/aarch64 (manylinux), Windows x64,
macOS universal2. Every wheel is also attached to the GitHub Release with
`SHA256SUMS` and a signed build-provenance attestation:

```bash
gh attestation verify audp_ecm-*.whl --repo SbruiceS/AUDP-ECM-Python
```

Building from source needs a Rust toolchain **and read access to the private
core repository** `SbruiceS/AUDP-ECM` (Cargo fetches it with your git
credentials; set `CARGO_NET_GIT_FETCH_WITH_CLI=true`).

## Quick start

```python
import audp_ecm as ecm

# Reed–Solomon: corrects 2·errors + erasures ≤ n − k
rs = ecm.ReedSolomon(31, 23)
cw = rs.encode(bytes(range(23)))
rx = bytearray(cw); rx[0] ^= 0xFF; rx[5] ^= 0x10
res = rs.decode(rx)                       # or rs.decode(rx, erasures=[...])
assert res.data == bytes(range(23)) and res.corrected_symbols == 2

# Burst-resilient framing: exact payload back, bursts up to depth·t corrected
codec = ecm.BurstCodec.for_burst(31, 23, payload_len=64, burst_len=16)
tx = codec.protect(b"node=17;soil_moisture=0.42")
assert codec.recover(tx) == b"node=17;soil_moisture=0.42"

# Soft information → erasures (never more than the RS budget)
eras = ecm.mark_erasures(reliability, threshold=0.5, max_erasures=rs.n - rs.k)

# Channel models for simulation
noisy = ecm.BurstErrorChannel(p_start=0.01, p_continue=0.7).corrupt(tx, seed=1)
```

## API

| Object | Purpose |
|--------|---------|
| `ReedSolomon(n, k)` | `encode`, `decode`, `decode_euclidean`, `syndromes`, `is_codeword`; `n`, `k`, `t` |
| `DecodeResult` | `data`, `corrected_symbols`, `erasures`, `verified` |
| `BurstCodec(n, k, depth)` | `protect`, `recover`; `capacity`, `encoded_len`, `burst_tolerance`; `depth_for`, `for_burst` |
| `BchCode(n, t)` | bit-level `encode` / `decode` |
| `crc16`, `append_crc16`, `verify_crc16` | CRC-16/CCITT-FALSE |
| `gf_mul`, `gf_inv`, `gf_pow` | GF(256), irreducible 0x11D |
| `interleave_codewords`, `deinterleave_codewords` | cross-codeword interleaving |
| `mark_erasures` | reliability → erasure indices |
| `SymbolErrorChannel`, `BurstErrorChannel`, `ErasureChannel` | seeded channel models |

Errors: `EcmError` ⊃ `ConfigError`, `InputLengthError`, `ErasureIndexError`, `DecodeError`.

## Security properties

- **No `unsafe`** in the binding (`#![forbid(unsafe_code)]`); the core forbids
  `unsafe` in every crate used here.
- **No panics reachable from Python**: parameters are validated before they
  reach core code that would assert; failures raise typed exceptions.
- **Immutable, thread-safe objects** (`frozen` PyO3 classes). The GIL is
  released during encode/decode.
- **TOCTOU-safe inputs**: mutable buffers (`bytearray`, `memoryview`) are
  snapshotted to `bytes` before native code runs without the GIL.
- **Bounded resources**: inputs ≤ `MAX_INPUT_BYTES` (16 MiB), burst depth
  ≤ `MAX_DEPTH` (4096), erasure lists ≤ the number of symbols.
- **Verified results**: a decode is reported only after the corrected word
  passes syndrome (and, for `BurstCodec`, CRC) verification.
- **Release hardening**: overflow checks on, LTO, stripped wheels; CI runs
  clippy `-D warnings`, `cargo audit`, `pip-audit`, Hypothesis property tests.
- Supply chain: zero runtime Python dependencies; core pinned by commit.

See [SECURITY.md](SECURITY.md) to report a vulnerability.

## Development

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install "maturin>=1.15,<2" pytest hypothesis
maturin develop --release
pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for building against a local core checkout.

## Licence

**Proprietary software — not open source.** © 2026 Sbruice Singh / Agriculture Service
of Product Farm (ASPF). All rights reserved. Use requires a written licence agreement
with ASPF; see [LICENSE](LICENSE). Licensing enquiries: sbruicesingh@haclon.in.
