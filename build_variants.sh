#!/bin/bash
# Build the three SAFE evaluation binaries from IDENTICAL source.
#   bin/ip_guard     : IP-stride prefetcher + object-bound guard  (-DHEAP_GUARD)
#   bin/ip_noguard   : IP-stride prefetcher, guard compiled out   (no flag)
#   bin/no_prefetch  : no L1D prefetcher (baseline)
#
# The guard vs. no-guard binaries differ ONLY by the -DHEAP_GUARD compile flag,
# so any measured difference is attributable to the guard alone.
set -e
cd "$(dirname "$0")"

# System config (matches Table II): hashed-perceptron BP, SRRIP L2, DRRIP LLC.
BP=hashed_perceptron
L2REPL=srrip
LLCREPL=drrip
NUM_CORE=${NUM_CORE:-4}   # run.sh runs 4-trace mixes
BINSUFFIX=${BINSUFFIX:-}  # e.g. "_sc" for single-core binaries (bin/ip_guard_sc)

# build_champsim.sh arg order:
# [branch] [l1i] [l1d] [l2c] [llc] [itlb] [dtlb] [stlb] \
# [btb_repl] [l1i_repl] [l1d_repl] [l2c_repl] [llc_repl] [itlb_repl] [dtlb_repl] [stlb_repl] [num_core] [tail]
build() {
  local l1d_pref="$1" tail="$2"
  echo "=================================================================="
  echo ">>> Building variant: $tail  (L1D pref=$l1d_pref, EXTRA_CFLAGS='$EXTRA_CFLAGS')"
  echo "=================================================================="
  ./build_champsim.sh "$BP" no "$l1d_pref" no no no no no \
      lru lru lru "$L2REPL" "$LLCREPL" lru lru lru "$NUM_CORE" "$tail"
}

mkdir -p bin

# 1) SAFE guarded build
EXTRA_CFLAGS="-DHEAP_GUARD" build ip_stride guard
mv -f bin/*-"${NUM_CORE}core-guard" "bin/ip_guard${BINSUFFIX}"

# 2) Unguarded baseline (same prefetcher, guard compiled out)
EXTRA_CFLAGS="" build ip_stride noguard
mv -f bin/*-"${NUM_CORE}core-noguard" "bin/ip_noguard${BINSUFFIX}"

# 3) No-prefetch baseline
EXTRA_CFLAGS="" build no noprefetch
mv -f bin/*-"${NUM_CORE}core-noprefetch" "bin/no_prefetch${BINSUFFIX}"

echo
echo "Built binaries:"
ls -la "bin/ip_guard${BINSUFFIX}" "bin/ip_noguard${BINSUFFIX}" "bin/no_prefetch${BINSUFFIX}"
