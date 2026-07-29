# SAFE Guard — Session Report (2026-07-24)

Work on the object-bound prefetcher guard (SAFE).
Goal you set: verify the guard is implemented correctly, sanity-check it, and
improve the (flat) results — with a target framing of "security speeds things up
+ uses less energy."

---

## 1. What was broken

- **guard vs no-guard binaries were hand-edited, not flag-controlled.** The guard
  in `src/cache.cc::prefetch_line` (`same_heap_object`) has **no build gating** —
  it's active whenever `btc != nullptr`, which is true for every L1D. So
  `ip_guard` and `ip_noguard` could easily be built identical, making every
  normalized metric ≈ 1.0. This matches the paper's Fig 5/6 (GeoMean 0.995 /
  1.00002 — i.e. no measurable difference).
- **Hidden handicap in the guarded build:** `btc_delay` (1 cyc on BTC hit, **50
  on miss**) was added to every guarded prefetch's `event_cycle` (`cache.cc`),
  and 0 in the baseline — so the guard paid a latency tax the baseline didn't,
  contradicting the paper's "parallel/off-critical-path check" (Fig 4).
- **`run.sh` was not actually running** at session start (only a stopped `vim`).
- **Single global `live_heap`** shared across all 4 cores (paper specifies a
  *per-process* bound table) → cross-core contamination in multi-core runs.

## 2. Architecture (how the guard actually works — not what the figures imply)

- Guard: `src/cache.cc::prefetch_line` (~L3870) → `same_heap_object(demand_addr,
  pf_addr)` in `src/ooo_cpu.cc:51`.
- Uses oracle `std::map live_heap` (ooo_cpu.cc:26), filled from trace alloc
  records (AllocType 1=malloc, 2=free, 3=live-at-skip snapshot; ooo_cpu.cc ~L360).
- Policy (**strict**): demand not in a heap object → ALLOW; pf in *same* object →
  ALLOW; else → KILL. (A "secondary check" allowing pf into *another live object*
  is present but **commented out**, ooo_cpu.cc:90–100 = the "relaxed" policy.)
- `BoundTableCache` (inc/cache.h) is a **timing model only**; the kill uses the
  oracle map, not BTC contents.
- The `ip_stride.l1d_pref` prefetcher already **confines prefetches to the same
  4 KB page** (~L112), so the guard only ever fires on *intra-page inter-object*
  crossings.

## 3. Changes made this session

| File | Change |
|---|---|
| `Makefile` | Added `CFlags += $(EXTRA_CFLAGS)` so a macro can be injected from env |
| `src/cache.cc` | Gated the guard block with `#ifdef HEAP_GUARD`; set `btc_delay=0` (bound check modeled off critical path, per Fig 4); kept BTC hit/miss accounting |
| `build_variants.sh` | **NEW** — builds `ip_guard` (`-DHEAP_GUARD`), `ip_noguard` (no flag), `no_prefetch` from identical source. Env: `NUM_CORE` (def 4), `BINSUFFIX` (e.g. `_sc`). Config = Table II (hashed_perceptron BP, srrip L2, drrip LLC). |
| `probe.sh` | **NEW** — single-core, warmup 5M / sim 20M, all traces × 3 variants → `probe_output/`. |
| `energy_model.py` | **NEW** — access-count energy proxy (Σ accesses×nJ + DRAM); per-bench + GeoMean; optional exclude args. |
| `metrics.py` | **NEW** — richer table: IPC ratio, prefetch accuracy, pollution, DRAM/off-chip traffic, energy, EDP, "% of prefetcher benefit retained". |

Binaries built (all from identical source): `bin/ip_guard`, `bin/ip_noguard`,
`bin/no_prefetch` (4-core) and `bin/*_sc` (single-core, used for the probe).

**Flag verified working:** guarded build reports `BTC_HITS/MISSES > 0` and
`PF_KILLED_BY_HEAP_GUARD > 0`; unguarded reports `0/0` and `0`.

## 4. Experiments run

- 4-core sanity (xalancbmk+mcf mix, 1M/5M): confirmed the flag now makes
  guard≠noguard, guard fires only on xalancbmk (small objects), 0 kills on mcf.
