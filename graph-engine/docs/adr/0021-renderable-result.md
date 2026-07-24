# ADR 0021 — A renderable result type: one calculation, many renderings

Status: **proposed — MAJOR DECISIONS / OPEN QUESTIONS below are for sign-off** ·
Scope: `calcsheet` (the standalone library) + `nodepacks/sheet` + one small
engine/server seam; **no frontend renderer work is designed here** · Relates
to: ADR 0004 (graph⟷source bijection — literals are widget values, D5 emits
only wiring lines), ADR 0007 (derived input sockets — `calc_card`'s symbol
sockets must survive the split), ADR 0010 (node-declared renderers,
`Renderer(kind, **config)`), ADR 0013 (renderer kinds `latex` / `html-card`),
ADR 0019 (output rendering should be type-driven and separable — this ADR
stays on the **producer** side of that line and composes with it).

Numbering note: as of 2026-07-24, 0021 is the next free number across
`docs/adr-*` branches (0012 remains a pre-existing gap).

## The ask

> "Right now calc_card just renders HTML and that's great. How can we take
> this a step up and make sure there's also an intermediate or output type
> that we can use? We should be able to use that output type and define
> multiple different ways to render it. Options: attach `render_html` /
> `render_pdf` to an object type, or have a separate function that operates on
> the existing type. Evaluate the pros and cons and come up with a proposal
> following best practices."
>
> Design input: seamlessly support and modify different ways of rendering the
> same data in the future; rendering options (page numbering, headers, …) may
> be needed later.

## Context — what already exists (and what is actually missing)

The intermediate type the ask describes **already exists inside calcsheet**;
it just never escapes.

- **`Result` is the intermediate.** `evaluate_calc(calc: Calc) -> Result`
  (`calcsheet/src/calcsheet/evaluate.py:138`) produces a frozen dataclass
  (`evaluate.py:61-72`) carrying `title, as_of, precision, inputs, formulas,
  checks, values, passed`. Its docstring is already the design goal:
  *"Everything a renderer needs — and nothing it has to recompute."*
- **The one renderer is already a free function over that type.**
  `render_html(result: Result) -> str` (`calcsheet/src/calcsheet/render.py:159`)
  takes the `Result`; it is not a method. The only method in the package,
  `Calc.evaluate()` (`model.py:77-81`), is a thin convenience that lazy-imports
  `evaluate_calc` to avoid a module cycle — a precedent for "type stays inert,
  behaviour lives in functions".

So "methods vs free functions" is half-answered by our own code. The real
gaps are:

1. **The graph node collapses both steps.** `sheet.calc_card`
   (`nodepacks/sheet/__init__.py:306-366`) parses the mini-syntax, builds the
   `Calc`, calls `evaluate_calc` (line 360) and immediately `return
   render_html(result)` (line 366). The `Result` never appears on a socket, so
   a canvas user cannot swap or add a rendering — the choice of "HTML" is
   welded into the node that owns the numbers.
2. **There is exactly one renderer and zero option plumbing.** `render_html`
   takes no options; there is nowhere to say "page numbers", "header text" or
   "theme".
3. **A second backend drags a dependency in.** `calcsheet` is deliberately
   two pure-Python deps (`sympy`, `latex2mathml` — `calcsheet/pyproject.toml`),
   and the engine is stdlib-only. Any PDF backend is a heavyweight dependency
   that must not land on users who only want HTML, and must not break the
   pack's lazy-import contract (`nodepacks/sheet/__init__.py:14-19`: importing
   the pack and listing its spec works with **none** of calcsheet's deps
   installed).

## D1 — Renderers are free functions over `Result`, catalogued by a registry (not methods)

Three shapes were weighed:

**(a) Methods on the type** — `result.render_html()`, `result.render_pdf()`.

- Pro: maximum discoverability; one autocomplete surface.
- Con: **inverts the dependency direction.** The core type would import every
  backend (or fake independence with per-method lazy imports, which hides the
  real dependency graph and makes "is PDF available?" answerable only by
  calling and catching). Every new backend edits `Result` — the opposite of
  "adding `render_docx` is additive and requires no change to `Result`".
