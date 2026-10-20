# Contributing

## Building against a local core checkout

The core is pinned by commit in `Cargo.toml`. To develop against a sibling
checkout instead, create a **gitignored** `.cargo/config.toml`:

```toml
[net]
git-fetch-with-cli = true

[patch."https://github.com/SbruiceS/AUDP-ECM"]
ecm-kernels = { path = "../AUDP-ECM/crates/ecm-kernels" }
ecm-algebraic-codes = { path = "../AUDP-ECM/crates/ecm-algebraic-codes" }
ecm-core = { path = "../AUDP-ECM/crates/ecm-core" }
ecm-probabilistic = { path = "../AUDP-ECM/crates/ecm-probabilistic" }
ecm-finite-fields = { path = "../AUDP-ECM/crates/ecm-finite-fields" }
ecm-polynomials = { path = "../AUDP-ECM/crates/ecm-polynomials" }
ecm-graph-codes = { path = "../AUDP-ECM/crates/ecm-graph-codes" }
```

## Bumping the core

1. Update every `rev = "…"` in `Cargo.toml` to the new core commit.
2. `cargo update -p ecm-kernels` and commit `Cargo.lock`.
3. Run `cargo clippy -- -D warnings`, `maturin develop --release`, `pytest`.

## CI secret

The core repository is private. CI needs a secret **`CORE_REPO_TOKEN`**: a
fine-grained personal access token with **read-only "Contents"** access to
`SbruiceS/AUDP-ECM` only. It is used solely to fetch the pinned core commit.

## Rules

- No `unsafe` (enforced by `#![forbid(unsafe_code)]`).
- Validate every parameter before calling core code that asserts.
- Every new API needs tests in `tests/` (functional + misuse cases).
