#!/bin/bash
# Download the malloc/free-instrumented ChampSim traces used by probe.sh / run.sh.
#
# These traces are NOT the public DPC3/SPEC17 traces. They were regenerated with
# the Pin tool in tracer/champsim_tracer.cpp and additionally carry heap alloc
# records (AllocType 1=malloc, 2=free, 3=live-at-skip) that populate live_heap
# for the object-bound guard. The public SPEC17 traces have no alloc records,
# so the guard would never fire on them.
#
# They ship as GitHub Release assets rather than git objects: 18 of the 25 files
# exceed GitHub's 100 MB hard per-file limit, and the set totals ~2.8 GB.
#
# Usage:
#   ./fetch_traces.sh                      # uses TRACE_REPO/TRACE_TAG defaults
#   TRACE_REPO=me/my-repo ./fetch_traces.sh
#   TRACE_TAG=traces-v2 ./fetch_traces.sh
set -uo pipefail
cd "$(dirname "$0")"

TRACE_REPO=${TRACE_REPO:-faizalam87/SAFE}
TRACE_TAG=${TRACE_TAG:-traces-v1}
DEST=${DEST:-./trace}

if [[ $TRACE_REPO == REPLACE_ME/* ]]; then
  cat >&2 <<EOF
error: TRACE_REPO is not set.

Set it to the GitHub repo hosting the trace release, either by editing the
default at the top of this script or by exporting it:

    TRACE_REPO=<owner>/<repo> ./fetch_traces.sh

EOF
  exit 1
fi

mkdir -p "$DEST"
[[ -f "$DEST/SHA256SUMS" ]] || { echo "error: $DEST/SHA256SUMS missing (it is tracked in git)" >&2; exit 1; }

BASE="https://github.com/$TRACE_REPO/releases/download/$TRACE_TAG"
echo ">>> Fetching traces from $TRACE_REPO @ $TRACE_TAG into $DEST"

# Trace list is derived from the tracked manifest, so the two can never drift.
mapfile -t FILES < <(awk '{print $2}' "$DEST/SHA256SUMS")
echo ">>> ${#FILES[@]} traces listed in manifest"

fail=0
for f in "${FILES[@]}"; do
  if [[ -f "$DEST/$f" ]]; then
    echo "[have] $f"
    continue
  fi
  echo "[get ] $f"
  if ! curl -fSL --retry 3 --retry-delay 5 -o "$DEST/$f.part" "$BASE/$f"; then
    echo "[FAIL] $f (download)" >&2
    rm -f "$DEST/$f.part"
    fail=1
    continue
  fi
  mv "$DEST/$f.part" "$DEST/$f"
done

echo ">>> Verifying checksums"
if ( cd "$DEST" && sha256sum --quiet -c SHA256SUMS ); then
  echo ">>> All traces present and verified."
else
  echo ">>> CHECKSUM MISMATCH -- delete the offending files and re-run." >&2
  fail=1
fi

exit $fail
