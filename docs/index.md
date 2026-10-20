# audp-ecm for Python — technical documentation

| Document | Contents |
|----------|----------|
| [api.md](api.md) | Complete API reference with types, errors and examples |
| [security.md](security.md) | Threat model, guarantees, limits, reporting |
| [development.md](development.md) | Building from source, tests, CI pipeline |
| [releasing.md](releasing.md) | CD pipeline, versioning, PyPI Trusted Publishing, verifying releases |

## What the package does

`audp-ecm` adds forward error correction to telemetry and sensor links:

| Capability | API |
|------------|-----|
| Reed–Solomon over GF(256): corrects `e` unknown symbol errors and `s` known erasures whenever `2e + s ≤ n − k` | `ReedSolomon` |
| Burst-resilient framing: exact-length payload, corrects any contiguous burst of up to `depth · t` symbols | `BurstCodec` |
| Binary BCH (bit level) | `BchCode` |
| CRC-16/CCITT-FALSE (detection) | `crc16`, `append_crc16`, `verify_crc16` |
| GF(256) arithmetic (irreducible 0x11D) | `gf_mul`, `gf_inv`, `gf_pow` |
| Soft information → erasures | `mark_erasures` |
| Seeded channel models for simulation | `SymbolErrorChannel`, `BurstErrorChannel`, `ErasureChannel` |

It is **not cryptography**: none of these mechanisms authenticate data or resist a
deliberate attacker. Combine with a MAC/AEAD where integrity matters.

## Compatibility

| Item | Supported |
|------|-----------|
| Python | CPython ≥ 3.10 (one `abi3` wheel per platform) |
| Platforms (wheels) | Linux x86_64 / aarch64 (manylinux), Windows x64, macOS universal2 |
| Runtime dependencies | none |
| Thread safety | all objects are immutable; safe to share; the GIL is released while coding |

## Minimal example

```python
import audp_ecm as ecm

rs = ecm.ReedSolomon(31, 23)                 # t = 4
cw = rs.encode(bytes(23))
rx = bytearray(cw); rx[3] ^= 0xFF            # one corrupted symbol
assert rs.decode(rx).data == bytes(23)

codec = ecm.BurstCodec.for_burst(31, 23, payload_len=64, burst_len=16)
tx = codec.protect(b"node=17;temp=21.7")
assert codec.recover(tx) == b"node=17;temp=21.7"
```
