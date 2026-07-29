#!/bin/bash
# Publish the instrumented traces in ./trace as GitHub Release assets.
#
# Release assets are used instead of Git LFS because:
#   - GitHub's hard per-file limit in a git push is 100 MB; 18 of the 25 traces
#     are larger (up to 214 MB), so a plain push is rejected outright.
#   - Release assets allow up to 2 GB per file, cost no LFS storage quota, and
#     are not billed against LFS bandwidth. The free LFS tier is only 1 GB.
#
# Requires the gh CLI, authenticated: gh auth status
#
# Usage:
#   TRACE_REPO=<owner>/<repo> ./upload_traces.sh
#   TRACE_REPO=<owner>/<repo> TRACE_TAG=traces-v2 ./upload_traces.sh
set -uo pipefail
cd "$(dirname "$0")"

TRACE_REPO=${TRACE_REPO:-}
TRACE_TAG=${TRACE_TAG:-traces-v1}
SRC=${SRC:-./trace}

[[ -n $TRACE_REPO ]] || { echo "error: set TRACE_REPO=<owner>/<repo>" >&2; exit 1; }
command -v gh >/dev/null || { echo "error: gh CLI not found" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "error: gh not authenticated (run: gh auth login)" >&2; exit 1; }
[[ -f "$SRC/SHA256SUMS" ]] || { echo "error: $SRC/SHA256SUMS missing" >&2; exit 1; }

mapfile -t FILES < <(awk '{print $2}' "$SRC/SHA256SUMS")

# Refuse to publish a partial or corrupted set.
echo ">>> Verifying local traces before upload"
missing=0
for f in "${FILES[@]}"; do
  [[ -f "$SRC/$f" ]] || { echo "  missing: $f"; missing=1; }
done
(( missing == 0 )) || { echo "error: local trace set incomplete, refusing to upload" >&2; exit 1; }
( cd "$SRC" && sha256sum --quiet -c SHA256SUMS ) || { echo "error: checksum mismatch, refusing to upload" >&2; exit 1; }

total=$(du -ch "${FILES[@]/#/$SRC/}" | tail -1 | cut -f1)
echo ">>> ${#FILES[@]} traces, $total total -> $TRACE_REPO @ $TRACE_TAG"

if gh release view "$TRACE_TAG" --repo "$TRACE_REPO" >/dev/null 2>&1; then
  echo ">>> Release $TRACE_TAG already exists, uploading into it"
else
  echo ">>> Creating release $TRACE_TAG"
  gh release create "$TRACE_TAG" --repo "$TRACE_REPO" \
    --title "Instrumented ChampSim traces" \
    --notes "malloc/free-instrumented SPEC CPU2017 ChampSim traces for the SAFE object-bound prefetcher guard.

Generated with the Pin tool in \`tracer/champsim_tracer.cpp\`. In addition to standard ChampSim instruction records these carry heap allocation records (AllocType 1=malloc, 2=free, 3=live-at-skip) which populate the guard's \`live_heap\` map. The public DPC3/SPEC17 traces do NOT contain these records and cannot be substituted.

Fetch with \`fetch_traces.sh\`; checksums are pinned in \`trace/SHA256SUMS\`." || exit 1
fi

# Upload one at a time: 200 MB assets are slow and --clobber makes reruns safe
# after a partial failure.
fail=0
for f in "${FILES[@]}"; do
  echo "[up  ] $f"
  gh release upload "$TRACE_TAG" "$SRC/$f" --repo "$TRACE_REPO" --clobber || { echo "[FAIL] $f" >&2; fail=1; }
done

gh release upload "$TRACE_TAG" "$SRC/SHA256SUMS" --repo "$TRACE_REPO" --clobber || fail=1

if (( fail == 0 )); then
  echo ">>> Upload complete: https://github.com/$TRACE_REPO/releases/tag/$TRACE_TAG"
else
  echo ">>> Some uploads failed -- re-run, --clobber makes it idempotent." >&2
fi
exit $fail
