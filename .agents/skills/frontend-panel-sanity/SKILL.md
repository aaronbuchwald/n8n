---
name: n8n:frontend-panel-sanity
description: Walk every panel and every user action of the graph-engine web UI and sanity-check each for unexpected behavior, with an option to record video for human review. Use when asked to "check the frontend panels", "sanity-check the UI", "walk every panel/action", verify the graph-engine web app end-to-end, or audit the demo UI for regressions.
---

# Frontend panel sanity

Systematically exercise the graph-engine web UI (`graph-engine/web`) — every main
panel and every user action it supports — against the live demo stack, asserting
each action's expected observable result and flagging anything unexpected.

## The canonical enumerable list

The authoritative, typed inventory of panels + actions is:

```
graph-engine/web/tests/frontend-registry.ts
```

It exports `PANELS: Panel[]`. Each `Panel` has an `id`, `name`, human
`description`, the real `testids` it owns, and `actions[]`. Each `PanelAction`
carries a human `trigger` (the concrete gesture — which `data-testid` to
click/fill/press) and `expect` (the observable result — a real testid/class),
plus a machine `steps`/`checks` encoding the harness executes. Helpers
`panelCount()` and `actionCount()` report coverage.

**This registry is the source of truth.** When the UI changes, update it first;
the harness and this skill follow it. Never invent testids — every value in the
registry is read out of `graph-engine/web/src/**` and cross-checked against the
authored `graph-engine/web/tests/*.spec.ts` contracts.

## The harness

```
graph-engine/web/tests/frontend-sanity.spec.ts
```

imports the registry and emits one Playwright test per panel; each action runs as
its own `test.step`, from a fresh layout-ready boot so actions stay independent.
For each action it drives the `steps` and asserts every `check`.

## Procedure

Iterate **every panel and every action** in the registry against the live demo
stack. For each action:

1. Boot the app at the action's `url` (default `/`) and wait for the canvas to
   reach `[data-testid="flow-canvas"][data-layout-ready="true"]`.
2. Drive the action's `trigger` (its `steps`).
3. Assert its `expect` (its `checks`).

Flag an action as **unexpected behavior** on any of:

- a **failed assertion** (a `check` did not hold), including the
  **content-reachability** invariant below — content clipped with no scrollport;
- a **console error** or **pageerror / unhandled rejection** during the action
  (the harness attaches `console`/`pageerror` probes and fails the step if any
  fire);
- a **non-zero external request** — anything leaving `127.0.0.1`/`localhost`
  (the offline posture requires exactly 0; every panel asserts this).

### Destructive actions (`review: true`)

Actions that rewrite the shared demo module (create node, save source, commit a
calc equation, drag/connect/delete on the canvas, tidy layout) or that are too
stateful to encode declaratively are marked `review: true` in the registry and
carry `custom` notes. The harness does **not** auto-drive these against the
shared workspace — it runs any read-only prelude it can, records the action as a
`needs-review` annotation, and points at the authored `*.spec.ts` that owns the
full mutate-and-restore contract (e.g. `palette.spec.ts`, `canvas-editing.spec.ts`,
`calc-widget.spec.ts`, `source-editing.spec.ts`, `new-node-authoring.spec.ts`,
`stale-run-sync.spec.ts`). To sanity-check those flows for real, run the named
spec (it restores the demo to pristine in a `finally`).

## The content-reachability invariant

`toBeVisible()` asserts **presence, not reachability**: it is `true` for content
that is laid out but clipped away by an `overflow:hidden` box the user can never
scroll. Three shipped bugs were exactly that shape and all were found by a human,
not by the suite:

1. `.ge-results__render { overflow: hidden }` — a card taller than the output
   panel was cut off with no way to scroll to the rest;
2. the calc card's `.card { overflow:hidden }` + `white-space:nowrap` cells — at
   node-card width (~280px) the rows/checks were wider than the box and
   **horizontally unreachable** (a vertical scrollbar existed; a horizontal one
   did not);
