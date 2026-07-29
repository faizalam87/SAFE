# SAFE — an object-bound guard for hardware prefetchers

SAFE confines an L1D prefetcher to the heap object its triggering access already
touched. A stride prefetcher happily walks past the end of a `malloc`'d buffer
into whatever is allocated next; that out-of-bounds prefetch is both a
ShadowLoad-style side-channel primitive (see [Security model](#security-model))
and a source of cache pollution. SAFE checks the candidate prefetch address
against the bounds of the demand access's object and drops it if it would cross
out.

Built on [ChampSim](https://github.com/ChampSim/ChampSim), evaluated on
malloc/free-instrumented SPEC CPU2017 traces.

**Result in one line:** the guard eliminates ~53% of useless prefetches and cuts
off-chip traffic by up to 9%, with IPC within 1% of the unguarded baseline on 22
of 24 benchmarks — see [Results](#results) for the two where it costs more, and
why.

---

## Requirements

- Linux, `g++` with C++11 support (the upstream artifact used GCC 7.5)
- `make`, and Python 3 for the analysis scripts (stdlib only — no pip installs)
- `curl` + `sha256sum` to fetch traces
- ~3 GB disk for traces, plus room for simulator output

---

## Quick start

```bash
# 1. Get the instrumented traces (~2.8 GB) into ./trace
./fetch_traces.sh

# 2. Build the three single-core variants into ./bin
NUM_CORE=1 BINSUFFIX=_sc ./build_variants.sh

# 3. Run the sweep (24 benchmarks x 3 variants, 5M warmup / 20M sim)
./probe.sh                       # -> probe_output/

# 4. Read the results
python3 metrics.py probe_output          # accuracy, pollution, traffic, energy, EDP
python3 energy_model.py probe_output     # energy table with GeoMean
```

`probe.sh` runs 8 simulations concurrently by default (`MAXJOBS=8`). The full
sweep is 72 runs; budget a few hours on a typical server.

To see the distribution without the two known small-object outliers:

```bash
python3 metrics.py probe_output 623.xalancbmk_s-165B 623.xalancbmk_s-202B
```

### Multi-core

`run.sh` sweeps 4-trace mixes (5M warmup / 200M sim). Build without the
single-core overrides first — `NUM_CORE` defaults to 4 and `BINSUFFIX` to empty,
which is what `run.sh` expects:

```bash
./build_variants.sh              # -> bin/ip_guard, bin/ip_noguard, bin/no_prefetch
./run.sh                         # -> temp_output/
python3 final_result_parse.py    # per-CPU cumulative IPC
```

Uncommenting more entries in `run.sh`'s `BENCHES` array grows the run
combinatorially — 14 active benchmarks is 1001 mixes x 3 variants.

---

## The three binaries

`build_variants.sh` produces all three **from identical source**, so any measured
difference is attributable to the guard alone:

| Binary | L1D prefetcher | Guard | Purpose |
|---|---|---|---|
| `bin/ip_guard` | IP-stride | **on** (`-DHEAP_GUARD`) | SAFE |
| `bin/ip_noguard` | IP-stride | off | unguarded baseline |
| `bin/no_prefetch` | none | — | no-prefetch floor |

The guard is a compile-time flag, not a source edit. This matters: an earlier
version of this work hand-edited the two binaries and they sometimes came out
identical, which silently produced "no difference" results.

Fixed system config (all variants): hashed-perceptron branch predictor, SRRIP L2,
DRRIP LLC. Override `NUM_CORE` / `BINSUFFIX` via environment.

---

## How the guard works

```
prefetch candidate (base_addr -> pf_addr)
        |
        v
  same_heap_object(base_addr, pf_addr)      src/ooo_cpu.cc
        |
        +-- base_addr not on the heap? ------------> ALLOW
        +-- pf_addr within [start, end] of base? --> ALLOW
        +-- otherwise -----------------------------> KILL
```

- **Kill site:** `src/cache.cc`, inside `prefetch_line`, under `#ifdef HEAP_GUARD`.
  Killed prefetches increment `pf_killed_by_heap_guard`, reported as
  `PF_KILLED_BY_HEAP_GUARD` in the stat dump.
- **Bounds source:** the global `live_heap` map in `src/ooo_cpu.cc`, populated
  from allocation records carried in the traces (`AllocType` 1=malloc, 2=free,
  3=live-at-skip). Bounds are byte-granular with an inclusive end.
- **`BoundTableCache`** (`inc/cache.h`) models the lookup structure's hit/miss
  behaviour and occupancy. It is a **timing model only** — the kill decision uses
  the oracle `live_heap`, not BTC contents.
- **Latency:** `btc_delay` is 0. The bound check is modeled as running in
  parallel with the L1 TLB lookup, i.e. off the critical path, so it adds no
  latency to either variant.

The current policy is **strict**: a prefetch into a *different* heap object is
killed. `same_heap_object()` contains a commented-out secondary check that would
also allow prefetches landing in some other live heap object — this recovers the
performance lost on small-object workloads but weakens the security guarantee.
See [Results](#results).

---

## Results

From the single-core sweep (`probe.sh`, 24 benchmarks, 5M warmup / 20M sim),
guard vs. unguarded baseline. The guard actually fires on **13 of 24**; the rest
have too few or too large heap objects for any prefetch to cross a boundary, and
sit at exactly 1.0000 on every metric.

| Metric | All 24 | Excl. 2 outliers (22) | Best case |
|---|---|---|---|
| Off-chip / DRAM traffic | **0.9893** | 0.9886 | −9.3% xalancbmk-700B, −9.2% leela-149B |
| Energy | **0.9931** | 0.9946 | −4.0% leela-149B, −3.4% xalancbmk-700B |
| Useless prefetches (total) | **−52.6%** | −51.3% | −96% xalancbmk-10B (11671 → 419) |
| Pollution misses (total) | −31.3% | −11.9% | −93% xalancbmk-165B |
| IPC | 0.9657 | **0.9994** | 22/24 within 1%, 20/24 within 0.5% |

**The honest framing is security + energy/traffic, not speedup.** IPC is
preserved — not improved — on 22 of 24 benchmarks, and two regress hard:
`623.xalancbmk_s-165B` (−35%) and `-202B` (−32%). Those two are the entire
reason the all-24 IPC GeoMean reads 0.9657; without them it is 0.9994.

That regression is characterized, not a bug. Those phases stream through ~165-byte
objects laid out contiguously, so essentially every useful stride prefetch crosses
an object boundary and the strict guard kills it — the guarded IPC lands exactly
on the no-prefetch IPC, with `ISSUED: 0`. It is the real security/performance
tradeoff of a strict object bound, and the relaxed secondary check is the knob
that trades one for the other.

The guard only ever *removes* prefetches, so every cache and DRAM access count is
≤ baseline; the energy delta is a near-monotonic saving. Energy is an
access-count proxy (ChampSim has no energy model) — per-access nJ constants are
documented and tunable at the top of `energy_model.py`, and the *normalized*
result is robust to them because DRAM dominates.

Full writeup, including the diagnosis of earlier flat results, is in
[`SAFE_SESSION_REPORT.md`](SAFE_SESSION_REPORT.md).

---

## Traces

> **The public DPC-3 / SPEC17 ChampSim traces will not work.**

These traces were regenerated with the Pin tool in `tracer/champsim_tracer.cpp`
and carry heap allocation records alongside the usual instruction records. Those
records are what populate `live_heap`. Run SAFE on a public trace and the heap
map is empty, so the guard never fires and you measure nothing.

The 25 traces total ~2.8 GB and 18 exceed GitHub's 100 MB per-file limit, so they
ship as **Release assets** rather than git objects:

```bash
./fetch_traces.sh                              # download + verify into ./trace
TRACE_REPO=<owner>/<repo> ./upload_traces.sh   # (maintainer) publish ./trace
```

`fetch_traces.sh` defaults to the `traces-v1` release of this repo; override with
`TRACE_REPO` / `TRACE_TAG` if you host them elsewhere. **The release is not
published yet** — until a maintainer runs `upload_traces.sh`, the download will
404 and you will need to supply the traces yourself.

`trace/SHA256SUMS` is tracked in git and is both the checksum manifest and the
authoritative list of shipped traces — `fetch_traces.sh` derives its download
list from it, so the two cannot drift. It lists 25 traces; `probe.sh` runs 24 of
them (`605.mcf_s-782B` is fetched but not in its `BENCHES` array). Both `probe.sh` and `run.sh`
default to `./trace` and honour `TRACES_DIR` as an override.

Regenerating traces from scratch requires Pin 3.2 and the tracer in `tracer/`;
see the [upstream ChampSim tracing docs](https://github.com/ChampSim/ChampSim).

---

## Security model

The attack SAFE targets is a prefetcher-based cross-object leak: an attacker
arranges for a victim's stride-predictable access pattern to run off the end of
its object, causing the prefetcher to pull a *neighbouring* allocation into the
cache. The attacker then times that line to learn something about data it never
issued a load for. Bounding prefetches to the triggering object removes the
primitive.

Scope and caveats, stated plainly:

- Bounds come from an **oracle** (`live_heap`, from trace records), not from a
  real hardware bounds-tracking mechanism. The BTC models what looking those
  bounds up would cost; it does not supply them. A silicon design needs a real
  bounds source — tagged pointers, a memory-safety ISA extension, or a
  compiler-maintained table.
- The guard covers **heap** objects. Accesses whose base is not in `live_heap` —
  stack, globals, code — are allowed through unchecked.
- The IP-stride prefetcher confines prefetches to a single 4 KB page, so in
  practice the guard only ever fires on *intra-page* inter-object crossings.
- `live_heap` is a single global map. Under multi-core runs all cores share it;
  a real design would keep it per-process.

---

## Layout

```
src/            ChampSim core; cache.cc holds the guard kill site
inc/            headers; cache.h defines BoundTableCache
prefetcher/     L1D/L2C/LLC prefetchers (ip_stride.l1d_pref is the guarded one)
replacement/    cache replacement policies
branch/         branch predictors
tracer/         Pin tool that emits alloc-record-carrying traces
scripts/        upstream ChampSim helper scripts
trace/          SHA256SUMS manifest; traces land here after fetch_traces.sh

build_variants.sh       build all three variants from identical source
build_champsim.sh       upstream builder (18 args; build_variants.sh wraps it)
probe.sh                single-core sweep  -> probe_output/
run.sh                  4-core mix sweep   -> temp_output/
metrics.py              rich metric table from probe_output/
energy_model.py         access-count energy model from probe_output/
final_result_parse.py   per-CPU IPC from temp_output/
```

Build output (`bin/`, `obj/`), simulator dumps (`probe_output/`, `temp_output/`),
and traces are gitignored — all regenerable from the above.

---

## License

ChampSim and this fork are distributed under the terms in [`LICENSE`](LICENSE).
This work builds on the [Berti artifact](https://github.com/agusnt/Berti-Artifact).
