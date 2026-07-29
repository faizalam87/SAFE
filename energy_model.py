#!/usr/bin/env python3
"""
Access-count energy model for the SAFE guard evaluation.

ChampSim has no energy model, so we estimate dynamic memory-hierarchy energy as
    E = sum_over_levels( accesses_level * energy_per_access_level ) + DRAM
using published per-access dynamic energies (CACTI-class SRAM + Micron DDR4).
The guard only ever REMOVES prefetches, so every access count is <= the
unguarded baseline; the energy delta is therefore a (near-)monotonic saving,
dominated by off-chip (DRAM) traffic because DRAM per-access energy is ~20-100x
that of on-chip caches.

Numbers below are per 64 B access, in nanojoules. They are documented so a
reviewer can swap in their own; the NORMALIZED result is robust to the exact
on-chip values because DRAM dominates. Cite the source you use in the paper.
"""
import os, re, sys, math

# ---- Per-access dynamic energy (nJ / 64 B access). Tunable & citable. --------
E = {
    "L1D":  0.10,   # ~48 KB L1D, CACTI-class 22 nm
    "L2C":  0.45,   # ~512 KB L2
    "LLC":  1.50,   # ~2 MB LLC slice
    "DRAM": 20.0,   # activate + rd/wr + I/O per 64 B, Micron DDR4-class
}

CONFIGS = ["no_prefetch", "ip_noguard", "ip_guard"]

# Regexes over a single-core (CPU 0) ChampSim stat dump.
PAT = {
    "IPC":       re.compile(r"CPU\s+0\s+cumulative IPC:\s+([0-9.]+)"),
    "L1D_ACC":   re.compile(r"L1D TOTAL\s+ACCESS:\s+(\d+)"),
    "L2C_ACC":   re.compile(r"L2C TOTAL\s+ACCESS:\s+(\d+)"),
    "LLC_ACC":   re.compile(r"LLC TOTAL\s+ACCESS:\s+(\d+)"),
    "LLC_MISS":  re.compile(r"LLC TOTAL\s+ACCESS:\s+\d+\s+HIT:\s+\d+\s+MISS:\s+(\d+)"),
    "POLL":      re.compile(r"L1D PREFETCH_POLLUTION_MISSES:\s+(\d+)"),
    "KILLED":    re.compile(r"L1D.*PF_KILLED_BY_HEAP_GUARD:\s+(\d+)"),
    "PF_USELESS":re.compile(r"L1D PREFETCH  REQUESTED:\s+\d+\s+ISSUED:\s+\d+\s+USEFUL:\s+\d+\s+USELESS:\s+(\d+)"),
}

def parse(path):
    d = {}
    if not os.path.exists(path):
        return None
    txt = open(path, errors="ignore").read()
    for k, pat in PAT.items():
        m = pat.search(txt)
        d[k] = float(m.group(1)) if m else 0.0
    if d.get("IPC", 0) == 0:            # run didn't finish
        return None
    return d

def energy_nJ(d):
    dram = d["LLC_MISS"]                # 1 DRAM access per LLC miss (read); WB extra but small
    return (d["L1D_ACC"] * E["L1D"] +
            d["L2C_ACC"] * E["L2C"] +
            d["LLC_ACC"] * E["LLC"] +
            dram         * E["DRAM"])

def geomean(xs):
    xs = [x for x in xs if x and x > 0]
    return math.exp(sum(math.log(x) for x in xs) / len(xs)) if xs else float("nan")

def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "probe_output"
    # Any extra args are substrings of benchmark names to EXCLUDE from the
    # aggregate (still listed, marked [excluded]). Transparency > cherry-picking.
    exclude = sys.argv[2:]
    try:
        benches = sorted(d for d in os.listdir(os.path.join(base, "no_prefetch"))
                         if os.path.isdir(os.path.join(base, "no_prefetch", d)))
    except FileNotFoundError:
        print(f"[error] {base}/no_prefetch not found"); return

    rows, e_ratio, ipc_ratio = [], [], []
    hdr = f"{'benchmark':<26} {'IPC_ng':>8} {'IPC_g':>8} {'IPC%':>7} | " \
          f"{'E_ng(nJ)':>12} {'E_g(nJ)':>12} {'E_g/ng':>7} | {'kills':>8} {'useless_ng':>10} {'useless_g':>9}"
    print(hdr); print("-" * len(hdr))
    for b in benches:
        g  = parse(os.path.join(base, "ip_guard",   b, f"{b}.txt"))
        ng = parse(os.path.join(base, "ip_noguard", b, f"{b}.txt"))
        if not g or not ng:
            print(f"{b:<26} (incomplete)"); continue
        eg, eng = energy_nJ(g), energy_nJ(ng)
        er = eg / eng if eng else float("nan")
        ir = g["IPC"] / ng["IPC"] if ng["IPC"] else float("nan")
        excl = any(x in b for x in exclude)
        if not excl:
            e_ratio.append(er); ipc_ratio.append(ir)
        tag = "  [excluded]" if excl else ""
        print(f"{b:<26} {ng['IPC']:>8.4f} {g['IPC']:>8.4f} {(ir-1)*100:>+6.2f}% | "
              f"{eng:>12.0f} {eg:>12.0f} {er:>7.4f} | {g['KILLED']:>8.0f} "
              f"{ng['PF_USELESS']:>10.0f} {g['PF_USELESS']:>9.0f}{tag}")
    print("-" * len(hdr))
    label = f"GeoMean (n={len(ipc_ratio)}" + (f", excl {len(exclude)})" if exclude else ")")
    print(f"{label:<26} {'':>8} {'':>8} {(geomean(ipc_ratio)-1)*100:>+6.2f}% | "
          f"{'':>12} {'':>12} {geomean(e_ratio):>7.4f} |")
    if exclude:
        print(f"Excluded (substr match): {exclude}")
    print(f"\nEnergy model (nJ/access): {E}")

if __name__ == "__main__":
    main()