- Con: third parties cannot add a rendering without monkey-patching the class.
- Con: unit-testing a backend drags the whole type's method surface along.

**(b) Free functions over the type** — `render_html(result)`,
`render_pdf(result)` in separate modules.

- Pro: matches the existing code (`render.py:159`) and the package's own creed
  ("it is a library" — `__init__.py` docstring). Dependency direction is
  clean: backends import the model; the model imports nothing.
- Pro: a backend is a module you can ship, extra-gate, test and delete
  independently. Third parties write their own function against the public
  `Result` and are first-class.
- Con: discoverability is by documentation, not autocomplete on the object.

**(c) A registry** — `renderers()` returns declared backends; `get_renderer
("pdf")` resolves one.

- Pro: this is what the *tooling* needs — the `sheet` pack and any CLI must
  enumerate what exists (and what is installed) without importing backends.
- Con: as the only entry point it is stringly-typed indirection; nobody should
  be forced through `get_renderer("html")(result)` to render HTML.

**Decision: (b) as the author-facing contract, (c) as a thin catalogue on
top; (a) rejected.** Authors call `render_html` / `render_pdf` directly with
real signatures and real types. The registry exists for enumeration and
lazy resolution (D5), not as the primary API. The existing free-function
precedent is thereby argued, not just inherited: it wins because dependency
direction and additive extension are the two properties the ask names, and
methods sacrifice both for autocomplete.

## D2 — The intermediate becomes a real socket value (the load-bearing question)

Can `calc_card` split into `calc(...) -> Result` and `render_html(result) ->
str` with `Result` crossing a socket? **Yes — splitting is viable today**, and
the evidence is specific:

- **In-process, sockets carry arbitrary Python objects.** The executor stores
  each node's raw outputs and hands them to consumers by reference —
  `provided[param] = outputs[source.id][socket]`
  (`engine/execute.py:115`); nothing between two nodes serialises anything.
  A frozen dataclass flows through a wire exactly like the floats and lists
  already do. (Its `type` in the spec is just the annotation name, `"Result"`
  — the engine does no socket type-checking.)
- **Graph JSON is unaffected.** Only *literals* are serialised into the graph
  (`engine/graph.py:37-44` — `inputs` holds literal widget values; edges are
  string endpoints). A `Result` is always **wired, never a literal**, so the
  bijection (ADR 0004) and the graph schema need zero changes. The emitted
  source is just `card = render_html(result=calc_node.result, ...)` — an
  ordinary wiring line under D5.
- **What actually degrades is the HTTP preview, and it degrades safely.** The
  run endpoint JSON-ifies every socket via `to_jsonable`
  (`server/app.py:197-207`), which turns any non-JSON object into a
  `{"$repr": ..., "$type": "Result"}` placeholder (`server/serialize.py:26-42`).
  The frontend is contractually tolerant of that shape
  (`web/src/node-renderers/registry.ts:30-33`), and the `html-card` kind
  falls back to result chips for any non-string
  (`web/src/node-renderers/html-card/index.tsx:70-77`). So after a split: the
  render node's `result` socket is still a plain HTML string and renders in
  the sandboxed iframe exactly as today; the calc node's `Result` socket shows
  as a truncated-repr chip in the inspector/results panel.

**The cost, plainly:** a repr chip is an honest but ugly preview of the most
interesting value in the graph. Two additive fixes, neither blocking:

1. **`Result` gains a canonical dict form** — `Result.to_dict() -> dict` /
   `Result.from_dict(...)`, versioned (`{"calcsheet_result": 1, ...}`),
   pure-JSON. Worth having regardless: it is the archival form of a completed
   calculation and the door to cross-process execution (ADR 0003) later.