3. generally, `overflow:hidden` is the reflexive fix for two legitimate problems
   (clip to a border radius; make a flex child shrink instead of blowing out its
   parent) — both locally correct, both silently making content unreachable once
   the box is small or the content grows.

### The rule

Implemented in `graph-engine/web/tests/reachability.ts`. For **every rendered
element**, on each axis independently:

- overflowing ⇔ `scrollSize > clientSize + 2px` (the tolerance kills sub-pixel
  false positives);
- **OK** if the element **or any ancestor** has computed `overflow-x`/`overflow-y`
  (matching the overflowing axis) of `auto`/`scroll` — some scrollport can bring
  the content into view;
- **FAILURE** if no such ancestor exists on that axis.

Two subtleties it encodes deliberately:

- **The overflowing element itself need not scroll.** An element may overflow
  *visibly* and still be perfectly reachable because an ancestor scrolls — the
  calc card's `.checks` overflows visibly inside a scrolling `.sec`, which is
  correct and passes. Requiring per-element scroll produces false positives.
- **A scrollport and `min-width:max-content` must be different elements.** One box
  carrying both simply grows: `scrollWidth === clientWidth`, no scrollbar, and the
  clipping moves silently to its parent. The walk catches that at the parent, and
  the report's `clipped by:` line names the box that *actually* clips.

Three qualifiers keep it honest rather than noisy — each is a documented constant
in `reachability.ts`, not a blanket escape hatch:

| Qualifier | Why |
|---|---|
| Geometric confirmation (`visibleClipBand`) | The scroll area must really run past the last box that can show it, else an anchored popover painting outside its `overflow:visible` anchor reads as a violation while sitting plainly on screen. |
| Collapsed regions (`clientSize <= 0`, zero-extent clip band) | A collapsed dock/results panel shows nothing at all on that axis; its rail is the affordance, not a scrollbar. |
| Pan surfaces (`DEFAULT_PAN_SURFACES`) | ReactFlow's transform-panned canvas brings content into view by panning — a real gesture, just not a scrollbar. These boxes are not measured and count as scrollports; node cards **inside** them are still measured. |

`DEFAULT_IGNORE_SUBTREES` is exactly two entries (Monaco, which virtualises its
own scrolling, and the minimap, which is a proxy not content). Keep it that small —
a broad ignore list makes the invariant worthless.

### The exemption (deliberate truncation)

A single-line label that ellipsises is fine **when the full value is recoverable
another way**. Exempt, precisely:

- **x axis:** computed `text-overflow: ellipsis` **AND** a non-empty `title`;
- **y axis:** computed `-webkit-line-clamp` other than `none` **AND** a non-empty
  `title` (e.g. `.ge-node__doc`, clamped to two lines with the full docstring in
  the tooltip);
- **either axis:** an explicit `data-truncates="ok"` opt-out on the element or an
  ancestor, for author-declared truncation whose full value is recoverable some
  other way (a copy button, an expander).

Ellipsis **alone is never enough** — a truncated value with no way to read it is
the very bug this exists to catch. Do not blanket-exempt everything that
ellipsises.

### What it covers

