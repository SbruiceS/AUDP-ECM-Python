# API reference

All functions accept any **bytes-like** object (`bytes`, `bytearray`, `memoryview`,
or anything supporting the buffer protocol). Mutable inputs are copied to an
immutable snapshot before native code runs. `str` is rejected — encode it first.

## Errors

```
EcmError                      base class (subclass of Exception)
├── ConfigError               invalid parameters (n, k, t, depth)
├── InputLengthError          wrong length, or input larger than MAX_INPUT_BYTES
├── ErasureIndexError         erasure index negative or ≥ number of symbols
└── DecodeError               too many errors, or verification (syndromes/CRC) failed
```

Probability arguments of channel models raise `ValueError` when out of range.

## Constants

| Name | Value | Meaning |
|------|-------|---------|
| `MAX_INPUT_BYTES` | 16 777 216 | upper bound for any single input |
| `MAX_DEPTH` | 4096 | upper bound for `BurstCodec` depth |
| `__version__` | e.g. `"0.2.0"` | package version |

## `ReedSolomon(n, k)`

Systematic RS code over GF(256). Requires `0 < k < n ≤ 255`.
Codeword layout: `n − k` parity bytes followed by the `k` data bytes.

| Member | Returns | Notes |
|--------|---------|-------|
| `n`, `k`, `t` | `int` | `t = (n − k) // 2` |
| `encode(data)` | `bytes` (n) | `len(data)` must equal `k` |
| `decode(received, erasures=None)` | `DecodeResult` | Berlekamp–Massey; `2e + s ≤ n − k` |
| `decode_euclidean(received, erasures=None)` | `DecodeResult` | Euclidean key-equation solver; same contract |
| `syndromes(received)` | `bytes` (n − k) | all zero ⇔ codeword |
| `is_codeword(word)` | `bool` | |

`erasures` are positions (0 … n−1) known to be unreliable; duplicates are ignored.

### `DecodeResult`

| Attribute | Type | Meaning |
|-----------|------|---------|
| `data` | `bytes` | the `k` recovered data bytes |
| `corrected_symbols` | `int` | unknown errors corrected |
| `erasures` | `int` | distinct erasures supplied |
| `verified` | `bool` | always `True` for a returned result (failures raise `DecodeError`) |

## `BurstCodec(n, k, depth)`

Frames `len(u16) ‖ payload ‖ CRC-16`, spreads it over `depth` RS(n, k) codewords and
interleaves symbol `j` of codeword `i` to position `j·depth + i`. A contiguous burst
of `L` symbols touches at most `⌈L / depth⌉` symbols per codeword.

| Member | Returns | Notes |
|--------|---------|-------|
| `BurstCodec.depth_for(n, k, payload_len, burst_len)` | `int` | smallest depth that fits the payload and the burst |
| `BurstCodec.for_burst(n, k, payload_len, burst_len)` | `BurstCodec` | constructor using `depth_for` |
| `depth`, `capacity`, `encoded_len`, `burst_tolerance` | `int` | `encoded_len = n·depth`, `burst_tolerance = depth·t` |
| `protect(payload)` | `bytes` | `len(payload) ≤ capacity` |
| `recover(received, erasures=None)` | `bytes` | exact payload; erasures index the transmitted stream |

## `BchCode(n, t)`

Binary narrow-sense BCH (shortened from length 255). Raises `ConfigError` when the
generator degree reaches `n` (e.g. `BchCode(15, 2)`).

| Member | Returns |
|--------|---------|
| `n`, `k`, `t` | `int` |
| `encode(data_bits: list[bool])` | `list[bool]` (n) |
| `decode(received_bits: list[bool])` | `list[bool]` (k) |

## Functions

| Function | Returns | Notes |
|----------|---------|-------|
| `gf_mul(a, b)`, `gf_pow(a, e)` | `int` | GF(256), irreducible 0x11D |
| `gf_inv(a)` | `int` | `ValueError` for 0 |
| `crc16(data)` | `int` | CRC-16/CCITT-FALSE; `crc16(b"123456789") == 0x29B1` |
| `append_crc16(data)` | `bytes` | data + big-endian CRC |
| `verify_crc16(frame)` | `bytes` | strips CRC; `DecodeError` on mismatch |
| `interleave_codewords(codewords)` | `bytes` | equal-length codewords |
| `deinterleave_codewords(data, depth)` | `list[bytes]` | inverse of the above |
| `mark_erasures(reliability, threshold, max_erasures=None)` | `list[int]` | indices with reliability < threshold; keeps the least reliable `max_erasures` |

## Channel models (simulation)

Deterministic for a given `seed`.

| Class | Constructor | `corrupt(data, seed)` returns |
|-------|-------------|-------------------------------|
| `SymbolErrorChannel` | `p ∈ [0, 1]` | `bytes` |
| `BurstErrorChannel` | `p_start, p_continue ∈ [0, 1)`; `mean_burst_length = 1/(1−p_continue)` | `bytes` |
| `ErasureChannel` | `p ∈ [0, 1]` | `(bytes, list[int])` |
