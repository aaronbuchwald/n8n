# ADR 0016 — Single-source check: the assertion is a calc line

Status: **accepted** · Scope: `graph-engine/examples/capacity_check/` and its
tests — **no engine change, no nodepack change** · Relates to: ADR 0004
(graph ⟷ source bijection; D7 straight-line form), ADR 0007 (derived handcalc
sockets), ADR 0010 (renderers), ADR 0015 (instance-vs-definition — its branch
touches the same example file, see Build plan §coordination).

Numbering note: ADR 0015 (`docs/adr-0015-instance-vs-definition`) is the
highest-numbered ADR across `integration/wave-1`, all `docs/adr-*` branches,
and origin as of 2026-07-23; **0016 is free** (0012 was never used — the gap is
pre-existing, not this ADR's to fill).

Scope note, stated up front: an earlier sketch of this work included an
**action handler** — "on FAIL, do something" (branching, side effects,
notifications). That concept is **aborted here and deferred to a future ADR**.
This ADR does exactly one thing, for simplicity: make the PASS/FAIL judgment
derive from the calculation's own computed result instead of a parallel
re-derivation.

## Problem — the verdict is a second source of truth

`examples/capacity_check/capacity_check.py` computes the margin once and then
*judges* it from a different computation (line numbers on `integration/wave-1`):

- line 118 — `handcalc(lines="margin = C_min - F_max", C_min=…, F_max=…)`
  computes and typesets the margin;
- line 123 — `check_capacity(force=max_force.value, capacity=min_capacity.value)`
  **re-derives the comparison from the raw inputs**: `ok = force < capacity`
  (line 91), plus its own hand-built text `"PASS — 120 < 210"`.

`force < capacity` and `margin > 0` are the same judgment — but nothing ties
them together. Change the equation (say, `margin = 0.9 * C_min - F_max` to add
a safety factor) and the card still says `PASS — 120 < 210`: the math block and
the verdict silently disagree. The duplication is visible in today's run
output — the caption states the same fact twice, from two computations:

```
C_min = 210 · F_max = 120 · margin = 90 · PASS — 120 < 210
                            └── from the calc ┴── re-derived from raw inputs
```

**Why the split exists** (and why its rationale is stale): the module docstring
(lines 15–19) and `check_capacity`'s docstring argue the check "does not go
through SymPy: feeding concrete numbers into a symbolic inequality
(`Lt(120, 210)`) would auto-collapse to `True` and lose the '120 < 210'
itself". That is true **of SymPy relational objects** — and irrelevant to
handcalcs, which renders at the *source* level, never building an `Lt`. The
verified finding below shows handcalcs typesets a comparison line with the
substituted numbers intact. The parallel derivation was built to dodge a
problem the rendering library does not have.

## Finding — handcalcs renders assertion lines natively (verified, decisive)

Verified by running the pack's own nodes (`nodepacks/sym/__init__.py::
typeset_calc` / `handcalc`) under `uv run --extra sym` (handcalcs 1.11):

**A comparison assignment is a first-class calc line.** For
`lines = "margin = C_min - F_max\ncheck = margin > 0"` with
`C_min=210, F_max=120`, handcalcs emits:

```latex
\begin{aligned}
\mathrm{margin} &= C_{min} - F_{max}  = 210.000 - 120.000 &= 90.000
\\
\mathrm{check} &= \mathrm{margin} \gt 0  = 90.000 \gt 0 &= True
\end{aligned}
```

— symbolic form, **substituted comparison (`90.000 > 0`)**, and boolean
result, exactly the "check line with a verdict mark" shape we want, with no
SymPy collapse. The fail case (`C_min=100`) renders
`check = margin > 0 = -20.000 > 0 = False`. handcalcs does this because a
comparison is just an expression on an assignment's RHS; its documented
conditional rendering (`if b < d/2: …`) is the same machinery and is *not*
needed here.

The rest of the chain accepts it unchanged (all verified end-to-end through
`to_graph → run → to_python` on this branch):

- **Deriver** (`sym.calc_free_symbols`, ADR 0007): `check = margin > 0` is a
  single-Name assignment; `margin` is already an LHS, so derived sockets stay
  exactly `{C_min, F_max}` — no spurious inputs.
- **`latex_to_mathml`**: `\gt` converts (`<mo>&#x0003E;</mo>`); each aligned
  row becomes its own `<math display="block">`, so the check renders as its own
  line under the equation. `render_math_card`'s markup guard passes.
- **`results`** socket gains the computed names: `{C_min: 210, F_max: 120,
  margin: 90, check: True}` — the boolean is *data on a wire*, available to a
  consumer without recomputing anything.
- **Bijection**: the two-line `lines` literal round-trips through `to_python`
  as `lines='margin = C_min - F_max\ncheck = margin > 0'` — one literal on one
  wiring statement, per ADR 0004 D5/D7.

**One engine constraint that shapes Option A** (`engine/composite.py`,
reference resolution): `x.s` and `x["s"]` both resolve to *(node, socket)* —
one level, whole sockets only. `steps.results["margin"]` (a key inside a
dict-valued socket) is **not expressible as a wire**, so any node consuming
the computed margin must take the whole `results` dict and pick inside.

## Options weighed

### Option A — rewire the verdict onto the computed margin

Keep a separate check node, but feed it the calc's output instead of the raw
extremes: `verdict = check_margin(results=steps.results)` with the node doing
`ok = results["margin"] > 0`. (Not `check_capacity(margin=steps.results["margin"])`
— sub-socket wires don't exist, per the engine constraint above.)

- Smallest conceivable diff; the `handcalc → check` wire becomes visible.
- **But the assertion itself still lives outside the calc**: the direction and
  threshold (`> 0`) are Python in a node body, invisible in the rendered math;
  the card's math block shows no check row; and the node still hand-formats a
  comparison string for the caption — a residual second display surface. The
  *value* is single-sourced; the *judgment* is not.

### Option B-full — a new `sym.check` node (handcalc + assertion + verdict in one)

A new/extended sym node taking calc lines + assertion, emitting
`latex/results/ok/message`. Truly one node, and it would delete
`check_capacity`. Rejected **for now**: it adds a node type, spec, derived-
socket interplay and schema surface to solve a problem the finding shows the
*existing* `handcalc` node already solves for the math; the only genuinely new
part (bool → ok/message) doesn't justify a pack node until a second example
needs it. Deferred; see FOR REVIEW.

### Option B (recommended) — the assertion is a line of the calc

Write the assertion as one more assignment line in the **same `lines` field of
the existing `handcalc` node**, and shrink the check node to a *formatter* of
the already-computed boolean:

- `lines = "margin = C_min - F_max\ncheck = margin > 0"` — equation and
  assertion in one block, one field, one node. handcalcs typesets both, with
  the substituted comparison (verified above).
- `check_capacity(force, capacity)` is **replaced** by an example-local
  `check_verdict(results, check="check")` that reads `results["check"]` and
  emits `ok` (the boolean) and `text` (`"PASS"`/`"FAIL"`). It contains **no
  comparison** — like `calc_notes`, it is presentation over the calc's own
  results dict, wired from `steps.results`.

This is Option B's assertion form at Option A's footprint: zero engine change,
zero sym-pack change, example-only. Recommended because it is the only variant
where the judgment exists **exactly once, in the user-visible calc text**, and
the rendered card proves it (the check row shows the substituted numbers).

> **FLAGGED for sign-off:** the recommendation is this hybrid — "assertion as
> a calc line" (B's form) realized without a new node type (A's footprint).
> If reviewers prefer literal-A (comparison stays in Python) or literal-B-full
> (new sym node now), the sections above give the trade-offs.

## Decisions

### D1 — The assertion is a calc line; the calc is the single source

The comparison that decides PASS/FAIL is written as an assignment line
(`check = margin > 0`) in the same `lines` value as the equation it judges.
No other node may compute a comparison over the raw quantities. The deriver's
existing single-assignment rule (ADR 0007) is why it's an *assignment* — a
bare expression line `margin > 0` is rejected today, and we do not change the
deriver (see FOR REVIEW).

### D2 — The verdict node formats; it never calculates

`check_verdict(results: dict, check: str = "check") -> {ok, text}`:
`ok = bool(results[check])`, `text = "PASS" if ok else "FAIL"`. A missing key
raises `UserError` naming the key and the available results — so renaming the
`check` symbol without updating the param is a **loud run-time error**, never a
silently stale verdict (the failure mode this ADR exists to kill). It stays
**example-local** (in `capacity_check.py`, replacing `check_capacity` in
`NODES`), UI-agnostic, pure stdlib — promotion to the sym pack is deferred
until a second example wants it.

> **Owner override (supersedes the D2 shape above, as implemented):**
> `check_verdict(results, check="check") -> {ok}` **raises on a false result**
> instead of returning a `text` fragment — a False `check` reddens the node (and
> the raise stops the run); on pass it is a no-op returning `{ok: True}`.
> "Nothing more than red" — no action handler, no branching. The **PASS/FAIL
> caption text is dropped entirely**: the `check = margin > 0 = 90.000 > 0 =
> True` line inside the handcalc card is the visible verdict, so the caption is
> `calc_notes` only and `join_text` is no longer used by this example (it stays
> in the sym pack, unused here). A failing run may not render the downstream
> card at all — accepted and intended.

### D3 — No engine or nodepack change

Engine stays pure stdlib and untouched; `sym` pack untouched (verified: the
current `handcalc`/`calc_free_symbols`/`latex_to_mathml`/`render_math_card`
already handle every artifact of the assertion line). The diff is confined to
`examples/capacity_check/` + its tests.

### D4 — Retire the stale SymPy rationale

The module and node docstrings claiming the comparison "can't" be typeset
(SymPy `Lt` collapse) are removed/corrected: true of SymPy relationals,
irrelevant to handcalcs. Leaving that text in place is what licensed the
parallel derivation.

### D5 — Action-on-fail is out of scope

`ok` is a boolean output socket and `text` is a caption fragment. Nothing
branches on them, nothing fires from them. Any "when the check fails, do X"
behavior (notifications, gating downstream nodes, run status) is a **future
ADR** — deliberately aborted here to keep this change single-purpose.

> **Owner override note (as implemented):** the one on-fail behavior that *is*
> shipped is the raise inside `check_verdict` — a false `check` reddens the node
> via a `UserError`, nothing more. There is still **no action handler and no
> branching**; that richer behavior remains deferred to a future ADR. `ok` is a
> leaf output consumed by nothing, and `text` no longer exists (the PASS/FAIL
> caption is dropped — see the D2 owner override).

## The idealized `capacity_check`, end to end (all values verified by running it)

**Inputs — the two extremes** (from the committed CSVs):

| arc | file | selection | extreme |
|---|---|---|---|
| forces | `forces.csv` (`F1,80 · F2,120 · F3,45`) | `select_extreme(max, "force")` | `F_max = 120` (F2) |
| members | `members.csv` (`M1,300 · M2,210 · M3,275`) | `select_extreme(min, "capacity")` | `C_min = 210` (M2) |

**Formula + assertion — the single source** (the `lines` literal of the one
`handcalc` node):

```python
margin = C_min - F_max
check = margin > 0
```

**The rewritten `@main`** (straight-line, ADR 0004 D7 — each call its own
assignment; verified to trace, run, and round-trip through `to_python`):

```python
@main
def capacity_check_report(
    forces_path: str = "forces.csv", members_path: str = "members.csv"
) -> str:
    """Read both CSVs, pick the extremes, typeset the margin, and check it."""
    forces = read_table(path=forces_path)
    members = read_table(path=members_path)

    max_force = select_extreme(forces, column="force", mode="max")
    min_capacity = select_extreme(members, column="capacity", mode="min")

    # ONE calc block: the equation and the assertion that judges it. The free
    # symbols (C_min, F_max) are derived sockets (ADR 0007); `margin` and
    # `check` are computed results — there is no other computation of either.
    steps = handcalc(
        lines="margin = C_min - F_max\ncheck = margin > 0",
        C_min=min_capacity.value,
        F_max=max_force.value,
    )
    mathml = latex_to_mathml(steps.latex)

    # Verdict = presentation of steps.results["check"]. No comparison here.
    verdict = check_verdict(results=steps.results)

    notes = calc_notes(steps.results)
    caption = join_text(notes, verdict.text)
    report = render_math_card(title="Capacity check", mathml=mathml, caption=caption)
    return report
```

Dataflow (node ids = variable names, ADR 0004 D3) — note `check_verdict` now
hangs off `steps.results`, not off the raw extremes:

```
max_force.value ────┬─> steps (handcalc)  "margin = C_min - F_max ⏎ check = margin > 0"
min_capacity.value ─┴─────┬────────────┬──────────────┐
                    steps.latex   steps.results   steps.results
                          │            │              │
                       mathml        notes         verdict (check_verdict) ─ text ─┐
                          │            └──────────────┴──> caption (join_text) <───┘
                          └──────────────────────────────> report (render_math_card)
```

**Display — the rendered card** (MathML rows from the verified LaTeX):

```
┌─ Capacity check ───────────────────────────────┐
│  margin = C_min − F_max = 210.000 − 120.000    │
│                                      = 90.000  │
│  check = margin > 0 = 90.000 > 0 = True        │   ← substituted assertion
│                                                │
│  C_min = 210 · F_max = 120 · margin = 90       │
│  · check = True · PASS                         │   ← caption: notes + verdict
└────────────────────────────────────────────────┘
```

Fail case (e.g. capacities edited so `C_min = 100`): the same single edit
surface yields `margin = −20.000`, `check = margin > 0 = −20.000 > 0 = False`,
caption `… · margin = -20 · check = False · FAIL` — math block, results and
verdict cannot disagree because they are one computation.

**Outputs** (verified run values for the committed CSVs):

| socket | value |
|---|---|
| `steps.latex` | aligned block: equation row + assertion row (above) |
| `steps.results` | `{C_min: 210.0, F_max: 120.0, margin: 90.0, check: True}` |
| `mathml` | two `<math display="block">` rows (zero-JS, CDN-free) |
| `verdict.ok` | `True` |
| `verdict.text` | `"PASS"` |
| `report` | self-contained HTML card (ADR 0010 `html-card` renderer) |

## Verification criteria (testable, each maps to a test in the build plan)

1. **No parallel re-derivation.** No node body in the example compares the raw
   quantities: `check_capacity` is gone; `check_verdict` contains no `<`/`>`
   over values (only `bool(results[key])`). The string `force < capacity`
   exists nowhere; the only comparison text in the module is the calc line.
2. **One edit updates everything.** Changing the formula to
   `margin = 0.9 * C_min - F_max` (one edit, the `lines` literal) changes the
   math block, `results`, notes, **and** the verdict coherently
   (`margin = 69 → PASS`; with `0.5` → `−15 → FAIL`) with **no second edit**.
   Same for changing the assertion itself (`check = margin > 10`).
3. **The card shows the substituted assertion.** Rendered HTML contains the
   check row with substituted values (`90.000 > 0` as MathML) and the
   PASS/FAIL word in the caption — asserted on the run output.
4. **Run output consistent.** `verdict.ok == steps.results["check"]`, and the
   caption's PASS/FAIL agrees with the math block's `True`/`False` — a single
   execution feeds all three surfaces.
5. **Loud, not silent, on rename.** Renaming the `check` symbol in `lines`
   without updating `check_verdict`'s `check` param raises `UserError` listing
   the available result names (asserted); it can never yield a stale verdict.
6. **Bijection intact.** `to_graph → to_python` round-trips the two-line
   `lines` literal on one wiring statement; graph shape is unchanged except
   `check_capacity` → `check_verdict` with its single `results` wire; existing
   served-graph and picker flows keep working with the new node id.

## Build plan (implementation PR, separate from this ADR)

1. `examples/capacity_check/capacity_check.py`: extend the `lines` literal
   with the assertion line; replace `check_capacity` with `check_verdict`
   (D2); update `NODES`; rewrite the module docstring — dataflow diagram
   (verdict hangs off `steps.results`) and drop the SymPy-collapse rationale
   (D4).
2. `tests/test_capacity_check_example.py`: replace the `check_capacity`
   pass/fail unit tests with `check_verdict` pass / fail / missing-key
   (UserError) tests; update graph-level assertions (node id, caption now
   `… · check = True · PASS`, no `120 &lt; 210`; `lines=` source assertion is
   now the two-line literal); add the one-edit criterion (#2) and the
   consistency criterion (#4).
3. `tests/test_capacity_check_served.py`: served `results` set becomes
   `{C_min, F_max, margin, check}`; source endpoint id
   `capacity_check.check_verdict`.
4. `web/tests/graph-picker.spec.ts`: node id `check_capacity` →
   `check_verdict` (two occurrences).
5. No schema-snapshot churn: `freeze_schemas.py` snapshots only
   `examples/minimal` (verified).
6. Run: `uv run --extra sym python examples/capacity_check/capacity_check.py`,
   the Python test suite, and the web picker spec.

**Coordination:** branch `docs/adr-0015-instance-vs-definition` edits the same
module docstring/comments (dataflow walkthrough). Whichever lands second
rebases; the diagrams must both show the `steps.results → verdict` wire once
this ADR is implemented.

## MAJOR DECISIONS / FOR REVIEW

1. **Option choice (flagged):** recommended B — "assertion is a calc line" —
   realized with no new node type. Literal Option A (comparison stays in a
   Python node, fed the results dict) and Option B-full (new `sym.check` node)
   are written up above with trade-offs; pick B unless the calc-line syntax is
   objectionable.
2. **Assertion syntax:** `check = margin > 0` (assignment form). A bare
   expression line `margin > 0` is rejected by the ADR 0007 deriver's
   single-assignment rule; accepting it would be a deriver change — not
   proposed. Is the named-boolean idiom acceptable as *the* convention?
3. **handcalcs rendering finding:** the assertion typesets natively inside the
   same block, substituted, with `True`/`False` (verified, quoted above). This
   is what makes B free. Reviewers should note the existing docstring's SymPy
   rationale is thereby obsolete (D4).
4. **Verdict-key convention:** `check_verdict(results, check="check")` reads a
   named boolean; renaming the symbol requires updating the param, failing
   **loudly** if forgotten (criterion #5). Rejected alternative: auto-detect
   "the last boolean result" — survives renames but is implicit magic.
5. **Caption redundancy:** notes render `check = True` and the verdict adds
   `PASS` — the boolean appears twice in the caption. Kept for simplicity
   (calc_notes untouched); alternatives (filter booleans in `calc_notes`, or
   drop `notes`' check entry) are sym-pack changes. Cosmetic call.
6. **`True`/`False` typography:** handcalcs emits the bare word, which
   latex2mathml sets as italic letters (`<mi>T</mi><mi>r</mi>…`). Cosmetic;
   prettifying (e.g. ✓/✗ or upright text) would be a sym-side LaTeX
   post-pass — deferred.
7. **Node name:** `check_verdict` (alternatives: `verdict`, `calc_verdict`).
8. **Promotion path:** if a second example needs a verdict, promote
   `check_verdict` to the sym pack — or revisit Option B-full then.
9. **What the aborted action-handler leaves open:** `verdict.ok` is emitted
   but nothing consumes it beyond the caption. Whether a failing check should
   affect run status, gate downstream nodes, or trigger actions is explicitly
   a future ADR (D5).
