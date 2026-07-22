# ADR 0006 — Collapsible composite nodes (nodepack-internals hiding)

Status: **proposed — DEFERRED** (parked 2026-07; pick up after the node-inspector
"Edit source" rework lands) · Scope: `graph-engine/` · Relates to: ADR 0001
(engine core), ADR 0004 (graph ⟷ source bijection), ADR 0005 (node-declared UI)

> **This ADR is a placeholder that records the question, not the decision.** It
> exists so the design conversation below isn't lost. Do not implement from it
> until it's promoted to `proposed` (open confirmations resolved) and scheduled.

## The question

When an example or client program **invokes a nodepack's functionality**, the
canvas currently shows *every internal node* of that functionality (the showcase
renders ~12 nodes because its render pipelines are authored as separate node
calls). A consumer shouldn't need to see a pack's internals — they should be
**hidden or collapsed by default, and expandable** on demand.

Today composites (`@graph`/`@main`) are **flattened**: the composite is inlined
into its primitive nodes (ADR 0004's "Flatten (inline subgraph)" choice), so
there is no collapsed representation on the canvas.

## Leading direction (aligned, not yet decided)

- **The collapsible unit is the `@graph` composite, not the nodepack.** A
  nodepack is a *namespace* (`table.*`); a composite is a real **dataflow
  boundary** with defined inputs (its params) and output (its return). Collapse
  should follow boundaries, not namespaces.
- **Preserve the composite boundary in the graph model** (stop always-flattening).
  The UI renders a composite as **one node by default** (inputs = params,
  output = return), **expandable** to reveal the inlined internals (drill-in or
  in-place — see open questions).
- **This is natural under the bijection (ADR 0004):** a collapsed composite node
  ⟷ a single call `card = render_pipeline(...)` in the parent's source;
  expanding ⟷ the inlined statements. Collapse/expand is literally "call the
  function" vs "inline it" — both are honest Python views of the same graph.
- Nodepack-level *visual grouping* (tint/box all `table.*` nodes) can come later
  as a secondary filter, but it's a weaker abstraction than the composite.

## Open questions (resolve before promoting)

1. **Default state** — collapsed-by-default for invoked composites vs
   expanded-by-default with a collapse affordance. (Leaning: collapsed for
   *imported* composites, expanded for the graph you're authoring.)
2. **Expansion model** — inline expansion on the same canvas (the group grows in
   place) vs drill-in (the composite replaces the canvas, breadcrumb back).
3. **Graph-model impact** — how to carry composite nesting without breaking the
   flat `to_python`/`run` paths (which can keep inlining) or ADR 0004's
   projection. Does the graph JSON gain a nesting representation, or is nesting a
   view-layer reconstruction from the source?
4. **Bijection edits** — editing a wire *inside* an expanded composite writes to
   the composite's `.py`, not the parent's; confirm the write-back routing.
5. **Widgets on collapsed nodes** — which inputs (the composite's params) surface
   as editable widgets on the collapsed node.
6. **Interaction with entry-point registry** (the separate multi-`@main`/picker
   idea) — a collapsed composite and a top-level entry are close cousins.

## Why deferred

Parked behind the in-flight node-inspector "Edit source" rework. This touches the
graph model, the bijection, and the canvas UI at once, so it warrants its own
Fable-advised design pass + scoped build once prioritized.
