---
name: n8n:grouping-strategy
description: >-
  Authors and audits grouping strategies for the graph-engine project — the
  pluggable rules that divide a population of member-end forces into connection
  groups (graph-engine/nodepacks/grouping). Use when adding, changing or
  reviewing a grouping strategy; when a request describes a new way to split
  member forces into groups, tiers, bands or connection types; or when checking
  an existing strategy against its contract. Trigger words: grouping strategy,
  connection group, tiered, load tier, threshold, governing force, member ends,
  group_card, apply_strategy.
---

# Grouping strategies: author and audit

A **grouping strategy** answers one question: *given the forces at every member
end, how are they divided into groups, each of which gets one connection
design?* This skill has two jobs — **author** a new one, and **audit** an
existing one. Read the full guide before either:
`graph-engine/docs/grouping-strategies.md`.

**Layout.** Contract `nodepacks/grouping/contract.py` · registry `registry.py` ·
shipped strategies `single.py`, `tiered.py` · node `grouping.group` in
`__init__.py` · summary card `sheet.group_card` · tests
`tests/test_grouping_strategies.py` · example
`examples/beam_bearing_pressure_tiered/`.

**Verify with** `cd graph-engine && uv run --extra sym --extra dev python -m pytest -q`.
(`uv run --extra sym pytest` resolves a global pytest and collects nothing — use
`python -m pytest`.)

## The contract in one screen

```python
def my_strategy(population, params) -> list[Group]: ...
```

- **`population`** — a tuple of force records, already validated: each a mapping
  with a finite `value` (the magnitude), a `unit` (all records agree), a `ref`,
  plus opaque provenance. Read `value`; treat the rest as untouchable.
- **`params`** — the strategy's own namespace from `inputs.json`'s
  `{"strategy": …, "params": {…}}`. Validate it yourself; raise
  `engine.UserError`; **refuse** a key you do not read.
- **returns** an ordered `list[Group(key, label, members, governing, extra={})]`.
  `key` is a Python identifier (it becomes a symbol suffix on the card); `label`
  is what a reviewer reads; `count` is derived from `members`.
- **run only via** `grouping.registry.apply_strategy(name, population, params)`,
  which validates the population before and checks invariants after — for every
  strategy alike, with no fast path for any of them.

**Invariants** — 1 total, 2 exclusive, 3 non-empty groups, 4 `governing` is
*identically* one of the group's own `members`, 5 keys are unique identifiers
(all enforced at runtime); 6 deterministic and 7 order-independent (yours, proved
by tests).

## Job 1 — Author

Work in this order. Do not skip step 1; it is the step that makes the rest
decidable.

1. **Answer the four design questions in prose**, in the module docstring:
   - *What governs a group?* (largest magnitude is common, not mandatory)
   - *What happens at a boundary?* (pick half-open `[lower, upper)` unless you
     have a reason; state which side a value on the edge falls)
   - *What does an empty group mean?* (an error by default — say why if not)
   - *How is provenance preserved?* (by carrying record objects through untouched)

2. **Write `graph-engine/nodepacks/grouping/<name>.py`.** Copy the shape of
   `tiered.py`: docstring answering the four questions, `ACCEPTED_PARAMS`, a
   private `_validate(params)`, the strategy function, then `register(...)` with
   a one-line `summary` (it is what an unknown-name error prints).

3. **Register it** — one line in `nodepacks/grouping/__init__.py`:
   `from . import <name> as <name>  # noqa: F401 - imported for its registration`.
   Nothing else changes. If you find yourself editing a dispatch chain or an
   error message to mention the new name, you are doing it wrong.

4. **Add it to `SHIPPED`** in `tests/test_grouping_strategies.py`. That table
   parametrises every invariant, determinism and order-independence test over the
   real 184-row export, so the whole contract now covers you for free. Then add
   the tests only you can write: the boundary case at an exact edge, each
   parameter error, and the distribution your rule produces on that data.

5. **Add a `## Worked example:` section** to `graph-engine/docs/grouping-strategies.md`
   — the code, the four answers, the distribution on the demo export.

6. **Run the audit below** on what you wrote, then the test suite.

### Conventions the shipped strategies follow

- Use `governing_by_magnitude(members)`, never `max(members, key=force_of)` —
  `max` breaks ties by iteration order, which violates invariant 7.
- Use `reject_unknown_params(params, strategy=…, accepted=…)` first thing.
- Never re-validate the population; `apply_strategy` already did.
- Errors name the offending thing **and** what the data actually is, so the fix
  is in the message (`tiered`'s empty-tier error prints the range the population
  spans).
- Do not sort or otherwise reinterpret a user's parameters — refuse them.
- Keep the module pure stdlib and free of any knowledge of RFEM, bearing
  pressure or cards. If you need a column name, you are in the wrong pack.
- JSON-safe values only in `extra` — no `inf`/`nan` (they end up in a written
  artifact; `tiered` spells an open upper bound `None`).

## Job 2 — Audit

Audit when reviewing a change, when a strategy predates a contract change, or on
request. Report **drift**, not style: every finding cites the invariant or
convention it violates and names the file and line.

Read `audit-checklist.md` for the full checklist and the commands. In short:

1. **Contract** — signature, the five runtime invariants, and the two the runtime
   cannot check (determinism, order-independence). Order-independence is the one
   that decays silently; grep for `max(` / `min(` over members, `sorted(` without
   a total key, `set(` iteration, `dict` ordering assumptions, `random`,
   `datetime`, `id(`.
2. **Registration** — registered exactly once, imported in `__init__.py`,
   `summary` present and accurate, name not colliding.
3. **Parameters** — `reject_unknown_params` called; every accepted key validated
   for type, range and ordering; every message actionable.
4. **Provenance** — `governing` comes out of `members` by identity; no record is
   rebuilt, copied or reduced to a number anywhere in the module.
5. **Documentation** — the four design questions answered in the docstring; a
   worked-example section in the guide; the guide's claims still true.
6. **Tests** — present in `SHIPPED`; boundary, empty-group and parameter-error
   tests exist; the documented distribution matches what the code produces.
7. **Layering** — no import of `rfem`, `sheet`, `calcsheet` or any node module
   from a strategy.

Deliver a table of `file:line` · what · which rule · suggested fix, then a
verdict: **clean**, **drift** (fixable in place), or **contract violation**
(behaviour is wrong today). Write the fix only if asked; an audit that silently
edits is not an audit.
