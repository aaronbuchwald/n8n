# ADR 0019 — Output rendering should be type-driven and separable

Status: **proposed / not yet designed in full** · Scope: how a run's output is
presented (canvas node surface + the run-results output panel) · Relates to:
ADR 0010 (node-declared renderers), ADR 0013 (renderer kinds `latex` /
`html-card`).

This ADR exists to **record a direction and a constraint**, not to specify an
implementation. It was raised while removing the `height` output socket from
`sheet.calc_card` (see "What prompted this"), and the owner's instruction was
explicitly: *"for now let's just clean it up"* — build nothing yet.

## The observation

> "Not all graphs will yield an output of this type, so how we render the final
> output should be type dependent as well and may need some common inference —
> i.e. this is HTML, render a frame; this is a number, just show the output.
> For now HTML is good and that's a common workflow, but we should call that out
> in a design as a component that should be modular and separable."

## Where we are today

Rendering is **node-declared**, not value-inferred. A node opts in with
`@node(renderer=Renderer(kind, **config))` (ADR 0010) and the frontend resolves
`kind` to a component (`html-card`, `latex`). A node that declares nothing gets
the generic result chips.

That covers the authored case well, and it should stay — a node that *knows* it
emits a self-contained HTML card should say so. Two gaps:

1. **No inference for the undeclared case.** A graph whose output is a plain
   number, a list, a table-shaped dict, or a Markdown/HTML string gets generic
   chips regardless of what would actually read well. The *value* carries enough
   information to choose a sensible default presentation, and nothing uses it.
2. **The renderer set is not cleanly separable.** The kinds are a small closed
   registry in the web app. "HTML gets a sandboxed frame" is one policy among
   several that should be pluggable — including by consumers who never use the
   `sym`/`sheet` packs at all.

## The direction (to be designed)

- A **resolution order**: node-declared renderer → inferred-from-value renderer
  → generic chips. Declaration always wins; inference is the floor, never an
  override.
- A **value→presentation inference** step with a small, honest set of rules
  (e.g. HTML-ish string → sandboxed frame; number/bool → plain value with the
  socket's unit if known; list of uniform records → table; long text →
  scrollable text; anything else → chips).
- Renderers as a **separable module** with an explicit registration contract, so
  the set is extensible without editing the app shell, and so a deployment can
  ship a different set.

## Constraints any design must honour

- **The sandbox posture is not negotiable.** Untrusted HTML renders in a
  `sandbox=""` iframe (ADR 0010 D5). Host-DOM rendering stays the reviewed
  exception for markup *we* generate (the `latex` kind, ADR 0013 D5).
- **Presentation must never enter the dataflow contract.** This is the lesson
  from what prompted this ADR: a per-instance frame height was published as an
  output *socket*, which put a rendering detail into the node's public type
  surface and forced the composite to return `card.result` instead of `card`. If
  a renderer needs per-instance sizing, the mechanism is renderer config, a
  user-set value persisted in the layout sidecar (like node positions), or
  intrinsic sizing — **never an output socket**.
- **Content must never be unreachable.** Whatever a renderer draws, an
  overflowing surface scrolls on both axes rather than clipping.
- Inference must be **cheap and total** — it runs on every rendered output and
  must never throw or block on a value it does not recognise.

## What prompted this

`sheet.calc_card` briefly declared `outputs=["result", "height"]`, computing a
pixel height in Python because a scriptless sandboxed iframe cannot measure its
own content. It worked, but it leaked presentation into the graph's type
surface. The height socket was removed; the frame now uses its declared size and
the card scrolls inside it. The general problem it was solving — "how tall, and
in what shape, should *this* output be drawn?" — is what this ADR reserves.

## Not decided here

The rule set, the registration contract, whether inference lives in the frontend
or is served alongside the spec, and how a unit/type annotation on the output
socket should influence presentation. All open.