2. **`to_jsonable` gains a duck-typed hook**: before falling back to
   `_preview`, probe for a `to_jsonable()` method on the value and recurse on
   what it returns. The engine/server stay ignorant of calcsheet (no import —
   a protocol, not a dependency); any pack type can opt into a real JSON
   preview. This is the same "cheap version of ADR 0001's JSON values +
   opaque handles" the serializer already claims to be.

**Decision:** the socket carries the **live `Result` object** in-process (an
opaque-but-typed value, per ADR 0001's model); the dict form is for
serialisation seams (HTTP previews via the hook, archives, future
out-of-process runs) — not what consumers unpack by hand. We do **not** put
the raw dict on the socket: renderer signatures should say `Result`, not
`dict`, and the object form keeps `from_dict` churn out of every consumer.

## D3 — Render options: per-renderer dataclasses, flattened to node params at the graph boundary

Options must serve two audiences: library authors (typed, discoverable) and
canvas users (editable as graph literals — ADR 0004: *literal argument ⟷
widget value*, so anything the UI edits must be a JSON-able literal).

- **Library level: one frozen options dataclass per renderer, owned by that
  renderer's module.** `HtmlOptions(theme=..., header=..., footer=...)` next
  to `render_html`; `PdfOptions(page_size=..., margins_mm=..., page_numbers=...,
  header=..., footer=...)` next to `render_pdf`. Overlapping concepts reuse
  the same *field names* by convention (`header`, `footer`, `theme`), but
  there is deliberately **no shared superset type**: page numbering is
  meaningless for a scrolling HTML card, and a union type would make every
  renderer validate (or silently ignore) the other's knobs — the classic
  "options soup". Every options dataclass must be JSON-round-trippable
  (all-scalar fields), for the same reason `Widget`/`Renderer` config already
  runs a `json.dumps` guard at import time (`engine/spec.py:113,156`).
- **Graph level: options are ordinary node parameters on the *render* node**
  — flat scalars (`header: str = ""`, `page_numbers: bool = True`), so each
  gets a type-derived widget for free (`engine/spec.py:_WIDGET_BY_TYPE`), is a
  plain literal in the graph JSON, and round-trips the bijection without any
  new machinery. The node body assembles the options dataclass from its
  scalar params. A single `options: dict` param was rejected: it has no
  widget, no validation surface, and it hides the knobs the canvas exists to
  show.
- **Options are presentation and must never leak into the dataflow contract
  upstream** (ADR 0019's hard constraint): they live on the render node only.
  The calc node knows nothing about pages or headers.

## D4 — The renderer contract

A backend is a module that provides exactly three things:

1. a **render function** — `render_<name>(result: Result, options:
   <Name>Options | None = None) -> str | bytes` — pure, deterministic
   (byte-identical output for the same `Result` + options; the `as_of`
   never-read-the-clock rule extends to renderers), consuming only public
   `Result` fields, recomputing nothing;
2. an **options dataclass** (frozen, all-scalar, JSON-round-trippable), or
   `None` if the renderer has no knobs;
3. a **registry entry** describing itself without importing itself:

```python
@dataclass(frozen=True)
class RendererInfo:
    name: str                      # "html", "pdf" — the registry key
    media_type: str                # "text/html", "application/pdf"
    output: type                   # str (a document) or bytes (a binary)
    options_type: type | None      # HtmlOptions / PdfOptions / None
    requires: str | None           # extra that provides it, e.g. "pdf"; None = core
    load: Callable[[], Callable]   # imports the backend on first use (D5)

def renderers() -> tuple[RendererInfo, ...]: ...   # never imports backends
def get_renderer(name: str) -> Callable: ...        # lazy; CalcError if missing (D5)
```

`media_type` + `output` are how a renderer **declares what it produces so a
UI can present it**. This is the seam that composes with ADR 0019 without
duplicating it: on the canvas, each render node still *declares* its surface
via `@node(renderer=Renderer(kind, ...))` (ADR 0010 — declaration is the top
of 0019's resolution order and always wins), so nothing in this ADR needs
0019's inference to exist. When 0019's value→presentation inference is
designed, `media_type` is exactly the honest signal it wants ("this is
`application/pdf`, offer a download; this is `text/html`, sandboxed frame") —
we produce the signal here and leave consuming it to 0019. Until a `pdf`
renderer kind exists in the web registry, a PDF node's output degrades to
chips, which is the designed fallback (`registry.ts` — null-means-chips), not
a failure.

Adding `render_markdown` or `render_docx` later is: one new module, one
`RendererInfo`, optionally one extra in `pyproject.toml`. **Zero edits to
`Result`, `evaluate_calc`, or any existing renderer** — that is the additive
guarantee the ask requires, and the registry's tests should assert it (a
`renderers()` snapshot plus "importing calcsheet imports no backend deps").

## D5 — Dependency isolation and failure timing

Mirrors the contract the `sheet` pack already lives by
(`nodepacks/sheet/__init__.py:14-19` — spec listing works with nothing
installed; only *running* needs the deps):

- **Shipping:** the HTML renderer stays in core (`render.py` is
  stdlib-only). A PDF backend ships as an **optional extra of the same
  package** — `calcsheet[pdf]`, module `calcsheet.pdf` — not a separate
  distribution and not an entry-point plugin. Rationale: one version to keep
  in lockstep with the `Result` shape it consumes; entry-point plugins buy
  third-party discovery we don't need yet (third parties can already call the
  free functions and register a `RendererInfo` at runtime; promoting that to
  entry points is an additive later step, deliberately out of scope).
- **Failure timing:** three moments matter, and each has one behaviour.
  - **Import time:** `import calcsheet` and `import calcsheet.pdf`'s *info*
    never import the backend deps. Listing `renderers()` always succeeds and
    can report availability via `importlib.util.find_spec` probes — again
    without importing.
  - **Spec-listing time:** the `sheet` pack keeps its lazy-import contract —
    `sheet.render_pdf`'s node body imports `calcsheet.pdf` inside the
    function, so the node appears in the catalog with none of the deps
    installed (identical to how `calc_card` lazy-imports `calcsheet` today,
    line 334).
  - **Call time:** a missing backend raises `CalcError` with the actionable
    fix in the message (`"PDF rendering needs the 'pdf' extra: uv sync
    --extra pdf"` / `pip install 'calcsheet[pdf]'`), which the node surfaces
    as `UserError` exactly as `calc_card` already translates `CalcError`
    (lines 361-364). Failing at call, not import, is the only choice
    compatible with "listing works uninstalled"; the availability probe keeps
    it from being a surprise.

## The consequential finding — `Result` is presentation-shaped, and what to do about it

Honest assessment, as asked. `Result`'s rows are not neutral facts: `Row`
carries `symbol_mathml` and `definition_mathml` (`evaluate.py:41,43`),
`CheckResult` carries `expr_mathml` (`evaluate.py:55`), and `value_text` is
precision-formatted display text. MathML is an HTML-oriented markup; a PDF
backend built on anything but an HTML-to-PDF engine cannot consume it, and
Markdown/DOCX certainly cannot. On its face, that argues for moving MathML
minting into the HTML renderer and keeping `Result` neutral.

**We recommend against moving it, for a reason visible in the code:** the
MathML is minted from the live sympy expression objects
(`expression_mathml(expr)` — `evaluate.py:183,208`), which exist only during
evaluation and are deliberately not retained on `Result`. Moving minting into
`render_html` would force the renderer to **re-parse the expression text with
sympy** — re-deriving what evaluation already knew, breaking the package's
core invariant ("everything a renderer needs — and nothing it has to
recompute") and dragging `sympy` into the render layer, the exact dependency
direction D1 exists to prevent.

The saving fact: **every markup field already has a plain-text sibling** —
`Row.symbol`/`symbol_mathml`, `Row.definition`/`definition_mathml`,
`CheckResult.expr`/`expr_mathml`, plus `value`, `value_text`, `unit`, `ref`,
`substituted`, `passed`. A non-MathML backend already has the complete neutral
record; MathML is redundant enrichment, not the sole carrier. So the honest
reframing is: **`Result` is a neutral record plus pre-minted markup channels,
and adding a channel is additive.** Concretely, when the first non-HTML
backend lands, add `symbol_latex` / `definition_latex` / `expr_latex` sibling
fields — the LaTeX is *already computed* on the way to MathML and thrown away
(`mathml.py:119-125`: `expr → sympy.latex(expr) → latex2mathml`), so
capturing it costs one string per row and gives a LaTeX-pipeline PDF backend
first-class typeset math with, again, zero recomputation. `value_text` stays:
significant-digit policy is a property of the calculation (`precision` is
authored on the `Calc`), and renderers agreeing on formatted values is a
feature, not a leak.

## Proposed public API — the same calc, two ways

What an author writes (library level):

```python
from calcsheet import Calc, Check, Formula, Input, evaluate_calc
from calcsheet.render import HtmlOptions, render_html
from calcsheet.pdf import PdfOptions, render_pdf        # needs calcsheet[pdf]

calc = Calc(
    title="Capacity check",
    as_of="2026-07-24",
    inputs={"F_max": Input(120.0, ref="forces.csv · max"),
            "C_min": Input(210.0, ref="members.csv · min")},
    formulas=[Formula("r", "F_max / C_min", ref="demand / capacity"),
              Formula("U", "100 * r", unit="%", ref="utilisation")],
    checks=[Check("U < 100", "capacity not exceeded"),
            Check("U < 50", "utilisation target")],
)

result = evaluate_calc(calc)                             # ONE evaluation…

html = render_html(result, HtmlOptions(theme="auto", header="Acme Corp"))
pdf = render_pdf(result, PdfOptions(page_numbers=True,   # …many renderings
                                    header="Acme Corp — Capacity",
                                    page_size="A4"))

archive = result.to_dict()                               # versioned JSON form
```

Back-compat: `render_html(result)` with no options renders exactly today's
card (all options default); `Calc.evaluate()` and every existing export keep
working.

Node level (`nodepacks/sheet`):

```python
@node(widgets={...}, dynamic=DerivedInputs(param="formulas", derive=formula_free_symbols))
def calc(title: str = "Calculation", as_of: str = "", formulas: str = "",
         checks: str = "", precision: int | None = None, **values: float) -> "Result":
    """Evaluate the calc; emit the Result (no rendering here)."""

@node(renderer=Renderer("html-card", socket="result", height=DEFAULT_CARD_HEIGHT))
def render_html(result: "Result", header: str = "", footer: str = "",
                theme: str = "auto") -> str:
    """Result -> self-contained HTML card (options are this node's literals)."""

@node()  # no renderer kind yet: output degrades to chips until ADR 0019 grows one
def render_pdf(result: "Result", header: str = "", footer: str = "",
               page_numbers: bool = True, page_size: str = "A4") -> bytes:
    """Result -> PDF bytes (needs the pdf extra; fails at call time, not listing)."""
```

## The capacity_check graph, before and after

Before (today, `examples/capacity_check/capacity_check.py:100-107` — five
nodes; evaluate+render welded into `card`):

```
forces.csv  ─> forces (read_csv) ──> F_max (calc.maximum) ──┐
                                                            ├─> card (sheet.calc_card) ─> html
members.csv ─> members (read_csv) ─> C_min (calc.minimum) ──┘
```

After (split form — six nodes; the `Result` is now on a wire, and a second
rendering is one more node on the same wire, not a second evaluation):

```
forces.csv  ─> forces ──> F_max ──┐
                                  ├─> sheet (sheet.calc) ──┬─> card (sheet.render_html) ─> html
members.csv ─> members ─> C_min ──┘        Result          └─> paper (sheet.render_pdf)  ─> pdf
```

As straight-line composite source (ADR 0004 D7 — each call its own
assignment, so it round-trips the bijection):

```python
sheet = calc(title="Capacity check", as_of="2026-07-24",
             formulas=..., checks=..., F_max=F_max, C_min=C_min)
card = render_html(result=sheet, header="Acme Corp")
paper = render_pdf(result=sheet, page_numbers=True)
```

A single-output node is referenced by its bare variable, not `x.result`: that
is what the emitter writes, so anything else would leave the file needing a
migration the moment it is saved. (Corrected during the Stream B build; the
first draft of this snippet used the explicit `.result` form.)

## Migration path (does not break the shipped example)

1. `sheet.calc_card` **stays**, unchanged in id, sockets, widgets, derived
   inputs and renderer declaration — the shipped `capacity_check` example and
   every existing graph keep working verbatim. Internally its body is already
   the composition (`evaluate_calc` then `render_html`); it simply remains the
   one-node convenience form.
2. `sheet.calc` and `sheet.render_html` land as **new, additive node types**.
   `calc` reuses `parse_formulas`/`parse_checks`/`formula_free_symbols`
   as-is — the ADR 0007 derived-socket seam moves with the deriving param.
3. The example gains the split as a variant (or a follow-up flips it once the
   Result preview hook is in); nothing forces a flip. Deprecating `calc_card`
   is explicitly **not** proposed (Open Question 1).
4. Housekeeping bundled with stream B: the stale comment in
   `capacity_check.py:108-109` still narrates the removed `height` socket
   (ADR 0019 "what prompted this") — fix in passing.

## Build plan — small, independently mergeable streams

- **Stream A — calcsheet: options + dict form + registry (valuable alone).**
  `HtmlOptions` (`theme`, `header`, `footer`) honoured by `render_html
  (result, options=None)`; `Result.to_dict()/from_dict` (versioned);
  `RendererInfo` + `renderers()` + `get_renderer` with the D5 failure
  contract. Pure library, no engine change; library users get options and an
  archival form immediately. Tests: default-options renders byte-identical to
  today; dict round-trip; registry imports nothing.
- **Stream B — the graph split.** `sheet.calc` + `sheet.render_html` nodes;
  the `to_jsonable` protocol hook in `server/serialize.py` so the `Result`
  socket previews as real JSON, not a repr; example variant + comment fix.
  Depends on A only for options params.
- **Stream C — second backend (gated on Open Question 4).** `calcsheet.pdf`
  behind the `pdf` extra; `PdfOptions`; LaTeX sibling fields captured on
  `Row`/`CheckResult` (additive); `sheet.render_pdf` node with call-time
  failure. No frontend work — output shows as chips by design.
- **Stream D — presentation of non-HTML outputs.** A `pdf`/download renderer
  kind, or value-inference from `media_type` — this is ADR 0019's design
  space; this ADR only guarantees the producer-side signal exists.

## Open questions (each with a recommended default — confirm or redirect)

1. **Does `calc_card` stay as a convenience single-node form alongside the
   split pair?** Default: **yes, keep it indefinitely** — it is the shipped
   example's spine and the one-node UX is genuinely good; the split pair is
   for graphs that want two renderings or on-canvas render swapping.
2. **Is JSON-serialisability of `Result` a hard requirement (versioned
   `to_dict`/`from_dict`), or best-effort preview only?** Default: **hard
   requirement** — it is cheap now, and it is the door to archives, honest UI
   previews, and ADR 0003 cross-process execution later.
3. **Does MathML stay on `Result`?** Default: **yes** — every markup field has
   a plain-text sibling, and moving minting into the renderer would force
   re-parsing with sympy (recompute-nothing violation); additively capture the
   currently-discarded LaTeX when the first non-HTML backend lands.
4. **Is PDF actually in scope soon, or a design constraint only?** Default:
   **constraint only for now** — Streams A+B ship without it; picking the PDF
   engine (HTML-to-PDF vs LaTeX pipeline) is a real decision best made when a
   concrete need fixes the requirements.
5. **Render options: per-renderer types or one shared superset?** Default:
   **per-renderer dataclasses** with shared field *names* by convention
   (`header`, `footer`, `theme`) — page numbering is meaningless for a
   scrolling HTML card, and a superset forces every backend to police the
   others' knobs.
