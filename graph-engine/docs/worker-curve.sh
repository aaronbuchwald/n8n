#!/usr/bin/env bash
# worker-curve.sh — measure Playwright wall clock vs --workers on the parallel
# `chromium` pack (122 of the 145 tests; the other 23 are the serial chain and
# are unaffected by worker count).
#
# Assumes an ALREADY-RUNNING api+preview stack on GE_API_PORT/GE_WEB_PORT built
# from the current source, so this measures test EXECUTION only, with no build
# or server-boot noise. Runs the ladder up and then back down, because this box
# is shared and load drifts; interleaving keeps drift from biasing one end.

set -uo pipefail
WEB="$(cd "$(dirname "${BASH_SOURCE[0]}")/../web" && pwd)"
OUT="${GE_BENCH_OUT:-$(dirname "${BASH_SOURCE[0]}")/worker-curve.jsonl}"
export GE_WEB_PORT="${GE_WEB_PORT:-4173}" GE_API_PORT="${GE_API_PORT:-8000}"

run() {
  local w="$1" pass="$2" start end dur rc load
  load="$(cut -d' ' -f1 </proc/loadavg)"
  start="$(date +%s.%N)"
  ( cd "$WEB" && pnpm exec playwright test --reporter=line --workers="$w" \
      --project=chromium --no-deps ) >/tmp/wc-$w-$pass.log 2>&1
  rc=$?
  end="$(date +%s.%N)"
  dur="$(python3 -c "print(f'{$end-$start:.2f}')")"
  local passed
  passed="$(grep -oE '[0-9]+ passed' /tmp/wc-$w-$pass.log | tail -1)"
  printf '{"workers":%s,"pass":"%s","seconds":%s,"rc":%d,"load_before":%s,"result":"%s"}\n' \
    "$w" "$pass" "$dur" "$rc" "$load" "$passed" >>"$OUT"
  printf 'workers=%-2s pass=%s  %8ss  rc=%d  load=%s  %s\n' "$w" "$pass" "$dur" "$rc" "$load" "$passed"
}

for w in 1 2 3 4 6; do run "$w" up; done
for w in 6 4 3 2 1; do run "$w" down; done
