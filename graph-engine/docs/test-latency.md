# Verification-loop latency: measured budget and recommendations

Measured on `docs/test-latency-diagnosis` (from `feat/rfem-governing-force`, head
`9cd200b0`), 2026-07-26, in a fresh agent worktree.

**Box:** 4 vCPU, 15 GB RAM, shared by up to three concurrent agent worktrees
(14 worktrees exist; three were running Playwright simultaneously during these
measurements). Global package caches were already warm: `~/.cache/uv` 339 MB,
pnpm store 3.2 GB.

Everything here is reproducible with the committed scripts:

| script | what it produces |
| --- | --- |
| `docs/measure-latency.sh` | per-step timings → `docs/bench-results.jsonl` |
| `docs/worker-curve.sh` | `--workers` ladder → `docs/worker-curve.jsonl` |
| `docs/contention-probe.sh` | worker ladder + 2-agent overlap → `docs/contention.jsonl` |
| `docs/analyze-transcripts.py` | verification share of real agent tasks |

A caveat that shapes the whole document: **a quiet box was never available.**
The 1-minute load average sat between 9 and 35 for most of the session because
other agents were running their own suites. Numbers are therefore reported with
the load they were taken under, and the "quiet" column exists only because one
early window happened to be idle (load ≈ 2).

---

## 1. The measured time budget

### 1.1 Setup — much cheaper than assumed

| step | fresh worktree | warm worktree |
| --- | ---: | ---: |
| `calcsheet`: `uv sync --extra dev` | **0.51 s** | — |
| `graph-engine`: `uv sync --extra sym --extra dev` | **0.42 s** | — |
| `web`: `pnpm install` | **1.53 s** | 1.27 s |
| **total dependency install** | **≈ 2.5 s** | ≈ 1.3 s |

These are real installs, verified not to be no-ops: 70 packages in
`graph-engine/.venv`, 11 top-level entries in `web/node_modules`.

**A fresh worktree is not a cold cache.** Both `uv` and `pnpm` resolve from a
content-addressed store on this machine and materialise by hardlinking, so a
"cold" worktree costs ~2.5 s, not minutes. This single fact invalidates the most
commonly proposed fix (see §5, rejected R1).

### 1.2 Per-suite, warm, low load (1.9 – 4.5)

| step | seconds | scope |
| --- | ---: | --- |
| `calcsheet` pytest | **3.81** | 93 passed |
| `graph-engine` pytest | **21.83** | 636 passed |
| `pnpm typecheck` | **5.87** | `tsc -b --noEmit` |
| `pnpm build` (first) | **18.81** | `tsc -b && vite build` |
| `pnpm build` (immediate re-run, nothing changed) | **17.44** | effectively **not** incremental |
| Playwright, full suite, `--workers=2` | **154.55** | 145 passed |

`pnpm build` re-run costs 17.44 s against 18.81 s cold — vite rebuilds the
bundle essentially from scratch every time. There is no "unchanged bundle" fast
path to exploit today.

### 1.3 One full pass of the instructed block

| step | s | share |
| --- | ---: | ---: |
| calcsheet pytest | 3.8 | 2% |
| graph-engine pytest | 21.8 | 11% |
| pnpm install | 1.3 | 1% |
| pnpm typecheck | 5.9 | 3% |
| pnpm build | 18.8 | 9% |
| Playwright | 154.6 | **75%** |
| **total** | **≈ 206 s (3.4 min)** | |

At the 2–3 passes agents typically run: **7–10 min of verification per task** on
a quiet box; 11–15 min at the loads actually observed.

### 1.4 Inside Playwright (`--workers=2`, load ≈ 2, all 145 passed)

| phase | s | note |
| --- | ---: | --- |
| **setup outside tests** | **24.8** | uvicorn boot + `pnpm build` (~17.4) + vite preview + browser launch |
| chromium (parallel pack) | 79.9 | 122 tests, 142.7 s summed → parallel factor 1.79 |
| serial chain | 48.6 | 23 tests across 5 sequential projects |
| **total wall** | **154.6** | |

Serial chain detail:

| project | tests | window | gap before it |
| --- | ---: | ---: | ---: |
| `editing` | 4 | 7.6 s | 1.1 s |
| `calc` | 1 | 3.7 s | 1.2 s |
| `formula` | 7 | 12.3 s | 1.6 s |
| `new-node` | 2 | 4.9 s | 1.2 s |
| `catalog` | 9 | 14.7 s | 1.5 s |
| **total** | **23** | **41.8 s tests + 6.6 s gaps = 48.6 s** | |

**23 of 145 tests (16%) consume 37% of the test-execution window.**

