#!/usr/bin/env bash
# measure-latency.sh — reproducible wall-clock measurement of the verification loop.
#
# Every number in docs/test-latency.md came from this script. It times a labelled
# command, records the load average and core count alongside it (this box is
# shared between concurrent agents, so a duration without its ambient load is
# uninterpretable), and appends one JSON object per run to a JSONL file.
#
# Usage:
#   ./measure-latency.sh bench <label> <command...>   # time one command
#   ./measure-latency.sh cold                         # full cold-start sequence
#   ./measure-latency.sh warm                         # full warm sequence
#   ./measure-latency.sh report                       # summarise the JSONL
#
# Env:
#   GE_BENCH_OUT   results file (default: docs/bench-results.jsonl)
#   GE_WEB_PORT / GE_API_PORT  ports for the Playwright stack (default 4173/8000)

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GE="$REPO_ROOT/graph-engine"
CS="$REPO_ROOT/calcsheet"
WEB="$GE/web"
OUT="${GE_BENCH_OUT:-$GE/docs/bench-results.jsonl}"

mkdir -p "$(dirname "$OUT")"

# --- helpers ---------------------------------------------------------------

loadavg() { cut -d' ' -f1 </proc/loadavg; }

# json-escape a string
esc() { python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))' <<<"$1"; }

# bench <label> <cwd> <command...>
bench() {
  local label="$1" cwd="$2"; shift 2
  local load_before load_after start end dur rc
  load_before="$(loadavg)"
  start="$(date +%s.%N)"
  ( cd "$cwd" && "$@" ) >/tmp/bench-last.log 2>&1
  rc=$?
  end="$(date +%s.%N)"
  load_after="$(loadavg)"
  dur="$(python3 -c "print(f'{$end-$start:.2f}')")"

  # Pull the test count out of pytest/playwright output when present, so a run
  # that silently collected nothing is visible in the record rather than looking
  # like a fast pass. (This repo has been bitten by exactly that.)
  local collected=""
  collected="$(grep -oE '[0-9]+ (passed|tests? passed)' /tmp/bench-last.log | tail -1 || true)"

  printf '{"label":%s,"seconds":%s,"rc":%d,"load_before":%s,"load_after":%s,"cores":%s,"result":%s,"ts":"%s"}\n' \
    "$(esc "$label")" "$dur" "$rc" "$load_before" "$load_after" "$(nproc)" \
    "$(esc "$collected")" "$(date -Is)" >>"$OUT"

  printf '%-46s %8ss  rc=%d  load %s->%s  %s\n' "$label" "$dur" "$rc" "$load_before" "$load_after" "$collected"
  return $rc
}

# --- individual steps ------------------------------------------------------

step_cs_sync()    { bench "calcsheet: uv sync (cold dep resolve+install)" "$CS"  uv sync --extra dev; }
step_ge_sync()    { bench "graph-engine: uv sync (cold dep resolve+install)" "$GE" uv sync --extra sym --extra dev; }
step_cs_pytest()  { bench "calcsheet: pytest"      "$CS"  uv run --extra dev python -m pytest -q; }
step_ge_pytest()  { bench "graph-engine: pytest"   "$GE"  uv run --extra sym --extra dev python -m pytest -q; }
step_pnpm_inst()  { bench "web: pnpm install"      "$WEB" pnpm install; }
step_typecheck()  { bench "web: pnpm typecheck"    "$WEB" pnpm typecheck; }
step_build()      { bench "web: pnpm build"        "$WEB" pnpm build; }
step_build_noop() { bench "web: pnpm build (no-op rerun)" "$WEB" pnpm build; }

step_pw() {
  local workers="${1:-2}"
  bench "playwright: full suite --workers=$workers" "$WEB" \
    env GE_WEB_PORT="${GE_WEB_PORT:-4173}" GE_API_PORT="${GE_API_PORT:-8000}" \
    pnpm exec playwright test --reporter=list --workers="$workers"
}

# --- sequences -------------------------------------------------------------

case "${1:-report}" in
  bench) shift; label="$1"; cwd="$2"; shift 2; bench "$label" "$cwd" "$@" ;;

  cold)
    echo "== COLD sequence (nothing installed) =="
    step_cs_sync; step_ge_sync; step_pnpm_inst; step_build
    ;;

  warm)
    echo "== WARM sequence (deps present) =="
    step_cs_pytest; step_ge_pytest; step_pnpm_inst; step_typecheck; step_build_noop
    ;;

  pytest)  step_cs_pytest; step_ge_pytest ;;
  pw)      shift; step_pw "${1:-2}" ;;
  report)
    python3 - "$OUT" <<'PY'
import json, sys, statistics
from collections import defaultdict
rows = defaultdict(list)
for line in open(sys.argv[1]):
    line = line.strip()
    if not line: continue
    r = json.loads(line)
    rows[r["label"]].append(r)
print(f'{"label":<52}{"n":>3}{"min":>9}{"med":>9}{"max":>9}  {"rc":>3}')
for label, rs in rows.items():
    s = sorted(x["seconds"] for x in rs)
    bad = sum(1 for x in rs if x["rc"] != 0)
    print(f'{label:<52}{len(s):>3}{min(s):>9.1f}{statistics.median(s):>9.1f}{max(s):>9.1f}  {bad:>3}')
PY
    ;;
  *) echo "unknown: $1"; exit 2 ;;
esac
