# Development

## Prerequisites

- Rust (stable) and Python ≥ 3.10
- Read access to the private core repository (build-time dependency)

## Build and test

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install "maturin>=1.15,<2" pytest hypothesis
maturin develop --release
pytest
```

The core is fetched by Cargo over git; with SSH or HTTPS credentials configured,
set `CARGO_NET_GIT_FETCH_WITH_CLI=true` so Cargo uses your git client.

Working against a local checkout of the core instead is described in
[CONTRIBUTING.md](../CONTRIBUTING.md). That override changes `Cargo.lock`
locally — **never commit the lockfile produced with the override** (`git checkout
Cargo.lock` before committing).

## Code quality gates

| Gate | Command |
|------|---------|
| Formatting | `cargo fmt --check` |
| Lints | `cargo clippy --release --locked -- -D warnings` |
| Rust advisories | `cargo audit` |
| Python advisories | `pip-audit --strict .` |
| Tests | `pytest` (functional, known-answer, misuse, thread-safety, Hypothesis properties) |

## Continuous integration (`.github/workflows/ci.yml`)

Runs on every push and pull request to `main` (and manually):

1. **Lint + audit** — rustfmt, clippy, `cargo audit`, `pip-audit`.
2. **Test matrix** — Linux, Windows, macOS × Python 3.10 / 3.12 / 3.13: build the
   extension and run the full test suite.

CI reads the private core through a read-only, single-repository deploy key
stored as an encrypted secret; it is never printed and never enters build
containers. Concurrent runs for the same ref are cancelled automatically.