Re-running with the API and preview already up (so Playwright's `webServer`
step is skipped entirely) dropped setup from 24.8 s to 11.3 s — i.e. the
server-boot-plus-build phase is worth **≈ 13.5 s minimum, ~19 s at low load**,
dominated by `pnpm build`.

### 1.5 Which specs cost the money

Summed test duration, all 145 tests (184.4 s total):

| spec | tests | s | share |
| --- | ---: | ---: | ---: |
| `frontend-sanity.spec.ts` | 18 | 53.3 | **28.9%** |
| `workbench-layout.spec.ts` | 12 | 17.7 | 9.6% |
| `content-reachability.spec.ts` | 15 | 14.5 | 7.9% |
| `node-catalog.spec.ts` | 9 | 14.2 | 7.7% |
| `formula-editing.spec.ts` | 7 | 12.0 | 6.5% |
| …19 more specs | 65 | 72.7 | 39.4% |
| `store-editing` / `store-queue` / `store-equation` | 19 | 0.6 | 0.3% |

`frontend-sanity.spec.ts` is the single biggest line item: it walks every panel
and every action from a fresh boot per action. Nineteen store-* tests are
effectively free.

---

## 2. Is the serialisation necessary?

The config chains `chromium → editing → calc → formula → new-node → catalog`
because these specs mutate the workspace. Checking what each actually writes:

| project | file it rewrites |
| --- | --- |
| `editing` | `examples/showcase/showcase.py` + layout sidecar |
| `calc` | `examples/handcalc_demo/handcalc_demo.py` |
| `formula` | `examples/capacity_check/capacity_check.py` |
| `new-node` | `examples/showcase/showcase.py` |
| `catalog` | `examples/showcase/showcase.py` |

**Only three of the five contend.** `editing`, `new-node` and `catalog` all
rewrite `showcase.py` and must stay mutually serial. `calc` (handcalc_demo) and
`formula` (capacity_check) touch disjoint files — from each other and from the
showcase group. The config's own comment for `formula` notes it is "on a
different example" and chains it anyway, out of caution rather than necessity.

Restructuring to `chromium → [editing → new-node → catalog]` with `calc` and
`formula` running alongside:

- showcase group: 7.6 + 4.9 + 14.7 + 2 gaps ≈ **29.8 s**
- `calc` (3.7 s) and `formula` (12.3 s) overlap inside that window
- **48.6 s → ~29.8 s, saving ≈ 18.8 s per full run**, no coverage change.

---

## 3. Worker count and concurrency

### 3.1 The ladder is dominated by load, not by `--workers`

First ladder (`worker-curve.jsonl`, chromium pack only), taken while two other
agents ran their suites:

| workers | pass | s | load at start | result |
| ---: | --- | ---: | ---: | --- |
| 1 | up | 165.8 | 4.6 | 122 passed |
| 2 | up | 191.3 | 8.3 | 121 passed, **1 failed** |
| 3 | up | 178.5 | 23.7 | 122 passed |
| 4 | up | 190.4 | 27.4 | 120 passed, **2 failed** |
| 6 | up | 144.5 | 29.4 | 120 passed, **2 failed** |
| 6 | down | 109.4 | 27.1 | 120 passed, **2 failed** |
| 4 | down | 129.4 | 22.6 | 120 passed, **2 failed** |
| 3 | down | 176.4 | 27.0 | 120 passed, **2 failed** |
| 2 | down | 153.6 | 23.6 | 120 passed, **2 failed** |

No relationship to worker count survives the noise. **Ambient load is a far
stronger predictor of wall clock than `--workers`.**

### 3.2 Controlled ladder, load sampled during each run

Re-run back-to-back so all three see comparable conditions
(`contention.jsonl`):

| config | s | mean load during run | result |
| --- | ---: | ---: | --- |
| `--workers=1` | 165.7 | 9.8 | 119 passed, 3 failed |
| `--workers=2` | 130.1 | 14.2 | 120 passed, 2 failed |
| `--workers=4` | 107.1 | 20.1 | 120 passed, 2 failed |

Against a contended box, raising workers **does** help the individual run:
2 → 4 workers is 130 s → 107 s (−18%). But this is zero-sum — the extra speed
is taken from the other agents sharing the four cores.

### 3.3 Two concurrent agents, separate stacks

| config | s | mean load | result |
| --- | ---: | ---: | --- |
| solo, `--workers=2` | 130.1 | 14.2 | 2 failed |
| concurrent A, `--workers=2` | 172.4 | 20.0 | 2 failed |
| concurrent B, `--workers=2` | 176.5 | 20.1 | 2 failed |

