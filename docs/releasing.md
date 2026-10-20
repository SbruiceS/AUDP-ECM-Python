# Releasing (CD)

Pipeline: `.github/workflows/release.yml`.

```
tag v*  ─▶ verify version ─▶ build wheels (4 targets) ─▶ test every wheel (3 OS × 2 Python)
                                                         └─▶ GitHub Release  [environment: AUDP-ECM]
                                                               └─▶ PyPI       [environment: pypi, opt-in]
```

| Stage | What it checks or produces |
|-------|----------------------------|
| Verify version | the tag `vX.Y.Z` must equal `version` in `Cargo.toml` |
| Wheels | abi3 wheels: Linux x86_64 + aarch64 (manylinux), Windows x64, macOS universal2; built offline from vendored sources |
| Test wheels | installs the **built wheel** (`--only-binary`, no source build) and runs the full test suite |
| GitHub Release | wheels + `SHA256SUMS` + signed build-provenance attestations; runs in the protected `AUDP-ECM` environment (tags `v*` only) |
| PyPI | Trusted Publishing (OIDC, no stored token); runs only when the repository variable `PYPI_PUBLISH` is `true` |

## Dry run

**Actions → Release → Run workflow** builds and tests every wheel without creating a
release or uploading anything. Run it before tagging.

## Cutting a release

```bash
# 1. bump version in Cargo.toml, update the core pin if needed, commit
# 2. tag and push
git tag -s v0.2.1 -m "audp-ecm 0.2.1"     # or -a if you do not sign tags
git push origin v0.2.1
```

## Enabling PyPI (one time)

1. On pypi.org → *Your account → Publishing → Add a new pending publisher*:

   | Field | Value |
   |-------|-------|
   | PyPI project name | `audp-ecm` |
   | Owner | `SbruiceS` |
   | Repository | `AUDP-ECM-Python` |
   | Workflow | `release.yml` |
   | Environment | `pypi` |

2. `gh variable set PYPI_PUBLISH --body true --repo SbruiceS/AUDP-ECM-Python`

Until then, tags still produce a complete GitHub Release.

## Verifying a release

```bash
sha256sum -c SHA256SUMS
gh attestation verify audp_ecm-*.whl --repo SbruiceS/AUDP-ECM-Python
```
