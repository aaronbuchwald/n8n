# ADR 0020 — Multi-line string literals in generated source

Status: **accepted** (2026-07; all five open questions confirmed at their
recommended defaults — see the end) · Scope: `graph-engine/` ·
Relates to: ADR 0004 (D5 literals, D7 straight-line form, Amendment A1),
ADR 0007 (derived-input params `formulas` / `lines` are the multi-line values
in practice), ADR 0018 (the multi-line *editor* for these same literals — this
ADR is the source-side counterpart of that inspector work).

## Context — the problem, in the real bytes

A calc literal is inherently line-oriented: the whole `sheet.calc_card` /
`sym.handcalc` mini-syntax is "one entry per line" (ADR 0007, ADR 0018). But
every path that *writes* source renders a string literal with `repr()`:

- `engine/composite.py::_render_value` — `return repr(bound.literals[param])`
  — used by both `to_composite` (fresh emit) and `wiring_lines` (the in-place
  write-back's statement emitter).
- `server/writeback.py::compute_writeback` — builds `line_by_id` as exactly
  **one line per node** from `wiring_lines` and splices those lines into the
  real `.py`.

`repr()` of a string containing newlines produces one physical line with
escaped `\n`s, so after a UI edit the module on disk reads:

```python
    card = calc_card(title='Capacity check', as_of='2026-07-24', formulas='r = F_max / C_min  # demand / capacity\nU = 100 * r [%]  # utilisation', checks='U < 100  # capacity not exceeded\nU < 50  # utilisation target', F_max=F_max, C_min=C_min)
```

This is pinned today by `web/tests/formula-editing.spec.ts` ("`repr()`
writeback keeps it ONE literal with escaped newlines"). The owner's ask: write
multi-line values back as **properly formatted multi-line Python**, and make
the bijection handle that shape identically in both directions, everywhere
source is written.

The value on the graph side is untouched by this ADR: a widget literal remains
the exact string (`"r = …\nU = …"`). Only its **spelling in the composite
text** changes.

## Non-negotiables (each verified against the code)

1. **Round-trip fidelity.** `from_composite(to_composite(g)) == g` byte-exact
   on every literal — no leading-whitespace injection, no lost/added trailing
   newline (`tests/test_composite.py::_assert_roundtrip_identity`,
   `tests/test_handcalc_bijection.py::test_roundtrip_multiline_calc`).
2. **Idempotence / stability.** `to_composite(from_composite(s)) == s`
   (`test_source_idempotence_*`), and a no-op save leaves the file
   byte-identical (`tests/test_writeback_fidelity.py::
   test_no_op_save_leaves_the_file_byte_identical`). Write-back compares
   statements by *parsed meaning* (`writeback.py::_signature`), so a format
   change may only ever appear on a statement the save actually re-emits.
3. **Parse accepts what emit produces — and more.** A human may hand-type any
   spelling of the same string; `from_composite` must keep accepting all of
   them (it reads `ast.Constant` / `ast.literal_eval`, not bytes).
4. **Escaping correctness.** Embedded quotes, backslashes (LaTeX-ish calc
   lines), a value containing `"""`, trailing quotes/newlines must all
   round-trip.
5. **Single-line values stay single-line.** `title='Capacity check'` must not
   grow parentheses. The switching predicate must be a pure function of the
   value so the file cannot thrash.

## Options considered

The hard constraint framing all four: a triple-quoted string inside an
indented function body takes its content **literally** — indentation either
becomes part of the value (silently changing what the calc computes) or the
content sits at column 0 (fighting the surrounding indentation).

### Option 1 — Triple-quoted string at the call site

```python
    card = calc_card(
        formulas="""r = F_max / C_min  # demand / capacity
U = 100 * r [%]  # utilisation""",
        ...
    )
```

- To keep bytes exact the content lines must start at **column 0** — visually
  broken inside a 4/8-space-indented call, which is the "properly formatted"
  bar this ADR exists to meet. Indenting the content instead injects
  whitespace into the value; the calc mini-syntax happens to strip per-line
  whitespace (`sheet._entries` does `raw.strip()`), but the bijection contract
  is byte fidelity of the *value*, and `_signature` would see a different
  string → every save re-patches the statement → churn.
- Escaping is delicate: inside triple quotes a backslash is still an escape
  character, so a calc line containing `\nu` (LaTeX) corrupts unless every
  backslash is escaped — at which point readability is gone. A value
  containing `"""` (or ending in `"` or `\`) forces delimiter/escape
  gymnastics.
- Parse side: fine as-is (a triple-quoted string is one `ast.Constant`).

**Verdict: rejected as the emitted form** (kept as an *accepted input* form —
it parses today with zero changes).

### Option 2 — Parenthesized implicit string concatenation ✅ recommended

```python
    card = calc_card(
        formulas=(
            'r = F_max / C_min  # demand / capacity\n'
            'U = 100 * r [%]  # utilisation'
        ),
        ...
    )
```

- **Value exact by construction**: each physical line is an ordinary
  single-quoted literal carrying its own `\n`; code indentation is code, never
  content. Per-fragment `repr()` gives exactly today's escaping guarantees.
- **Zero parse changes**: CPython's parser merges adjacent string literals at
  parse time — the whole group is a single `ast.Constant`, so
  `from_composite::_literal_value` already accepts it (verified:
  `ast.parse("x = ('a\\n' 'b')")` yields `Constant('a\nb')`;
  `ast.literal_eval` agrees).
- One string per entry line — exactly the mini-syntax's own granularity
  ("one entry per line"), so the source reads like the calc it encodes,
  with each row's `# reference` comment visible on its own line.
- Honest cost: it is "one literal per line", not a freeform text block;
  backslashes stay escaped (`\\nu` for LaTeX). That is the price of keeping
  literals literal and bytes exact, and it is the smallest price on the table.

### Option 3 — `textwrap.dedent("""…""")`

Readable and indentable — but the argument is no longer a literal: it is an
`ast.Call`. `from_composite::_literal_value` would have to *evaluate a
function call* to recover the value. Stated plainly: **this pierces ADR 0004
D5's "literal argument ⟷ widget value"**. The costs are concrete:

- Parsing becomes evaluation of a whitelisted call — a new, second literal
  language (`dedent`-of-`Constant` only), with `_signature`, minting,
  validation and the derive endpoint all needing to understand it.
- Fidelity gets *harder*, not easier: `dedent` strips the **common** leading
  whitespace, so a value line that legitimately begins with spaces (indented
  continuation in a calc) is ambiguous between content and formatting; a
  trailing-newline-exact inverse emitter is fiddly and easy to get subtly
  wrong.
- Everything downstream that assumes "a widget value is an `ast.Constant`"
  (the `Emit ⟷ parse is stdlib-`ast`` posture, A1's meaning-comparison)
  grows a special case.

**Verdict: rejected.** Readability must not cost literal-ness; Option 2 gets
the readability without the pierce. (It also stays *rejected as input*: a
hand-typed `dedent(...)` argument keeps raising the existing clear
`EngineError` from `_literal_value` — "neither a reference … nor a literal".)

### Option 4 — Module-level constant (`FORMULAS = """…"""` + `formulas=FORMULAS`)

Reads beautifully, collides head-on with the bijection. Verified against
`from_composite`:

- A bare `Name` argument is how the composite encodes a **wire** — but only
  when the name is a *node id* (`_socket_from_reference` checks
  `value.id in node_ids`). A module-level constant's name is not a node id, so
  it is not misread as an edge; it then falls through to `_literal_value`,
  which accepts only composite **parameters** with literal defaults — a
  module constant **raises `EngineError` today**.
- Supporting it would create a genuine D3/D5/D7 ambiguity: rename a node to
  `FORMULAS` and the same token flips meaning from "literal indirection" to
  "edge". It also moves the value *out* of the wiring statement, so A1's
  statement-level patch would have to edit two disjoint file regions (the
  constant and the call) for one widget edit, and node-statement spans
  (`node_statement_span`, ADR 0015) would no longer contain the node's values.

**Verdict: rejected** (both as emitted form and as newly-accepted input).

## Decisions

### D1 — Emitted form: parenthesized implicit concatenation, one fragment per value line

A multi-line string literal is emitted as a parenthesized group of ordinary
(implicitly concatenated) string literals:

- Fragments are `value.split('\n')`; every fragment except the last carries
  its `'\n'` back; a trailing **empty** last fragment (value ends with `\n`)
  is dropped — the preceding fragment's `'\n'` already encodes it.
- Each fragment is rendered with `repr()` — the exact escaping semantics the
  emitter has today, applied per line.
- The group is wrapped in `(` … `)` on their own lines; fragments sit one
  indent level deeper than the argument.

Verified properties (all four checked by experiment): concatenating the
`ast.literal_eval` of the fragments reproduces the value byte-exactly for the
capacity-check literal, for a trailing-newline value, and for `\r\n` content
(the `\r` stays visibly escaped in its fragment — see OQ4).

### D2 — The predicate: value-driven, exact

> A literal argument is emitted in block form **iff** it is a `str` and
> contains `'\n'`. Everything else — including a `str` of any length without
> a newline, and any non-`str` (dicts, lists, numbers) — keeps single-line
> `repr()`.

The predicate is a pure function of the value, so the representation cannot
oscillate on its own: re-emitting the same value always yields the same bytes,
and a value can only cross the boundary when the value itself changes — which
already re-emits that statement (and only it) under A1. No thrash is possible.

It is deliberately **not** keyed on the widget's `multiline=True` declaration
(see OQ1): the owner's requirement is "the bijection always handles this the
same way", and a value-driven rule means a newline in *any* string param —
`title` included — renders as real lines. Registry/widget metadata stays out
of the emit path, which `wiring_lines` can also be called without.

Scope note: the rule applies to **top-level string literal arguments** only. A
string nested inside a container literal (`options={"note": "a\nb"}`) keeps
container `repr()` — containers are a different (pre-existing) formatting
question and are out of scope here.

### D3 — When any argument goes block-form, the whole call goes expanded

A statement with at least one block-form literal is emitted as an expanded
call — one argument per line, trailing comma, closing `)` at statement indent
(the shape the hand-written `capacity_check.py` already uses). A statement
with no block-form literal keeps today's one-line form **unchanged** —
existing files without multi-line strings emit byte-identically, so every
current idempotence test over such fixtures still passes untouched.

The capacity-check card statement, exactly as `wiring_lines` would emit it
(note the emitter references single-output sources by bare name — the
hand-written `F_max.result` spelling remains an accepted equivalent input,
per D4):

```python
    card = calc_card(
        title='Capacity check',
        as_of='2026-07-24',
        formulas=(
            'r = F_max / C_min  # demand / capacity\n'
            'U = 100 * r [%]  # utilisation'
        ),
        checks=(
            'U < 100  # capacity not exceeded\n'
            'U < 50  # utilisation target'
        ),
        F_max=F_max,
        C_min=C_min,
    )
```

And the whole `@main` body of `examples/capacity_check/capacity_check.py` as
it would read after a formulas edit (only the card statement is re-emitted;
every comment and the other four statements survive byte-for-byte, per A1):

```python
@main
def capacity_check_report(
    forces_path: str = "forces.csv", members_path: str = "members.csv"
) -> str:
    """Read both CSVs, reduce each to its extreme, and render the calc card."""
    # Two independent CSV arcs. `read_csv` names a column and yields a list of
    # floats — interchangeable with `sources.mock_api`, which emits the same shape.
    forces = read_csv(path=forces_path, column="force")
    members = read_csv(path=members_path, column="capacity")

    # Reduce each arc to the value that governs the check: the highest applied
    # force and the lowest available capacity. Plain `calc` pack reductions —
    # nothing example-local.
    F_max = maximum(forces)
    C_min = minimum(members)

    card = calc_card(
        title='Capacity check',
        as_of='2026-07-24',
        formulas=(
            'r = F_max / C_min  # demand / capacity\n'
            'U = 100 * r [%]  # utilisation\n'
            'm = C_min - F_max  # margin over demand'
        ),
        checks=(
            'U < 100  # capacity not exceeded\n'
            'U < 50  # utilisation target'
        ),
        F_max=F_max,
        C_min=C_min,
    )
    # The card's `result` socket (the self-contained HTML document) is the graph
    # output; its sibling `height` socket tells the UI how tall to draw it.
    return card
```

(The hand-written leading comment block on the card statement is attached to
the statement being replaced; under A1 a *value* patch replaces only the
statement's own AST line span, so the comment survives — same behaviour as
today's one-line re-emit.)

### D4 — Parse: one meaning, several accepted spellings

`from_composite` continues to accept every spelling Python itself collapses
to one `ast.Constant` — **no code change needed**, verified against
`_literal_value` / `_socket_from_reference`:

| Input spelling | AST | Accepted? |
|---|---|---|
| `'a\nb'` (single-line, escaped — today's emit, existing files) | `Constant` | ✅ unchanged |
| `('a\n' 'b')` (block form, D1 — the new emit) | `Constant` (parser concatenates) | ✅ already, zero changes |
| `"""a\nb"""` (hand-written triple-quoted) | `Constant` | ✅ already — content taken literally, indentation included; the user owns those bytes |
| `textwrap.dedent("""…""")` | `Call` | ❌ stays rejected (D5: literals are literals) with the existing `EngineError` |
| `FORMULAS` (module constant) | `Name` not in `node_ids`/params | ❌ stays rejected with the existing `EngineError` |

Because A1 compares statements by parsed meaning, a hand-typed variant that
denotes the same string is a **no-op on save** — it is neither churned nor
normalized until the user actually changes that statement's meaning, at which
point the one re-emitted statement takes the canonical D1/D3 shape (expected —
"normalizing a line you just edited is not data loss").

### D5 — Escaping rules

Per-fragment `repr()`, i.e. Python's own rules, per line:

- Backslashes are escaped (`\\`) — a LaTeX-ish `\nu` in a calc line stays
  unambiguous and round-trips exactly.
- Quotes: `repr` picks `'` (switching to `"` when the fragment contains `'`
  and no `"`) — deterministic, same as today.
- A value containing `"""` is a non-event — no triple quotes are emitted, the
  sequence is just three escaped/plain quote characters inside a fragment.
- `\r`, `\t` and other non-printables remain visibly escaped inside their
  fragment (a fragment holding `a\r` + rejoined `\n` renders `'a\r\n'`).
- Trailing newline in the value ⇒ the last emitted fragment ends in `'\n'`;
  no trailing newline ⇒ it doesn't. Nothing is added or normalized away.

### D6 — Idempotence and stability, argued

1. **Emit is a pure function of the graph.** D1/D2/D3 consult only the value;
   the same graph always emits the same bytes ⇒
   `to_composite(from_composite(s)) == s` for any `s` the emitter produced.
2. **Parse is exact.** Every accepted spelling is an `ast.Constant`; Python
   string semantics reconstruct the bytes; no dedent/strip anywhere ⇒
   `from_composite(to_composite(g))` preserves every literal byte-exactly.
3. **Write-back cannot churn.** `compute_writeback` re-emits a statement only
   when `_signature` (parsed meaning) differs; representation is not part of
   the signature. A no-op save stays byte-identical; a one-literal edit
   rewrites exactly one statement; unrelated lines, comments and hand-written
   spellings are untouched. Existing single-line-escaped files therefore
   migrate **lazily, statement by statement, only when edited** (see OQ5).

### D7 — Where the change lands (and where it doesn't)

- `engine/composite.py` — `_render_value`/`_arg_exprs` grow the block/expanded
  emission; `to_composite` and `wiring_lines` emit per-statement *blocks*.
  Minimal-churn contract: `wiring_lines` keeps returning one `str` per
  statement, now allowed to contain embedded `\n` — `writeback.py`'s
  `_splice_lines` / `_assemble` already tolerate multi-line elements (they
  only guarantee a trailing newline), and `_wiring_statements` already spans
  multi-line statements via `end_lineno` (proven by the existing
  multi-line-dict fixture in `test_writeback_fidelity.py`).
- `server/writeback.py` — no planner logic changes expected; fidelity tests
  extended.
- `engine/emit.py` (`to_python`, the *derived* flat script — not the
  round-trip surface) — should reuse the same rendering helper for visual
  consistency; follow-up stream, outside the bijection contract.
- Frontend — none. The inspector edits the value, not its spelling
  (ADR 0018); only Playwright assertions that pinned the escaped-`\n` bytes
  change.

## Test impact

**Must change (they pin the old bytes on purpose):**

- `web/tests/formula-editing.spec.ts` — the two byte-level assertions:
  `formulas='…\\n…'` after the D7-1 commit, and
  `title='Capacity check\\nrevision B\\nrevision C'` (the latter only under
  OQ1's value-driven default). They flip to asserting the block form.
- `tests/test_composite.py` — *additions only*: idempotence + round-trip cases
  for multi-line literals and the escaping torture set (backslash, `"""`,
  trailing `\n`, `\r\n`, embedded quotes). Existing tests pass unchanged (no
  current fixture emits a multi-line string).
- `tests/test_handcalc_bijection.py` — `test_roundtrip_multiline_calc` already
  asserts value identity, not bytes: passes unchanged; add a byte assertion
  for the new emitted shape.

**Must NOT change (the safety net):**

- `tests/test_composite.py` round-trip identity + idempotence tests as they
  stand.
- `tests/test_writeback_fidelity.py` — every comment-preservation, no-op
  byte-identity, insertion/deletion and fallback-warning test. (The
  multi-line **dict** collapse test is about a container literal — out of
  scope per D2 — and keeps passing.)
- `tests/test_capacity_check_example.py` — it asserts the *graph value*
  (`card["inputs"]["formulas"] == "r = …\nU = …"`), which this ADR does not
  touch.
- `tests/test_node_statement.py`, `test_source_editing.py`, server suites.

## Build plan — small, independently mergeable streams

1. **Emitter core** (`engine/composite.py`): `_render_literal` helper
   (predicate D2, fragmenting D1), expanded-call emission D3; unit tests for
   fidelity, idempotence, escaping. No behaviour change for graphs without
   multi-line strings ⇒ mergeable alone.
2. **Write-back proof** (`server/writeback.py` + `tests/test_writeback_fidelity.py`):
   confirm multi-line statement blocks splice/patch/insert/delete correctly
   (expected: zero planner changes; the stream is mostly new fixture +
   assertions, incl. "editing a sibling param re-emits the whole statement in
   block form" and "no-op save on a block-form file is byte-identical").
3. **UI round-trip** (`web/tests/formula-editing.spec.ts`): update the two
   byte assertions; add one asserting the block shape lands on disk after a
   formulas commit.
4. **Example + docs**: one-time hand-reflow of
   `examples/capacity_check/capacity_check.py`'s `formulas`/`checks` to block
   form (subject to OQ5's confirm); cross-reference note in ADR 0004's
   honesty table ("canonical statement formatting" now includes the D1 block
   form).
5. **Derived export parity** (`engine/emit.py::to_python`): reuse the shared
   helper. Cosmetic, independent, last.

Streams 1→2→3 are ordered by dependency; 4 and 5 are independent of 3.

## Open questions — **all five confirmed as recommended** (bold = the decision)

1. **Which params get block form?** All string literals by value
   (**value-driven: any `str` containing `\n`**, D2) — or only params whose
   widget declares `multiline=True`? Value-driven is the consistent reading of
   "always handles this the same way", keeps registry metadata out of the
   emitter, and covers hand-typed newlines in any param; its visible
   consequence is that a multi-line `title` also becomes a block (changing the
   second web-test assertion).
2. **May readability cost strict literal-ness (Option 3, `textwrap.dedent`)?**
   **No** — keep ADR 0004 D5 intact; the D1 block form delivers indented,
   line-per-entry readability while the argument stays a plain `ast.Constant`,
   and `dedent(...)` input keeps raising the existing clear error.
3. **Normalize trailing newlines?** **No** — preserve the value's bytes
   exactly (a trailing `\n` emits as a visible `'…\n'` final fragment). The
   calc parsers ignore trailing blank lines anyway, so normalization would buy
   nothing and would break byte-fidelity and the `_signature` no-op guarantee.
4. **What about `\r\n` in a value?** **Preserve, don't normalize**: blocks
   split on `\n` only, so a `\r` stays visibly escaped inside its fragment and
   round-trips byte-exactly. (If the owner prefers, normalizing `\r\n → \n`
   would belong in the *editor commit path* (ADR 0018), never in the
   emitter/parser — the bijection should not silently rewrite values.)
5. **Migrate existing single-line files?** **Lazily** — the A1 statement-level
   rule already means a statement converts to block form the first time its
   meaning changes, and never otherwise (no repo-wide churn, no noisy diffs).
   One exception proposed: hand-reflow the shipped
   `examples/capacity_check/capacity_check.py` once (build-plan stream 4) so
   the flagship example shows the recommended shape.