A second concurrent agent inflates each run **130 s → ~174 s (+34%)**. Against
the quiet-box baseline (chromium pack ≈ 90 s including startup at load 2), a
realistically contended run is **+93%**.

No port or disk contention was observed: the other agents correctly set
`GE_WEB_PORT`/`GE_API_PORT` (4288/8088, 4289/8089), and installs are hardlinks.
**The contention is purely CPU.**

### 3.4 The real cost of contention is false failures, not seconds

Every run at sustained load ≥ 9 failed, on unchanged code. Three tests are
load-sensitive:

| test | symptom |
| --- | --- |
| `frontend-sanity` → `pane-click-clears-selection` | click lands before the handler settles |
| `minimap-passthrough` → "node beneath the minimap is still clickable" | hit-test race |
| `workbench-layout.spec.ts:140` "sizes persist across reload" | `expect(<8)` px, got **90.3** — layout not settled at assert time |

On the quiet run all 145 passed. Under normal multi-agent load the suite
reliably reports 2–3 failures that are not real. That is worse than slow: an
agent either re-runs (another ~155–244 s) or, worse, starts "fixing" a
non-existent bug.

---

## 4. What fraction of a real task is verification?

`analyze-transcripts.py` over 216 agent transcripts, pairing each Bash
`tool_use` with its `tool_result` and bucketing by command. 79 tasks touched
these projects (1415 min of wall clock).

- **Aggregate: 235 min of 1415 min = 17% of wall.**
- **Median per task: 6%.**

The distribution is strongly bimodal:

| task | branch | total | verification |
| --- | --- | ---: | ---: |
| `aeef580e` | feat/card-equation-sizing | 86.8 min | 4.3 min (**5%**) |
| `a33d44b3` | test/reachability-invariant | 46.1 min | 22.3 min (**48%**) |
| `a7990c2e` | feat/grouping-strategies | 30.6 min | 15.8 min (**52%**) |
| `a0e2459b` | feat/card-light-redesign | 33.3 min | 13.3 min (**40%**) |
| `aa1ade6f` | feat/calcsheet-node | 38.0 min | 14.6 min (**39%**) |
| `a039cb03` | integration/wave-1 | 27.1 min | 0.0 min (0%) |

The 87-minute task — the longest observed — spent 5% of itself verifying. Its
length came from somewhere else entirely. **Verification is not what makes long
tasks long.** But for the subset that does exercise the loop, it is 30–52%.

Where the verification time actually goes:

| bucket | runs | total | mean |
| --- | ---: | ---: | ---: |
| playwright | 227 | 178.7 min | 47.2 s |
| graph-engine pytest | 208 | 20.9 min | 6.0 s |
| pnpm build | 83 | 19.0 min | 13.8 s |
| pnpm install | 47 | 6.6 min | 8.4 s |
| pnpm typecheck | 90 | 6.4 min | 4.3 s |
| calcsheet pytest | 49 | 2.6 min | 3.1 s |
| uv sync | 12 | 0.2 min | 1.0 s |

**Playwright is 76% of all verification time.** And within it, the distribution
of 237 invocations is extremely skewed:

| percentile | duration |
| --- | ---: |
| p10 | 1.6 s |
| p25 | 9.6 s |
| p50 | **22.8 s** |
| p75 | 56.0 s |
| p90 | 146.0 s |
| p95 | 240.3 s |
| p99 | 487.7 s |
| max | 600.6 s |

- **31 invocations (13%) ran ≥ 120 s — the full suite — and consumed 126 of the
  179 minutes (70%).**
- 179 invocations (76%) took < 60 s: targeted subsets.
- **52% of invocations already narrowed scope** with `--grep`, `--project` or an
  explicit spec path.

Two conclusions. First, agents are *already* iterating with targeted runs far
more than the instruction block suggests — so "tell agents to use a targeted
command" captures less than it appears. Second, the mean full-suite run costs
**244 s against a 154 s quiet-box baseline (+58%)**, and the p99 of 488 s shows
how badly the tail degrades under load.

---

## 5. Waste / irreducible / self-inflicted

### Irreducible — ≈ 135 s per full pass

- `graph-engine` pytest 21.8 s for 636 tests (34 ms/test — genuinely cheap).
- `calcsheet` pytest 3.8 s for 93 tests.
- chromium parallel pack ≈ 80 s at `--workers=2`.
- The showcase serial group ≈ 30 s — three specs really do contend on one file.

### Waste — ≈ 44 s per full pass, recoverable with no coverage loss

