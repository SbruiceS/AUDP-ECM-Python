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

> The override rewrites `Cargo.lock` to local paths. Run `git checkout Cargo.lock`
> before committing — CI uses `--locked` and fails on a path-based lockfile.

## Bumping the core

1. Update every `rev = "…"` in `Cargo.toml` to the new core commit.
2. `cargo update -p ecm-kernels` and commit `Cargo.lock`.
3. Run `cargo clippy -- -D warnings`, `maturin develop --release`, `pytest`.

## CI secret

The core repository is private. CI uses the secret **`CORE_DEPLOY_KEY`**: the
private half of an SSH **read-only deploy key** registered on
`SbruiceS/AUDP-ECM` only. GitHub's host key is pinned in the workflows
(`StrictHostKeyChecking=yes`). Release builds vendor all sources on the host
and delete the key before the manylinux/cross containers run, so the key
never enters a build container. To rotate it, add a new read-only deploy key
on the core, replace the secret in this repo and `AUDP-ECM-D`, then delete
the old key.

## Rules

- No `unsafe` (enforced by `#![forbid(unsafe_code)]`).
- Validate every parameter before calling core code that asserts.
- Every new API needs tests in `tests/` (functional + misuse cases).
