#!/usr/bin/env python3
"""analyze-transcripts.py — how much of a real agent task went into verification?

Streams the agent JSONL transcripts (they are large; this never holds one in
memory or prints their content), pairs each Bash tool_use with its tool_result
by id, and uses the two records' timestamps as that command's wall clock.
Commands are bucketed into the verification steps agents are told to run.

Usage: analyze-transcripts.py <transcripts-dir> [--min-minutes N]
"""
import json, os, re, sys
from collections import defaultdict
from datetime import datetime

DIR = sys.argv[1] if len(sys.argv) > 1 else "."
MIN_MIN = 0.0
if "--min-minutes" in sys.argv:
    MIN_MIN = float(sys.argv[sys.argv.index("--min-minutes") + 1])

BUCKETS = [
    ("playwright", re.compile(r"playwright test|pnpm (exec )?playwright|pnpm test\b")),
    ("pnpm build", re.compile(r"pnpm build|vite build")),
    ("pnpm typecheck", re.compile(r"pnpm typecheck|tsc -b")),
    ("pnpm install", re.compile(r"pnpm install")),
    ("ge pytest", re.compile(r"pytest.*(--extra sym|graph-engine)|graph-engine.*pytest")),
    ("cs pytest", re.compile(r"calcsheet.*pytest|pytest.*calcsheet")),
    ("pytest (other)", re.compile(r"\bpytest\b")),
    ("uv sync", re.compile(r"uv sync")),
]


def bucket(cmd):
    for name, rx in BUCKETS:
        if rx.search(cmd):
            return name
    return None


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


rows = []
for fn in sorted(os.listdir(DIR)):
    if not fn.endswith(".jsonl"):
        continue
    path = os.path.join(DIR, fn)
    pending = {}          # tool_use_id -> (start_ts, bucket)
    per = defaultdict(lambda: [0.0, 0])
    first = last = None
    branch = None
    touched_ge = False
    try:
        with open(path, errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                t = rec.get("timestamp")
                if t:
                    t = ts(t)
                    first = t if first is None else min(first, t)
                    last = t if last is None else max(last, t)
                branch = rec.get("gitBranch") or branch
                cwd = rec.get("cwd") or ""
                if "graph-engine" in cwd or "calcsheet" in cwd:
                    touched_ge = True
                msg = rec.get("message") or {}
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use" and block.get("name") == "Bash":
                        cmd = (block.get("input") or {}).get("command", "")
                        b = bucket(cmd)
                        if b:
                            pending[block.get("id")] = (t, b)
                            if "graph-engine" in cmd or "calcsheet" in cmd:
                                touched_ge = True
                    elif block.get("type") == "tool_result":
                        got = pending.pop(block.get("tool_use_id"), None)
                        if got and t and got[0]:
                            dur = t - got[0]
                            if 0 <= dur < 3600:
                                per[got[1]][0] += dur
                                per[got[1]][1] += 1
    except Exception as e:
        print(f"skip {fn}: {e}", file=sys.stderr)
        continue

    if first is None or last is None:
        continue
    total = last - first
    if total / 60 < MIN_MIN or not touched_ge:
        continue
    verif = sum(v[0] for v in per.values())
    rows.append((fn, branch, total, verif, dict(per)))

rows.sort(key=lambda r: -r[2])

print(f"{'transcript':<26}{'branch':<34}{'total_min':>10}{'verif_min':>10}{'verif%':>8}")
for fn, branch, total, verif, per in rows:
    print(
        f"{fn[6:22]:<26}{(branch or '?')[:33]:<34}{total/60:>10.1f}{verif/60:>10.1f}"
        f"{100*verif/total if total else 0:>7.0f}%"
    )

print()
agg = defaultdict(lambda: [0.0, 0])
for *_, per in rows:
    for k, (s, n) in per.items():
        agg[k][0] += s
        agg[k][1] += n
print(f"{'bucket':<18}{'runs':>6}{'total_min':>11}{'mean_s':>9}")
for k, (s, n) in sorted(agg.items(), key=lambda kv: -kv[1][0]):
    print(f"{k:<18}{n:>6}{s/60:>11.1f}{s/n if n else 0:>9.1f}")

if rows:
    tt = sum(r[2] for r in rows)
    vv = sum(r[3] for r in rows)
    print()
    print(f"tasks analysed: {len(rows)}")
    print(f"aggregate wall:  {tt/60:.0f} min")
    print(f"aggregate verif: {vv/60:.0f} min  ({100*vv/tt:.0f}% of wall)")
    med = sorted(100 * r[3] / r[2] for r in rows if r[2])
    print(f"median per-task verification share: {med[len(med)//2]:.0f}%")