| item | cost |
| --- | ---: |
| explicit `pnpm build`, when Playwright's `webServer` builds again anyway | 18.8 s |
| explicit `pnpm typecheck`, when `pnpm build` runs `tsc -b` itself | 5.9 s |
| `calc` + `formula` serialised without needing to be (incl. the 2 project gaps that go with them) | 18.8 s |
| **total** | **43.5 s** |

Note the interaction: today's explicit `pnpm build` is *not* redundant in the
one case that matters — when a preview server is already listening, Playwright
skips its own build entirely (§6). Removing it is only safe once that hole is
closed.

### Contention — ≈ 90 s per full run, plus a flake tax

Mean observed full run 244 s vs 154 s quiet. This is not pure waste: three
agents sharing four cores finish sooner *in aggregate* than if serialised, so
the latency is partly the price of throughput. The genuine loss is the 2–3
false failures per run (§3.4), each of which can cost a whole extra pass.

### Self-inflicted by the instructions

- `pnpm typecheck && pnpm build` before a `pnpm test` that rebuilds: pure
  duplication, 24.7 s every pass, every agent.
- The block is presented as one indivisible ritual, so an agent that only
  touched a Python node still runs 145 browser tests. The transcripts show
  agents routing around this (52% narrow scope), which suggests the instruction
  is already being ignored in spirit — better to make the fast path official
  than to leave each agent to improvise it.

---

## 6. Two failure modes the recommendations must survive

### 6.1 Stale preview server — reproduced

`playwright.config.ts` sets `reuseExistingServer: !process.env.CI`, and agents
do not set `CI`. When anything is already listening on the web port, Playwright
**skips the entire `pnpm build && vite preview` command**.

Reproduced in 9 seconds:

1. Appended `console.log("STALE_BUNDLE_MARKER_9F3A")` to `web/src/main.tsx`.
2. Ran `playwright test --project=chromium tests/graph.spec.ts` against an
   already-running preview server.
3. **3 passed in 8.9 s.**
4. `dist/index.html` mtime unchanged; the marker was absent from `dist/` and
   from the bundle the server served.

The suite reported green against a bundle that predated the change. If the
listening server belongs to *another worktree*, the run tests that worktree's
code entirely. Any warm-server or skip-the-build proposal must defeat this.

### 6.2 Global pytest outside the venv — currently safe

`/root/.local/bin/pytest` (9.0.2) is on `PATH`. Today both projects fail loudly
rather than silently:

- `graph-engine`: bare `pytest` → 39 collection errors.
- `calcsheet`: bare `pytest` → 8 collection errors (`No module named 'calcsheet'`).
- `pytest` exits **5** on zero collected/selected, so a `&&` chain catches it.

The instructed `uv run --extra … python -m pytest` form is robust. The risk is
reintroducing the hole via a caching shortcut (a pre-activated venv that drifts,
or invoking `pytest` directly). Any such change should assert a **floor on the
collected count**, not just exit status.

### 6.3 Incidental: verifying dirties the worktree

Running the suite rewrote 8 tracked baselines under
`web/tests/__screenshots__/`, and left a new untracked
`examples/showcase/showcase.layout.json` behind (the `editing` spec writes the
layout sidecar and does not remove it when it did not exist beforehand). Agents
that merely verify end up with a dirty worktree and may commit the churn.

---

## 7. Recommendations, ranked by wall-clock saved per unit of effort and risk

### R1 — Close the stale-server hole, then delete the duplicated build
**Saves ≈ 24.7 s per pass (12%). Effort: small. Risk: low. Coverage lost: none.**

Two coupled changes:

1. In `playwright.config.ts`, stop silently reusing a foreign server. Either set
   `reuseExistingServer: false`, or — better, and cheaper at runtime — keep reuse
   but stamp the bundle with the working tree's git SHA + dirty-hash at build
   time and add one smoke test asserting the served stamp matches the current
   tree. That converts the §6.1 silent-wrong-artifact failure into a loud one
   and makes every later reuse proposal safe.
2. Drop `pnpm typecheck && pnpm build` from the agent block. Playwright's
   `webServer` runs `pnpm build`, which runs `tsc -b`; if types fail the build
   fails, the URL never comes up and the run errors out. Type coverage is
   preserved.

Do **not** do (2) without (1): today the explicit build is the only thing
standing between an agent and a stale bundle when a server is already up.

### R2 — Narrow the serial chain to the three specs that actually contend
**Saves ≈ 18.8 s per full run (12% of Playwright). Effort: small. Risk: low. Coverage lost: none.**

Keep `editing → new-node → catalog` serial (all rewrite `showcase.py`). Let
`calc` (handcalc_demo) and `formula` (capacity_check) depend on `chromium` only
and run alongside the showcase group. Evidence in §2.

