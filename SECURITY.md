# Security policy

## Scope

`audp-ecm` corrects channel noise; it does **not** provide authenticity or
confidentiality. In scope: crashes, panics, memory unsafety, unbounded
resource use, incorrect results, or exceptions escaping the documented
hierarchy for any Python input.

## Supported versions

The latest minor release receives security fixes.

## Reporting

Please do **not** open a public issue. Use GitHub's private vulnerability
reporting (Security → "Report a vulnerability") on this repository, or email
**sbruicesingh@haclon.in**. Include version, platform, and a reproducer.
Expect an acknowledgement within 5 working days.

## Hardening

See "Security properties" in [README.md](README.md). Core-library issues are
handled under the core repository's policy and fixed here by bumping the
pinned core commit.