`graph-engine/web/tests/content-reachability.spec.ts` runs the invariant over a
state × viewport matrix at **900×700** and **1500×900** (the bugs only appear once
boxes get small): boot with nodes rendered; after a Run on `?graph=capacity_check`
(the tall self-sized card — bug #1) and on the showcase graph; the node inspector
open on a node with long values; the node-catalog popover open; and both docks
collapsed to rails.

**The sandboxed-iframe caveat.** The calc card renders inside `sandbox=""` — an
opaque origin Playwright cannot evaluate into, and the sandbox must NOT be
weakened to inspect it. Instead the spec generates the card by importing the real
calcsheet module (`uv run --directory calcsheet python -c "from
calcsheet.examples.capacity import render; ..."` — no hand-generated file), mounts
it with `page.setContent(...)`, and runs the same invariant at **320px** (node-card
width), 480px and 900px.

The registry carries the same walk as panel `content-reachability` with the
`contentReachable` assertion kind, so the sanity harness enforces it too; a
`PanelAction` may pin its own `viewport`.

### Failure output

The message names the offending element (tag + testid + classes), the axis,
`scrollSize` vs `clientSize`, the **box that actually clips**, and the full
ancestor chain annotated with each box's computed overflow on that axis — so the
fix needs no re-derivation:

```
UNREACHABLE (y-axis): div.ge-results__render
  scrollHeight 599 > clientHeight 121 (478px of content past the edge)
  clipped by: div.ge-results__render
  no ancestor scrolls on y:
    div.ge-results__render — overflow-y: hidden
    div.ge-results__body — overflow-y: hidden
    section[data-testid="run-results"].ge-results — overflow-y: visible
    ...
```

### Running it

```bash
# From graph-engine/web — the invariant alone (read-only, parallel project):
pnpm exec playwright test tests/content-reachability.spec.ts --project=chromium --reporter=list

# Just the sandboxed calc card, rendered directly at node-card widths:
pnpm exec playwright test tests/content-reachability.spec.ts --grep "calc card"

# Via the registry walk (panel `content-reachability`):
pnpm exec playwright test tests/frontend-sanity.spec.ts --grep "Content reachability"
```

**A check that cannot fail is worthless** — verify it still bites after touching
`reachability.ts`: set `RunResultsPanel`'s render `Panel` back to
`style={{ overflow: 'hidden' }}`, or drop `overflow-x:auto` from `.sec` in
`calcsheet/src/calcsheet/render.py`, confirm the matching test fails with the
report above, then restore.

> Note the trap that made the first `.ge-results__render` fix a no-op:
> **react-resizable-panels writes `overflow: hidden` as an INLINE style on every
> `Panel`**, which no stylesheet rule can outrank. The override has to go on the
> Panel's `style` prop (the library merges props last).

## Recording for human review

Video recording is opt-in via the `SANITY_RECORD` env flag. When set, the
harness declares `test.use({ video: 'on' })` and Playwright writes a
`video.webm` per test under the output dir (`test-results/<test-name>/`).
Recordings, plus any `needs-review` annotations, are the artifact a human reviews.

## Commands

Run from `graph-engine/web`. **Do not** run `playwright install` — Chromium is
pre-installed and pinned in `playwright.config.ts`.

```bash
# Enumerate the whole walk (no stack needed) — sanity of the registry itself:
pnpm exec playwright test tests/frontend-sanity.spec.ts --list

# Walk every panel/action against the live demo stack (boots FastAPI + the built
# web bundle via the config's webServer; asserts each expect):
pnpm exec playwright test tests/frontend-sanity.spec.ts --reporter=list 2>&1 | tail -60

# Same walk, RECORDING video of each panel for human review:
SANITY_RECORD=1 pnpm exec playwright test tests/frontend-sanity.spec.ts --reporter=list
#   → recordings land in graph-engine/web/test-results/<test-name>/video.webm

# One panel only (grep the panel name or id):
pnpm exec playwright test tests/frontend-sanity.spec.ts --grep "Workbench shell"
```

Typecheck after editing the registry or harness:

```bash
pnpm -C graph-engine/web typecheck
```

## Notes

- The walk boots the live stack (ports 8000 API / 4173 web via
  `playwright.config.ts` `webServer`). If a concurrent job holds those ports, do
  authoring + `--list` + `typecheck` only and let the orchestrator run the real
  pass.
- Keep the registry and the authored `*.spec.ts` in agreement: the specs are the
  detailed, restore-safe contracts; the registry is the enumerable index over
  them. A new panel/action means: add it to `frontend-registry.ts` (grounded in
  real testids), then re-run `--list` to confirm it enumerates.
