# Security model

## Scope

Error correction protects against **channel noise**, not against attackers. CRC-16
and Reed–Solomon can be forged trivially; use a MAC or AEAD for integrity and
authenticity. In scope for this package: memory safety, crashes, resource
exhaustion, incorrect results and exceptions outside the documented hierarchy,
for **any** Python input.

## Guarantees

| Property | How it is enforced |
|----------|--------------------|
| No memory unsafety in the binding | `#![forbid(unsafe_code)]`; all FFI handled by PyO3 |
| No Rust panic reachable from Python | parameters validated before reaching code that asserts; typed exceptions instead |
| Thread safety | every class is immutable (`frozen`); objects can be shared freely |
| No time-of-check/time-of-use on buffers | mutable inputs snapshotted to `bytes` before the GIL is released |
| Bounded resources | inputs ≤ `MAX_INPUT_BYTES`; depth ≤ `MAX_DEPTH`; erasure lists ≤ number of symbols |
| Verified results | a decode is returned only after syndrome (and, for `BurstCodec`, CRC) verification |
| Arithmetic | release builds keep integer overflow checks enabled |

Miscorrection — decoding to a *different* valid codeword when errors exceed the
correction capability — is inherent to all error-correcting codes. `BurstCodec`
adds a CRC-16 to make it unlikely (≈ 2⁻¹⁶) to go unnoticed.

## Supply chain

- Zero runtime Python dependencies.
- Rust dependencies pinned by `Cargo.lock`; audited in CI with `cargo audit`.
- Declared Python dependencies audited with `pip-audit --strict`.
- GitHub Actions use least-privilege `permissions`; checkout never persists credentials.
- Release wheels carry SHA-256 checksums and signed build-provenance attestations;
  PyPI uploads use Trusted Publishing (no stored API token).
- Dependency and action updates are proposed weekly by Dependabot and reviewed
  before being applied.

## Reporting a vulnerability

Use GitHub private vulnerability reporting (**Security → Report a vulnerability**)
or email **sbruicesingh@haclon.in**. Please do not open a public issue.
Acknowledgement within 5 working days.