Residual risk: it assumes the server tolerates concurrent writeback to
*different* example modules. That is worth one deliberate check before landing —
if writeback takes a global lock, the gain shrinks to the two removed gaps
(~2.6 s) and the change should be dropped.

### R3 — Fix the three load-sensitive tests
**Saves an entire re-run (155–244 s) whenever it would have fired. Effort: small-to-medium. Risk: low. Coverage lost: none — it increases trustworthy coverage.**

`pane-click-clears-selection`, `minimap-passthrough`, and
`workbench-layout.spec.ts:140` fail on unchanged code at load ≥ 9 (§3.4). They
are settling/hit-test races, not real regressions. At current concurrency this
is the difference between a suite an agent can believe and one it cannot. I rank
it this high because a false failure costs more than any per-pass saving on this
list, and because it is a precondition for trusting anything else here.

### R4 — Make the targeted iteration loop official
**Saves ≈ 130–175 s per iteration pass avoided. Effort: small (documentation). Risk: medium — this is the one that trades coverage.**

Give agents an explicit two-tier instruction: a targeted command during
iteration (the relevant `--project`/spec path, plus the Python suite, which at
25.6 s combined is cheap enough to always run in full), and the complete block
once before handing off.

What it gives up: during iteration, a change can break a spec the agent did not
think to select. The Python suites are cheap enough to keep whole, so the
exposure is limited to cross-spec frontend regressions, caught at the final
pass. The measured caveat: 52% of invocations already narrow scope, so the
marginal gain is smaller than the arithmetic suggests — this mostly converts an
existing informal practice into a stated, reviewable one.

### R5 — Split a fast and slow tier
**Saves ≈ 27 s of wall per iteration pass. Effort: small. Risk: medium. Coverage lost: real but bounded.**

`frontend-sanity.spec.ts` is 18 tests and 28.9% of all test time (§1.5). It is a
broad panel walk that overlaps substantially with the dedicated per-feature
specs. Tag it (and `content-reachability`, 7.9%) as a slow tier that runs on the
final pass only.

What it gives up: `frontend-sanity` is exactly the test most likely to catch a
regression in a panel the agent was not thinking about — its breadth is the
point. Deferring it to the final pass keeps that safety net for the handoff but
removes it during iteration. Reasonable; should be a conscious choice.

### R6 — Leave `--workers=2` alone
**Effort: none. Recommendation: no change.**

On a contended box `--workers=4` is 18% faster for the individual run (§3.2),
but the gain is taken from concurrent agents, and it does not reduce the flake
rate (2 failures at both 2 and 4 workers; 3 at 1 worker). Raising the default is
zero-sum system-wide and would worsen §3.4. Revisit only if agent concurrency
drops or the box gets more cores.

### Rejected

**R-rej-1 — Share or cache `node_modules` / `.venv` across worktrees.**
Rejected: the entire install cost is **≈ 2.5 s** (§1.1), because `uv` and `pnpm`
already share content-addressed stores machine-wide and hardlink into each
worktree. There is nothing to win, and a shared mutable `node_modules` or a
shared `.venv` reintroduces exactly the §6.2 class of failure — an environment
that drifts from the project it is meant to be testing. Maximum saving 2.5 s
against a real correctness risk.

**R-rej-2 — Skip `pnpm build` when the bundle is unchanged.**
Rejected as stated: `vite build` re-runs in full (17.44 s re-run vs 18.81 s
cold, §1.2), so there is no incremental path to switch on, and a
content-hash-based skip is precisely the mechanism that produced the §6.1
incident. R1 already removes the *duplicate* build, which is the recoverable
part; the remaining single build is the price of knowing what is being tested.

**R-rej-3 — A long-lived shared preview server across worktrees.**
Rejected at present. It would save the ~19 s boot-and-build per run, but it is
the direct cause of the §6.1 failure, and a server shared *across worktrees*
serves one worktree's bundle to another's tests. It becomes defensible only
after R1's bundle-stamp assertion exists — at which point it is worth
revisiting, since ~19 s per run is real money.

---

## 8. Summary

| | per full pass |
| --- | ---: |
| measured today (quiet box) | **206 s** |
| after R1 + R2 (no coverage change) | **≈ 162 s (−21%)** |
| after R4 + R5, on iteration passes only | **≈ 60–70 s** |

Verification is **17% of aggregate task wall clock, 6% at the median, and
30–52% for tasks that genuinely exercise the loop**. It is not the reason long
tasks are long. The strongest argument for acting here is not the seconds: it is
that at current agent concurrency the suite reports two or three false failures
per full run, and an agent cannot tell those from real ones.
