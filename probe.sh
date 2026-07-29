#!/bin/bash
# Single-core probe: guard vs noguard vs no_prefetch across the paper's workloads.
# Short (warmup 5M / sim 20M) to find which benchmarks the guard actually moves.
set -u
cd "$(dirname "$0")"

TR=${TRACES_DIR:-./trace}
OUT=probe_output
WARM=5000000
SIM=20000000
MAXJOBS=${MAXJOBS:-8}

BENCHES=(
  602.gcc_s-734B 605.mcf_s-472 605.mcf_s-484B 605.mcf_s-665B 605.mcf_s-994B
  623.xalancbmk_s-10B 623.xalancbmk_s-165B 623.xalancbmk_s-202B
  623.xalancbmk_s-325B 623.xalancbmk_s-592B 623.xalancbmk_s-700B
  625.x264_s-12B 625.x264_s-18B 625.x264_s-20B 625.x264_s-33B 625.x264_s-39B
  628.pop2_s_17B 641.leela_s-149B 648.exchange2_s-72B 649.fotonik3d_s-1B
  654.roms_s_293B 654.roms_s_294B 654.roms_s_523B 657.xz_s-56B
)

n=0
for b in "${BENCHES[@]}"; do
  t="$TR/$b.trace.xz"
  [[ -f "$t" ]] || { echo "[skip] missing $t"; continue; }
  for v in ip_guard_sc ip_noguard_sc no_prefetch_sc; do
    cfg="${v%_sc}"                       # ip_guard_sc -> ip_guard
    mkdir -p "$OUT/$cfg/$b"
    ./bin/$v -warmup_instructions "$WARM" -simulation_instructions "$SIM" \
        -traces "$t" > "$OUT/$cfg/$b/$b.txt" 2>&1 &
    ((++n)); (( n % MAXJOBS == 0 )) && wait -n
  done
done
wait
echo "PROBE DONE: $OUT"
