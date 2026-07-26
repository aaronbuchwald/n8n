# Auditing a grouping strategy

The checklist behind Job 2 of `SKILL.md`. Its purpose is to keep the conventions
honest once there are five strategies instead of two: a contract nobody re-reads
decays into a comment, and the decay is invisible because a drifted strategy
still returns groups and still renders a card.

Run it against one strategy at a time. Every finding cites the rule it breaks.

## 0. Set up

```bash
cd graph-engine
ls nodepacks/grouping/                       # what exists
uv run --extra sym --extra dev python -c "import grouping; print(grouping.strategy_names())"
```

Read, in this order: `docs/grouping-strategies.md` (the contract),
`nodepacks/grouping/contract.py` (the enforcement), the strategy under audit,
and `nodepacks/grouping/tiered.py` (the reference implementation).

Anything the strategy is *entitled* to do differently from `tiered` must be
justified in its docstring. An unexplained difference is a finding.

## 1. Contract

| # | Check | How |
|---|---|---|
| 1.1 | Signature is `(population, params) -> list[Group]` | read |
| 1.2 | Returns `Group` instances, not dicts | read |
| 1.3 | `key` is a valid identifier and unique per result | read + test |
| 1.4 | `label` states the *rule*, not just an ordinal (`[150, ∞) kN`, not `Tier 1`) | read |
| 1.5 | `members` holds the records **as handed in** | read |
| 1.6 | Never returns an empty group | read + test |
| 1.7 | Never invents, copies or drops a record | read + test |
| 1.8 | Does not re-validate the population (`apply_strategy` did) | read |

Invariants 1–5 are enforced at runtime by `check_invariants`, so a violation is
a `StrategyContractError` in tests rather than a wrong drawing set. Confirm the
strategy is actually reached through `apply_strategy` and not called directly
anywhere.

## 2. Determinism and order-independence — the decaying pair

The runtime cannot check these, so they are where drift lands. Grep first, then
read every hit:

```bash
cd graph-engine/nodepacks/grouping
grep -nE 'max\(|min\(|sorted\(|set\(|\.keys\(\)|random|datetime|time\.|id\(' <name>.py
```

| Pattern | Verdict |
|---|---|
| `max(members, key=force_of)` | **violation** — ties break by iteration order. Use `governing_by_magnitude`. |
| `min(...)`/`max(...)` over records with a non-total key | violation — same reason |
| `sorted(bucket_dict)` | fine — sorting the *keys* makes group order data-driven |
| iteration over a `set` | violation — set order is not a function of the data |
| `random`, `datetime`, `time`, `id(...)` in the result | violation — not deterministic |
| relying on the population's index/position | violation of order-independence |

Prove it rather than argue it — the shared test does exactly this, over three
seeds:

```python
shuffled = list(population); random.Random(seed).shuffle(shuffled)
assert summary(apply_strategy(name, shuffled, params)) == summary(apply_strategy(name, population, params))
```

where `summary` includes each group's **governing `ref`**, not only its value. A
summary that compares values alone will pass while the cited export row flips.

## 3. Registration

- Registered exactly once, at module bottom, via `register(name, fn, summary=…)`.
- Imported in `nodepacks/grouping/__init__.py` (that import *is* the
  registration) with the `# noqa: F401 - imported for its registration` comment.
- `summary` is one line, present, and still describes what the code does — it is
  printed by every unknown-strategy error, so a stale summary misleads at exactly
  the moment someone is lost.
- The name is not a near-miss of an existing one (`tier` vs `tiered`) unless that
  is deliberate.

## 4. Parameters

- `reject_unknown_params(params, strategy=…, accepted=ACCEPTED_PARAMS)` is called
  **before** anything else. Missing this is the highest-value finding in the
  whole checklist: without it a typo silently disables the parameter.
- `ACCEPTED_PARAMS` matches what the code actually reads (grep `params.get` /
  `params[`).
- Every accepted key is validated for **type, finiteness, range and ordering**,
  each with its own message.
- No parameter is silently normalised — sorting a user's list, coercing a string
  to a number, or defaulting a required key are all findings. Refuse instead.
- Every message names the offending value and says what is acceptable.

## 5. Provenance

- `governing` is obtained *from* `members` (`governing_by_magnitude(members)` or
  an equivalent selection), never constructed.
- No `dict(record)`, `{**record}`, `copy`, or projection to a bare float anywhere
  in the module.
- If the strategy reads an extra key off a record (a support id, a member
  family), it errors clearly when the key is absent rather than defaulting.

Invariant 4 rejects an *equal but distinct* record, so a strategy that rebuilds
one fails loudly — confirm there is a test that would catch it if the invariant
were ever relaxed.

## 6. Documentation

- The module docstring answers all four design questions of the guide §4:
  what governs, what happens at a boundary, what an empty group means, how
  provenance is preserved.
- `docs/grouping-strategies.md` has a `## Worked example:` section for it.
- Every number in that section is still true — re-derive the distribution:

```bash
cd graph-engine && uv run --extra sym --extra dev python -c "
import grouping, rfem
ends = rfem.member_ends(rfem.read_extrema('examples/beam_bearing_pressure_rfem/export.csv'), 'Vz')
for g in grouping.apply_strategy('<name>', ends, {...}):
    print(g.key, g.label, g.count, g.governing['value'], g.governing['ref'])
"
```

- The guide's own claims still hold across the whole pack: that `single`
  reproduces `rfem.governing_force`'s 297.175507, and that the shipped table of
  files is complete.

## 7. Tests

- The strategy is in `SHIPPED` in `tests/test_grouping_strategies.py` — that is
  what buys the invariant, determinism and order-independence coverage.
- Strategy-specific tests exist for: the boundary case at an *exact* edge; every
  parameter error; the empty-group behaviour; and the distribution on the demo
  export.
- Error assertions match on the *sentence*, not just the exception type — a
  message is a feature here.

## 8. Layering

```bash
grep -nE '^(from|import) ' nodepacks/grouping/<name>.py
```

Only `engine`, the standard library, and `.contract` / `.registry` may appear.
An import of `rfem`, `sheet`, `calcsheet`, `server`, or an example module is a
layering violation: it makes the strategy unusable on any other population and
is the fastest way to lose the abstraction.

## 9. Report

```
| file:line | finding | rule | fix |
|---|---|---|---|
| tiered.py:118 | `max(members, key=force_of)` | invariant 7 (order-independence) | use `governing_by_magnitude` |
```

Then one of:

- **clean** — no drift found;
- **drift** — conventions or documentation are out of step; behaviour is correct
  today but the next change is likely to break it;
- **contract violation** — behaviour is wrong now; name the invariant and the
  input that exposes it.

Do not apply fixes unless asked. An audit that silently edits cannot be trusted
to have found everything, because there is nothing left to read.
