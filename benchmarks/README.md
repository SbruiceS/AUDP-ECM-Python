# Benchmarks

`bench.py` measures the public API exactly as applications use it.

```bash
python benchmarks/bench.py                 # full run: table on stderr, JSON on stdout
python benchmarks/bench.py --quick         # short smoke run
python benchmarks/bench.py --out out.json  # write JSON to a file
```

## What is measured

| Operation | Input |
|-----------|-------|
| `encode` | `k` random data bytes |
| `decode_clean` | an error-free codeword |
| `decode_t_errors` | exactly `t = (n − k)/2` symbol errors, spread over the word |
| `decode_full_erasures` | `n − k` erased symbols with their positions supplied |
| `burst_protect` / `burst_recover_max_burst` | 64-byte payload over RS(31,23), one contiguous burst of `depth·t` symbols |

Codes: RS(16,12), RS(32,24), RS(64,48), RS(128,96), RS(255,223). Inputs are seeded
(`SEED = 20261020`).

## Method

- Warm-up, then 7 rounds (3 with `--quick`); each round calls the operation in a batch
  sized to about 50 ms, so timer resolution is negligible.
- Reported per operation: median and minimum per-call time across rounds, throughput
  (`k` payload bytes ÷ median), and `spread` (max ÷ min).
- Memory: Python-heap peak per call (`tracemalloc`, including result objects) and the
  process's peak resident set size.
- **Stability:** a run is flagged `noisy` when any spread exceeds 1.5×. Laptops on
  battery or under thermal limits throttle during sustained runs. Benchmark on mains
  power, or use CI.

## Reproducible runs in CI

**Actions → Benchmarks → Run workflow**, then choose a release tag. The workflow
downloads that release's published wheels, verifies `SHA256SUMS`, and runs the suite on
Linux x86_64, Linux aarch64, Windows x64 and macOS arm64. It uploads the JSON results and
writes a summary table on the run page.
