#!/usr/bin/env bash
# contention-probe.sh — the two questions the noisy worker-curve could not answer:
#   (a) what does --workers actually buy on a QUIET box, and
#   (b) how much does a second concurrent agent cost each of them.
#
# Both need a quiet starting point, so the script blocks until the 1-minute load
# average drops below GE_QUIET (default 4) before each measurement, and records
# the load sampled DURING the run (the 1-min average read at the start is a
# lagging indicator — that is what made the first curve uninterpretable).
#
# Requires a prebuilt dist and a running api+preview stack on 4173/8000, plus a
# SECOND stack on 4174/8001 for the concurrency arm.

set -uo pipefail
WEB="$(cd "$(dirname "${BASH_SOURCE[0]}")/../web" && pwd)"
OUT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/contention.jsonl"
QUIET="${GE_QUIET:-4}"

wait_quiet() {
  local n=0
  while : ; do
    local l; l="$(cut -d' ' -f1 </proc/loadavg)"
    if (( $(python3 -c "print(1 if $l < $QUIET else 0)") )); then return 0; fi
    n=$((n+1)); [ "$n" -gt 120 ] && { echo "  (gave up waiting for quiet; load=$l)"; return 1; }
    sleep 10
  done
}

# sample the load every 2s in the background, report the mean over the run
sample_load() {
  local out="$1"; : >"$out"
  while : ; do cut -d' ' -f1 </proc/loadavg >>"$out"; sleep 2; done
}

# measure <label> <web_port> <api_port> <workers>
measure() {
  local label="$1" wp="$2" ap="$3" w="$4"
  local start end dur rc sf mean
  sf="$(mktemp)"; sample_load "$sf" & local spid=$!
  start="$(date +%s.%N)"
  ( cd "$WEB" && GE_WEB_PORT="$wp" GE_API_PORT="$ap" \
      pnpm exec playwright test --reporter=line --workers="$w" \
      --project=chromium --no-deps ) >"/tmp/cp-$label.log" 2>&1
  rc=$?
  end="$(date +%s.%N)"
  kill "$spid" 2>/dev/null
  mean="$(python3 -c "
import sys
v=[float(x) for x in open('$sf') if x.strip()]
print(f'{sum(v)/len(v):.2f}' if v else '0')")"
  dur="$(python3 -c "print(f'{$end-$start:.2f}')")"
  local passed; passed="$(grep -oE '[0-9]+ passed' "/tmp/cp-$label.log" | tail -1)"
  local failed; failed="$(grep -oE '[0-9]+ failed' "/tmp/cp-$label.log" | tail -1)"
  printf '{"label":"%s","workers":%s,"seconds":%s,"rc":%d,"load_mean":%s,"passed":"%s","failed":"%s"}\n' \
    "$label" "$w" "$dur" "$rc" "$mean" "$passed" "$failed" >>"$OUT"
  printf '%-22s w=%-2s %8ss rc=%d loadmean=%-6s %s %s\n' "$label" "$w" "$dur" "$rc" "$mean" "$passed" "$failed"
}

echo "== arm A: worker ladder on a quiet box =="
for w in 1 2 4; do
  echo "waiting for load < $QUIET ..."; wait_quiet
  measure "solo-w$w" 4173 8000 "$w"
done

echo "== arm B: two concurrent agents, each --workers=2, separate stacks =="
echo "waiting for load < $QUIET ..."; wait_quiet
measure "conc-A" 4173 8000 2 &
pidA=$!
measure "conc-B" 4174 8001 2 &
pidB=$!
wait $pidA $pidB
echo "done"