- **Single-core probe, 34 SPEC17 traces × 3 variants (warmup 5M / sim 20M).**
  Results in `probe_output/`. Rerun analysis with:
  `python3 metrics.py probe_output` and `python3 energy_model.py probe_output`.

## 5. Key findings

### (a) The energy story is real and clean (recommend as headline)
Because the guard **only removes prefetches**, every access count ≤ baseline, so
energy/traffic are (near-)monotonic savings, dominated by off-chip DRAM.
- Off-chip/DRAM traffic: GeoMean **0.988 (−1.2%)**, up to **−14%** (xalancbmk_s),
  **−9%** (leela-149B, xalancbmk-700B).
- Dynamic energy: GeoMean **0.994 (−0.6%)**, up to **−4.6%**.
- L1D pollution misses: large drops (e.g. xalancbmk_s 22,185→3,383).

### (b) The "speedup" claim is NOT supportable
- Excluding outliers, IPC GeoMean is **−0.06% (flat)** — no speedup. Prefetch
  hits are largely L2-absorbed, so pollution cleanup doesn't unblock the core.
- **Two workloads regress catastrophically:** `xalancbmk-165B` **−35% IPC**,
  `xalancbmk-202B` **−32%**. Root cause is NOT a bug: these phases stream
  contiguously across many tiny (~165 B ≈ 2.6-line) heap objects, so **every
  useful stride prefetch crosses an object boundary**. Strict enforcement kills
  them all (`ISSUED: 0`, useful 344K→0), and guard-IPC drops to *exactly*
  no-prefetch IPC (0.458173 == 0.458173). This is the fundamental
  **security ↔ performance tradeoff**, worst precisely in the many-small-objects
  case the paper highlights as the key security threat (#3).
- These two outliers alone drag the all-in aggregates: IPC 0.976, EDP 1.019
  (worse). Don't lead with IPC or EDP.

### (c) Best honest framing
"SAFE enforces object bounds (blocks ShadowLoad-style out-of-bounds prefetch),
reduces off-chip traffic up to 14% and energy up to 4.6%, and **preserves IPC
within noise on 32/34 workloads**. On tiny-object-intensive phases, strict
enforcement necessarily forgoes prefetch benefit — the characterized cost of the
guarantee." Lead with **traffic/energy/pollution**; report IPC as "no slowdown
except the two characterized cases."

## 6. Open decision (was mid-discussion when you left)

**Guard policy fork** for the two regressions (and the security thesis):
1. **Strict (current):** never cross an object. Full inter-object security; costs
   perf on small-object workloads. → drop speedup claim, keep security + energy.
2. **Relaxed:** enable the commented-out secondary check (allow pf into any *live*
   object). Recovers perf, but security weakens to "no prefetch into
   unmapped/freed/non-heap" — can't claim finest-grain inter-object protection
   (leaks between co-located live objects = threat #3).
3. **Smarter middle policy** (e.g. same size-class / adjacency) — more work.

## 7. Suggested next steps

- [ ] **Measure the killed-prefetch destinations on 165B/202B** (land in another
      *live* object vs *unmapped* memory) → tells us if the relaxed policy is
      viable and quantifies residual security. (Data-driven version of the fork.)
- [ ] Decide the policy fork (§6) — this sets the paper's thesis.
- [ ] Fix `live_heap` to be **per-cpu** if keeping multi-core runs.
- [ ] Longer runs (warmup 50M / sim 200M) on the workloads that move, for
      paper-grade numbers.
- [ ] Regenerate Fig 5/6 from `metrics.py` (traffic/energy/pollution as the win).
- [ ] Sensitivity: `PREFETCH_DEGREE` (currently 3) and `MASK_IP` (0xFF) both
      affect how often the guard fires.

## 8. How to reproduce
```
NUM_CORE=1 BINSUFFIX=_sc ./build_variants.sh   # single-core binaries
./probe.sh                                     # -> probe_output/
python3 metrics.py probe_output                # rich metric table
python3 energy_model.py probe_output           # energy table
# exclude outliers to see the distribution:
python3 metrics.py probe_output 623.xalancbmk_s-165B 623.xalancbmk_s-202B
```
Traces: `./fetch_traces.sh` (see README). They are malloc/free-instrumented and
cannot be substituted with the public DPC3/SPEC17 traces.
