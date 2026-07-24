# calcsheet

Completed calculations as artifacts.

A calculation is declared as **data** — inputs, formulas, references, checks —
evaluated **once**, and rendered as a self-contained HTML card in the "C4
four-slot" layout with a binary pass/fail verdict.

The rendered string never drives a decision. Rows, values and verdicts are all
pure functions of one `Result`, so the card can never disagree with the numbers
it was built from. Same calc in ⇒ byte-identical HTML out.

```mermaid
flowchart LR
  A[Calc<br/>inert data] -->|evaluate| B[Result<br/>rows + verdicts]
  B -->|render_html| C[HTML card<br/>self-contained]
```

## What "self-contained" means here

- Math is native **MathML** (via sympy → LaTeX → `latex2mathml`), which browsers
  typeset with **zero JavaScript**. No KaTeX, no node, no CDN.
- Inline CSS only. No external stylesheets, fonts, images or scripts.
- Enforced, not just claimed: markup embedded in the card is checked for
  `<script`, `onerror`, `onload`, `href=`, `src=` and `http` before it is
  emitted, and every caller-supplied string (title, refs, units, descriptions)
  is HTML-escaped.

Two runtime dependencies, both pure Python: `sympy` and `latex2mathml`.

## API

```python
Input(value, ref="", unit="")            # a given quantity
Formula(symbol, expr, ref="", unit="")   # expr: string over prior symbols
Check(expr, description="")              # boolean expression over the scope
Calc(title, as_of, inputs, formulas, checks, precision=3)

calc.evaluate() -> Result
render_html(result, options=None) -> str

HtmlOptions(theme="auto", header="", footer="")   # per-renderer, frozen, JSON-able

result.to_dict() -> dict          # versioned, json.dumps-able archival form
Result.from_dict(payload)         # lossless: from_dict(to_dict(r)) == r

renderers() -> tuple[RendererInfo, ...]           # catalogue; imports no backend
renderer_info(name) / get_renderer(name)          # lazy resolution by name
register_renderer(info)                           # third-party backends
```

```python
from calcsheet import Calc, Check, Formula, Input, render_html

calc = Calc(
    title="Capacity check",
    as_of="2026-07-24",
    inputs={
        "F_max": Input(120, ref="forces.csv · max"),
        "C_min": Input(210, ref="members.csv · min"),
    },
    formulas=[
        Formula("r", "F_max / C_min", ref="demand / capacity"),
        Formula("U", "100 * r", ref="utilisation", unit="%"),
    ],
    checks=[
        Check("U < 100", "capacity not exceeded"),
        Check("U < 50", "utilisation target"),
    ],
)

result = calc.evaluate()   # r = 0.571, U = 57.1 %, result.passed is False
html = render_html(result)
```

### Semantics

- **Order matters.** Formulas run in declaration order over ONE scope seeded by
  the inputs; each result joins the scope for the formulas after it. A formula
  may only reference symbols declared before it.
- **Checks see the final scope** and produce real Python booleans.
- **Binary severity.** Any false check ⇒ overall `passed is False`. There is no
  warn level.
- **`as_of` is caller-provided**, never `datetime.now()`.
- **Errors are early and named.** Unknown symbol, duplicate symbol, unparseable
  expression and a non-boolean check all raise `CalcError` naming the offending
  symbol or expression and listing the available names.
- **Formatting** is `f"{value:.{precision}g}"`, `precision=3` by default ⇒ `120`,
  `0.571`, `57.1`. `unit` is a plain display string; this package does no unit
  algebra.
- Underscored symbols render as subscripts: `F_max` ⇒ F with subscript "max".

### The card

| slot | content |
| --- | --- |
| symbol | MathML |
| definition | MathML (formulas only — inputs get a single `=`) |
| value + unit | right-aligned, tabular numerals, unit upright and muted |
| reference | right-hand gutter, plain text, hairline rule |

Two optional slots sit around it: `HtmlOptions.header` is a banner above the
card, `HtmlOptions.footer` is the notes line under the verdict (source pins, a
code edition, scope caveats). Both are empty by default, and an options-free
render is byte-for-byte the card this package has always emitted — the CSS for
a slot is only emitted when the slot is filled.

The substituted middle step is deliberately dropped — that is the C4 model, and
it is why `handcalcs` is not used here. Design checks render as one row each:
check expression as math, its description, the substituted boolean
(`57.1 < 50 = False`) and a PASS/FAIL badge. Light and dark themes ship via
`prefers-color-scheme`.

### One result, many renderings

`evaluate_calc` runs once; a rendering is a free function over the `Result` it
returns. That is the whole extension contract — a new backend is one module
with a `render_<name>(result, options=None)` function, its own frozen options
dataclass, and (optionally) a `RendererInfo`. Nothing about `Result` changes.

```python
result = calc.evaluate()                                  # ONE evaluation…
html = render_html(result, HtmlOptions(header="Acme Corp"))  # …many renderings
archive = result.to_dict()                                # versioned JSON form
```

`renderers()` is a **catalogue, not the API**: it exists so tooling can list
what is available and what each backend produces (`media_type`, `output`)
without importing any of them. Authors keep calling the free functions. A
backend that is listed but not installed fails at `get_renderer(name)` — the
call — with the install command in the message, never at import or enumeration
time.

Options types are per-renderer by design: page numbering is meaningless for a
scrolling HTML card, so there is no shared superset that every backend would
have to police. Overlapping concepts reuse the same field *names* (`theme`,
`header`, `footer`) by convention, and every field is a scalar so the whole
options object round-trips JSON.

## Setup, tests, example

From a clean checkout, in this directory (`calcsheet/`). `uv` creates and syncs
the environment on the first run — no separate install step:

```bash
# tests (61 of them)
uv run --extra dev python -m pytest -q

# the example: writes out/capacity-check.html and opens it in a browser
uv run python -m calcsheet.examples.capacity
uv run python -m calcsheet.examples.capacity --no-open   # write only
```

Explicit environment, if you prefer one:

```bash
uv venv && uv pip install -e '.[dev]'
uv run python -m pytest -q
```

Without `uv`:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
python -m pytest -q
python -m calcsheet.examples.capacity --no-open
```

The example prints the output path and the overall status (FAIL — 57.1 %
clears the 100 % safety limit but misses the 50 % target).

## Scope

This package is a standalone library with no side effects at import: no clock,
no filesystem, no network. It has **no coupling to the graph engine** and works
if that directory does not exist. Later it can be used from a graph merely by
decorating a function that calls `render_html`.

Out of scope for now: snapshot testing, a CI gate, and real unit algebra
(`unit` is a plain string).
