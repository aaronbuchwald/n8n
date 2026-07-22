# ADR 0004 — Graph ⟷ source bijection model

Status: **proposed** (settle before B4 / source-editing) · Scope: `graph-engine/` · Relates to: ADR 0001

## Context

The product goal: the **UI graph** and the **Python source** should map as close to
**bijectively** as possible — edit either surface and the other stays in sync.
This ADR defines *what maps to what*, what is deliberately excluded, and the
decisions (id scheme, source of truth, layout) that make the round-trip an
identity rather than an approximation. It also fixes the scope: which Python is
representable at all.

## The three surfaces

There are **three** things, not two, and conflating them is where "bijection"
gets fuzzy:

```
  GRAPH (canvas)            WIRING (composite)              NODE BODIES (files)
  nodes + edges +   ⟷      @main def report(path):    ─┐   @node def total(vals):
  widget values +          v = read_values(path)       │      return sum(vals)
  layout                   t = total(v)                 │   @node def average(...):
                           return render(t, a)          │      ...
                                                        └── referenced by module.qualname
```

- **Graph ⟷ Wiring composite** is the bijection this ADR is about.
- **Node bodies** are a *shared, referenced* resource (by `module.qualname`),
  edited on the code surface and shown as a node's internals in the UI. They are
  **never serialized into the graph** (ADR 0001, decision 6, upheld). Editing a
  body changes the node's behavior, not the graph's wiring.

## Decisions

**D1 — Canonical Python surface = the authoring module.** A `.py` file
containing the `@node` bodies **and** a `@main` composite whose body is a
**straight-line sequence of single-assignment calls** (`v = fn(args)`). This is
"the source code" the graph is bijective with. The flat `to_python()` script
stays a **derived export/compile target**, not the round-trip surface.

**D2 — The module is the single source of truth.** The graph JSON is a
*deterministic projection* of the module (parse), plus a **layout sidecar** for
positions. Canvas edits are applied by **rewriting the module's wiring lines**;
code edits **reparse** to the graph. One authoritative store → no drift. This
keeps "the graph *is* ordinary Python" literally true and gives Phase-6 VCS for
free (you version `.py` files). *(Alternative — graph JSON canonical, module
generated — rejected: it demotes the Python to an artifact and weakens the whole
premise.)*

**D3 — Node id = the composite's local variable name.** `v = read_values(path)`
→ node id `v`. This is maximally bijective (the code's variable *is* the id),
human-meaningful, and **stable under insertion** (adding a node above doesn't
renumber the others). This **un-defers** ADR 0001's "stable node ids" item and
resolves it. Duplicate targets are a name collision the user resolves, exactly
like Python.

**D4 — `code → graph` is an AST parse, not a trace.** Reading the composite's
AST gives the mapping directly: **assignment ⟷ node**, **variable name ⟷ id**,
**argument reference ⟷ edge**, **literal argument ⟷ widget value**. Tracing
(`@main.to_graph()`) stays for *programmatic* one-shot graph construction, but
the **bijective round-trip path** is parse ↔ emit over the composite text (only
AST-parse yields the variable-name ids of D3).

**D5 — `graph → code` emits/patches only the wiring lines.** Canonical
formatting applies to the composite's assignment lines only; **node bodies are
never regenerated**, so their comments, formatting, and imports are preserved.
Normalization damage is confined to the small wiring section.

**D6 — Layout is a view, excluded from the bijection.** `position` lives in the
sidecar (or the graph JSON `position` field), authored on save, `null` →
auto-layout. It is **not** encoded in the Python. This is the one dimension we
consciously drop from the bijection (encoding positions as source comments was
considered and rejected — it pollutes the code surface).

**D7 — Scope = the dataflow subset only.** The composite body must be
straight-line dataflow (values on wires, each node once). Control flow
(`if`/`for`/mutation) lives **inside node bodies**, never as graph structure;
arbitrary Python is intentionally not graph-representable (a traced/parsed value
can't be branched on). This is a feature — it's what keeps the mapping clean.

## What is / isn't bijective (stated honestly)

| Bijective (identity round-trip) | Deliberately excluded / lossy |
|---|---|
| nodes ⟷ composite assignments | **layout** (a view; sidecar only) |
| node id ⟷ variable name | **formatting/comments of wiring lines** (normalized on emit; bodies preserved) |
| edges ⟷ argument references | **non-dataflow Python** (control flow — unsupported in the composite by design) |
| widget values ⟷ literal arguments | |

So precisely: **the graph is bijective with the dataflow-wiring composite,
modulo layout and wiring-line formatting.**

## Consequences (new work this unlocks/requires)

- **Graph → composite emitter** (new; today we only emit the flat script).
- **Composite → graph AST parser** (new; complements tracing).
- **Variable-name ids** (adopt in the authoring/id scheme).
- **Persistence = module + layout sidecar** — the model B4 "save" writes to:
  canvas edits rewrite the module's wiring lines and the sidecar; code edits
  reparse. Canvas and editor are two views over one module.
- **Phase 6 VCS** = version `.py` + sidecar; graph-aware diff runs over the
  parsed model, not raw JSON text.
- **Stream E (source editing)** centers on exactly this: edit the composite text
  ⟷ graph; edit a `@node` body ⟷ that node's internals.

## Open confirmations (need a human decision to move to "accepted")

1. **Source of truth = the `.py` module** (D2), with graph JSON as a projection —
   vs. graph JSON canonical + generated code. *(Recommend: module.)*
2. **Node id = variable name** (D3) — vs. content-hash / explicit `id=`.
   *(Recommend: variable name.)*
3. **`code → graph` via AST parse** (D4) as the round-trip path — vs. tracing.
   *(Recommend: AST parse for round-trip; keep tracing for programmatic build.)*
4. **Layout in a sidecar** (D6) vs. positions embedded in the graph JSON only.
   *(Either works; sidecar keeps the graph JSON = pure projection.)*
