"""Reproducible benchmarks for the audp-ecm Python package.

Usage:
    python benchmarks/bench.py                 # full run, table on stderr, JSON on stdout
    python benchmarks/bench.py --quick         # shorter run (CI smoke)
    python benchmarks/bench.py --out results.json

Methodology
-----------
* Each operation is warmed up, then timed in ROUNDS rounds; every round calls
  the operation in a batch sized to take ~TARGET_MS, so timer resolution is
  negligible. Reported: median and min of the per-call time across rounds,
  and throughput = payload bytes / median time.
* Inputs are fixed and seeded (SEED), so runs are comparable across machines.
* Memory: Python-heap peak per call (tracemalloc, includes result objects) and
  the process's peak resident set size at the end of the run.
* Everything measured is the public API exactly as an application uses it.
* Stability: each result records spread = max/min across rounds; the run is
  flagged "noisy" if any spread exceeds 1.5 (thermal or power throttling,
  background load). Laptops on battery throttle under sustained load —
  benchmark on mains power or use the CI workflow (.github/workflows/benchmarks.yml).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import platform
import random
import statistics
import sys
import time
import tracemalloc

import audp_ecm as ecm

SEED = 20261020
CODES = [(16, 12), (32, 24), (64, 48), (128, 96), (255, 223)]


def cpu_name() -> str:
    try:
        if sys.platform.startswith("linux"):
            for line in open("/proc/cpuinfo", encoding="utf-8"):
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
        if sys.platform == "darwin":
            import subprocess
            return subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
        if sys.platform == "win32":
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    except Exception:
        pass
    return platform.processor() or "unknown"


def peak_rss_bytes() -> int | None:
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            pmc = PMC(); pmc.cb = ctypes.sizeof(PMC)
            k32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
            k32.GetCurrentProcess.restype = wintypes.HANDLE          # 64-bit pseudo-handle
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            if not psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
                return None
            return int(pmc.PeakWorkingSetSize)
        import resource
        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(r if sys.platform == "darwin" else r * 1024)
    except Exception:
        return None


def time_op(fn, rounds: int, target_ms: float) -> dict:
    for _ in range(50):
        fn()
    # calibrate batch size to ~target_ms
    batch, elapsed = 1, 0.0
    while elapsed < target_ms / 1000 and batch < 1 << 22:
        batch *= 2
        t0 = time.perf_counter()
        for _ in range(batch):
            fn()
        elapsed = time.perf_counter() - t0
    per_call = []
    for _ in range(rounds):
        t0 = time.perf_counter_ns()
        for _ in range(batch):
            fn()
        per_call.append((time.perf_counter_ns() - t0) / batch)
    return {"median_ns": statistics.median(per_call), "min_ns": min(per_call),
            "max_ns": max(per_call), "spread": max(per_call) / min(per_call),
            "batch": batch, "rounds": rounds}


def heap_per_call(fn, calls: int = 2000) -> int:
    tracemalloc.start()
    tracemalloc.reset_peak()
    base = tracemalloc.get_traced_memory()[0]
    for _ in range(calls):
        fn()
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    return max(0, peak - base)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out")
    args = ap.parse_args()
    rounds, target = (3, 15.0) if args.quick else (7, 50.0)
    rng = random.Random(SEED)
    results = []

    for n, k in CODES:
        rs = ecm.ReedSolomon(n, k)
        t = rs.t
        data = bytes(rng.getrandbits(8) for _ in range(k))
        cw = rs.encode(data)
        err = bytearray(cw)
        for i in range(t):                      # t errors, spread over the word
            err[(i * n) // t] ^= 0x5A
        err = bytes(err)
        eras_word = bytearray(cw)
        eras = list(range(n - k))               # full erasure budget
        for p in eras:
            eras_word[p] = 0
        eras_word = bytes(eras_word)
        assert rs.decode(err).data == data and rs.decode(eras_word, eras).data == data

        ops = {  # defaults bind this iteration's values explicitly
            "encode": lambda rs=rs, data=data: rs.encode(data),
            "decode_clean": lambda rs=rs, cw=cw: rs.decode(cw),
            "decode_t_errors": lambda rs=rs, err=err: rs.decode(err),
            "decode_full_erasures": lambda rs=rs, w=eras_word, e=eras: rs.decode(w, e),
        }
        for op, fn in ops.items():
            r = time_op(fn, rounds, target)
            r.update(code=f"RS({n},{k})", n=n, k=k, t=t, op=op,
                     payload_bytes=k, throughput_mb_s=k / r["median_ns"] * 1e3,
                     heap_peak_bytes=heap_per_call(fn, 500 if args.quick else 2000))
            results.append(r)

    # burst codec: 64-byte payload, burst of depth*t symbols injected
    codec = ecm.BurstCodec.for_burst(31, 23, payload_len=64, burst_len=16)
    payload = bytes(rng.getrandbits(8) for _ in range(64))
    tx = bytearray(codec.protect(payload))
    for i in range(10, 10 + codec.burst_tolerance):
        tx[i] ^= 0xC3
    tx = bytes(tx)
    assert codec.recover(tx) == payload
    for op, fn in {"burst_protect": lambda: codec.protect(payload),
                   "burst_recover_max_burst": lambda: codec.recover(tx)}.items():
        r = time_op(fn, rounds, target)
        r.update(code=f"BurstCodec(31,23,depth={codec.depth})", n=31, k=23, t=4, op=op,
                 payload_bytes=64, burst_symbols=codec.burst_tolerance,
                 throughput_mb_s=64 / r["median_ns"] * 1e3,
                 heap_peak_bytes=heap_per_call(fn, 500 if args.quick else 2000))
        results.append(r)

    report = {
        "suite": "audp-ecm python",
        "audp_ecm_version": ecm.__version__,
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu": cpu_name(),
        "cpu_count": os.cpu_count(),
        "seed": SEED,
        "mode": "quick" if args.quick else "full",
        "utc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "peak_rss_bytes": peak_rss_bytes(),
        "noisy": any(r["spread"] > 1.5 for r in results),
        "results": results,
    }
    out = json.dumps(report, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out + "\n")
    else:
        print(out)

    w = sys.stderr.write
    w(f"audp-ecm {report['audp_ecm_version']} · Python {report['python']} · {report['cpu']} · {report['platform']}\n")
    w(f"{'code':26} {'operation':24} {'median µs':>10} {'min µs':>9} {'MB/s':>8} {'heap B':>8}\n")
    for r in results:
        w(f"{r['code']:26} {r['op']:24} {r['median_ns']/1e3:10.2f} {r['min_ns']/1e3:9.2f} "
          f"{r['throughput_mb_s']:8.1f} {r['heap_peak_bytes']:8d}\n")
    rss = report["peak_rss_bytes"]
    w(f"peak RSS: {rss // 1024 if rss else 'n/a'} KiB\n")
    if report["noisy"]:
        w("WARNING: unstable timings (spread > 1.5x): check power/thermal state and rerun\n")


if __name__ == "__main__":
    main()
