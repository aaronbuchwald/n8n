# ADR 0014 — Workbench panel layout: resizable, collapsible regions

Status: **proposed — MAJOR DECISIONS below are FOR SIGN-OFF** · Scope:
`graph-engine/web` only (no engine/server change) · Relates to: ADR 0008 (the
one client store and its rules — layout state deliberately stays OUT of it),
ADR 0009 (entry switching remounts the main subtree — which persistence must
survive), ADR 0011 W5 (palette), ADR 0013 (the inspector is the one editing
surface — this ADR gives it a real, resizable home).

## Context

The web UI has grown five panels around the canvas, composed today by ad-hoc
CSS with **no resizing, no collapsing, and no persistence**:

- `.ge-main` is a flex row: **Palette** (fixed `236px` left column),
  `.ge-workspace` (a column holding the **canvas** plus, when a run exists,
  **RunResultsPanel** as a bottom strip capped at `max-height: 42%`), and —
  when open — **ExportPanel** and/or **NewNodePanel** as fixed-width
  (`34rem`, `max-width: 50%`) right columns.
- **NodeInspector** is not in the flow at all: it is `position: absolute`
  inside `.ge-canvas` (`width: 308px`, pinned to the right edge), floating
  *over* the canvas — it occludes nodes instead of sharing space with them.
- **SourceEditor** is not a panel of its own: it renders inside the inspector
  (edit mode, ADR 0013) or inside NewNodePanel (create mode). Its Monaco
  wrapper already sets `automaticLayout: true`.
- `GraphView` already reacts to container resize: a `ResizeObserver` on
  `.ge-canvas` calls `fitView` (rAF-wrapped) whenever the canvas box changes —
  today triggered by the results strip or export column appearing.
- Constraints that bind every choice below: **offline / no-CDN** (every asset
  bundled; the Playwright suite asserts `EXTERNAL_REQUESTS must be 0`),
  React 18 + Vite 5, `@xyflow/react` 12 in the center, and the store rules
  (ADR 0008: the sync store is for *shared server-derived* state with a
  single mutation funnel — presentation-local state like node positions
  already lives beside it in its own module, `store/positions.ts`).

None of the panel sizes fit everyone: the palette wastes width on small
screens, the inspector hides the graph it describes, the export column can't
be widened to read long lines, and every reload forgets everything.

### Locked criteria (decided with the user — not re-litigated here)

1. **Interaction = VS Code default**: draggable sashes between regions, a
   per-region collapse control, persisted sizes. NOT move/float/rearrange in
   v1 — but the seam must allow a docking follow-up.
2. **Collapse = to a thin rail**: a collapsed region leaves a slim strip with
   an icon/label at its edge; clicking it re-expands. Always discoverable.
3. **Implementation = a proven library**, chosen against our constraints and
   flagged for sign-off (D2).
4. **Scope = all major regions**, including promoting the secondary panels
   (Export, NewNode, SourceEditor) to proper docked, resizable residents (D3).
5. **Persistence**: sizes + collapsed state survive reloads via localStorage.

## Decisions (proposed)

### D1 — The region model: 3 sashes, 4 regions, rails at the edges

```
┌────────────────────────── topbar (fixed, unchanged) ──────────────────────────┐
├──────┬─┬────────────────────────────────────────────┬─┬──────────────────────┤
│      │s│                                            │s│                      │
│ left │a│              center: canvas                │a│  right dock          │
│ Pal- │s│              (ReactFlow)                   │s│  tabs: Inspector ·   │
│ ette │h│                                            │h│  Export · New node   │
│      │ ├─────────────────── sash ───────────────────┤ │  (SourceEditor lives │
│      │ │      bottom: Run results                   │ │   inside these tabs) │
├──────┴─┴────────────────────────────────────────────┴─┴──────────────────────┤
│ (collapsed regions leave a rail on their edge: ▐ left ▌ right ▂ bottom)       │
└───────────────────────────────────────────────────────────────────────────────┘
```

- **Nested split groups.** One horizontal group: `left | center | right`.
  The center panel contains a vertical group: `canvas / bottom`. Two groups,
  three sashes total. The topbar and the transient banners (action error,
  toast, stale-run) stay exactly where they are — they are not regions.
- **The bottom panel spans the center only** (between the sidebars, VS Code's
  default panel position). Rationale: results rows exist to focus canvas
  nodes — keeping them column-aligned with the canvas preserves that spatial
  link, and it means the bottom sash only fights one neighbor. *(FOR REVIEW #4.)*
- **The inspector moves out of the canvas overlay into the right dock.** This
  is the one real relocation: `.ge-inspector` stops being
  `position: absolute` inside `.ge-canvas` and becomes the right region's
  default tab. The canvas stops being occluded, and widening the inspector
  genuinely narrows the canvas (which the existing ResizeObserver already
  handles — D4).
- **Sizes** (defaults mirror today's CSS so day one looks familiar):

  | Region | Default | Min | Max | Collapsible |
  |---|---|---|---|---|
  | left (Palette) | 236px-equivalent (~15%) | 10% | 25% | yes → left rail |
  | right dock | per-tab: Inspector ~340px-eq, code tabs ~34rem-eq | 15% | 50% | yes → right rail |
  | bottom (Run results) | 30% | 12% | 60% | yes → bottom rail |
  | center (canvas) | remainder | 30% | — | never |

  Constraints are expressed in **percent** (the library's native unit — see
  D2's caveat); the defaults above are the px values translated at a
  reference 1440px viewport. The canvas can never be collapsed or squeezed
  below its min — it is the app.
- **Collapse behavior**: each region header gets a chevron collapse control;
  dragging a sash past the region's min **snaps it collapsed** (the library's
  `collapsible` semantics — same feel as VS Code's sidebar snap). A collapsed
  region renders **size 0** in the group, and a **rail** appears in its
  place:
  - Rails are **fixed-width elements outside the split group** (left/right:
    ~40px vertical strip with the region icon + rotated label; bottom: ~28px
    horizontal strip with label + result count when a run exists). Rendering
    rails outside the group sidesteps the library's percent-only
    `collapsedSize` (a thin fixed-px rail as a percent is viewport-dependent)
    and gives us full control of the affordance.
  - Clicking a rail (or its keyboard-focusable button) re-expands the region
    to its **pre-collapse size** (the library restores it; we persist it).
  - **Auto-expand on demand**: a run landing auto-expands a collapsed bottom
    region; selecting a node auto-expands a collapsed right dock onto the
    Inspector tab; Export/New-node opening auto-expands onto their tab. A
    surface the user summoned must never open invisibly behind a rail.
- **No activity bar in v1.** VS Code's activity bar earns its chrome by
  hosting many view containers; we have three regions, each with its own
  rail. An activity bar can be added later without disturbing this model.
  *(FOR REVIEW #3.)*

### D2 — Library: `react-resizable-panels` — **FOR SIGN-OFF (top decision)**

| Criterion | **react-resizable-panels** (recommended) | Allotment | dockview / rc-dock |
|---|---|---|---|
| React 18 + Vite | First-class; declarative `<PanelGroup>/<Panel>/<PanelResizeHandle>` components | Fine; React wrapper over VS Code's imperative split-view | dockview fine (React bindings over TS core); rc-dock has React 18 rough edges |
| ReactFlow coexistence | Sash is its own DOM separator; drag uses pointer capture on the handle — events never reach the ReactFlow pane | Same sash isolation (VS Code lineage) | Same, plus its own drag-overlay layers to keep clear of the canvas |
| Bundle / offline | **~5 kB gz, zero runtime deps**, plain npm — trivially no-CDN | ~30 kB + several small deps (resize-observer hook, event emitter, lodash pieces) + a required CSS import | dockview ~100 kB+ with its own theming CSS; rc-dock similar class |
| Accessibility / keyboard resize | **Built-in WAI-ARIA window-splitter**: handles are focusable `role="separator"`, Arrow/Home/End resize, `aria-valuenow` exposed | **No built-in keyboard resize** (long-standing gap) — we'd bolt it on | Partial; tab-focused, not splitter-pattern |
| Collapse support | `collapsible` + `collapsedSize` + `onCollapse`/`onExpand`, imperative `collapse()/expand()/resize()` per-panel refs — snap-closed on drag past min is native | `snap` gives snap-to-zero; no collapse API/events as first-class (visibility toggling is manual) | Native (tabs/groups), but as part of full docking |
| Persistence | **Built-in `autoSaveId`** (localStorage; pluggable `storage`) | Manual (`onChange` → roll our own) | Own layout-JSON serialization (heavier than we need) |
| Sizing model | **Percent-only** (v2 dropped px units) — px-ish mins are approximations; our rails avoid needing px `collapsedSize` by living outside the group (D1) | Pixel-based (true VS Code sashes incl. min/max px) | Pixel-based |
| Docking later | Not provided — by design here; the seam (D6) keeps it swappable | Not provided | **The point** — and why they're overkill for the locked v1 scope |
| Maintenance / ecosystem | Very active (Brian Vaughn); it's what shadcn/ui wraps — huge install base | Maintained but slower-moving | dockview active; rc-dock quiet |

**Recommendation: `react-resizable-panels`.** It wins on the three criteria
that bind hardest — accessibility (the only one with the splitter keyboard
pattern built in), offline weight (5 kB, zero deps), and built-in
collapse+persistence primitives that map 1:1 onto the locked interaction
model. Its one real weakness — percent-only sizing — costs us little because
(a) region constraints are proportional by nature, and (b) the collapse-to-
rail affordance is designed outside the group (D1) so no fixed-px collapsed
size is ever needed. Allotment's pixel-true sashes don't outweigh shipping
our own keyboard resizing and persistence; a docking library would buy
exactly the scope v1 excludes, at 20× the bytes.

### D3 — Secondary panels: the right dock is a **tab stack** — FOR SIGN-OFF

The right region hosts a VS Code-style tab strip with up to three tabs:

- **Inspector** — present while a node is selected (unchanged trigger:
  canvas click / results-row focus). Closing the tab = deselect.
- **Export** — present while `python !== null` (unchanged trigger: topbar
  button). Keeps its side-by-side "graph ↔ code at a glance" purpose — a tall
  code column reads far better than a bottom strip would.
- **New node** — present while `creatingSource` (unchanged trigger). It is
  `SourceEditor` in create mode, exactly as today, now resizable.

Rules:

- Opening a surface **activates its tab** (and expands a collapsed dock).
  Closing the active tab activates the most recently active remaining tab;
  the dock with zero tabs shows the Inspector placeholder ("select a node…")
  or may be collapsed.
- **Per-tab-kind width memory**: the inspector wants ~340px; the code tabs
  want ~34rem. Switching tabs animates the dock to that tab-kind's remembered
  width (each remembered on resize, persisted — D5). One sash, widths that
  fit the content.
- **The Escape cascade keeps its exact order** (source editor → inspector →
  new-node → export → results): the App-level handler is untouched in
  ordering; only "close inspector/export/new-node" now also updates the
  active tab. Existing tests encode this order and must keep passing.
- **SourceEditor stays a guest, not a region**: inside the Inspector tab
  (edit mode) and the New node tab (create mode). It inherits resizability
  from the dock; Monaco's `automaticLayout: true` already tracks it.

Alternatives considered: **(B)** a second right column ("editor column")
between canvas and inspector for the code surfaces — rejected: two right
sashes, up to four columns, and the canvas gets crushed; **(C)** Export as a
bottom tab beside Run results (the literal VS Code panel-tabs pattern) —
rejected: exported Python is tall/narrow, and the current side-by-side
graph↔code correspondence is a deliberate feature. C remains the fallback if
sign-off dislikes tabs-on-the-right.

### D4 — ReactFlow in the center: resize signal + sash isolation

The trickiest correctness point; the good news is the seams already exist.

- **Resize signal**: `GraphView`'s ResizeObserver on `.ge-canvas` remains the
  single resize entry point — sash drags, collapses, and tab-width changes
  all reach the canvas as container resize, with **zero new coupling**
  between the workbench and GraphView (the workbench never calls into the
  canvas). Two adjustments:
  1. **Debounce the refit** (~150ms trailing): a sash drag streams resize
     events every frame; refitting per-frame both costs layout work and makes
     the graph "swim" under the cursor. Debounced, the canvas content pans
     naturally during the drag and settles with one clean `fitView` when the
     sash stops. This also preserves today's behavior for one-shot resizes
     (results strip opening) — one refit, slightly later.
  2. Keep the existing policy of *always refitting on container resize*
     (today's semantics). Preserving the user's viewport instead is a
     defensible alternative — flagged as a minor decision *(FOR REVIEW #5)*.
- **Sash-drag vs pan/zoom isolation**: the resize handle is a dedicated
  sibling DOM element between panels — it is never inside `.ge-canvas`. The
  library pointer-captures the handle on pointerdown, sets a document-level
  cursor, and suppresses text selection for the duration; ReactFlow's pane
  only ever sees events targeted at itself, so a sash drag can never start a
  pan, and a pan that reaches the canvas edge does not grab the sash
  (capture requires pointerdown *on the handle*). We style the visible sash
  at 1px with a hit area of ~8px **centered on the divider** — any hit-slop
  overlap onto the canvas stays ≤4px and, being a separate element above the
  pane, wins hit-testing outright rather than "fighting".
- **Layout pipeline unaffected**: the measuring→framing→ready phases and the
  per-entry remount (`key={graphId}`) don't change. The initial layout
  measures against whatever size the restored workbench gives `.ge-canvas` —
  restoration happens synchronously from localStorage before first paint, so
  the aspect-driven auto-layout sees the real canvas box.
- **Monaco/KaTeX in resizable regions**: Monaco already has
  `automaticLayout: true`; KaTeX output is static flow content. No work.

### D5 — Persistence: localStorage, UI-local, versioned — NOT the sync store

- **Placement**: a new tiny module `web/src/store/layout.ts`, the sibling
  precedent of `store/positions.ts` — presentation state with its own storage
  path, sharing no lock, queue, or epoch with the sync store. ADR 0008's
  rules govern *shared server-derived* payloads; panel geometry is
  device-local presentation and enters neither the mutation funnel nor any
  `ingest*` action. Zero third-party state involvement, same as the rest.
- **What's stored, under which keys** (all localStorage):
  - Split sizes: the library's `autoSaveId` per group —
    `ge-workbench-main` and `ge-workbench-center` (stored by the library
    under its own `react-resizable-panels:*` prefix). Collapsed panels
    persist as size 0 with their pre-collapse size retained by the library.
  - Ours, one key `ge:workbench:v1`:
    `{ collapsed: {left, right, bottom}, rightWidthByTab: {inspector, code}, activeRightTab }`
    — the rail states (drives rail rendering before the groups mount), the
    per-tab-kind dock widths (D3), and the last active tab.
- **Versioned + fail-safe**: the `v1` suffix is the schema version; a parse
  failure or unknown version discards to defaults (never migrates, never
  throws). localStorage unavailable → in-memory fallback for the session.
- **Device-global, not per graph entry** *(FOR REVIEW #6)*: your workbench
  shape is about your screen, not the graph. This also neutralizes an
  existing behavior: the whole `.ge-main` subtree remounts on every entry
  switch (boot cycles through `loading` — App.tsx comment at the
  `WidgetEditingProvider`), so the workbench shell **will** remount; layout
  continuity across switches therefore comes from storage restore, which the
  `autoSaveId` mechanism gives us for free.
- **Reset**: a "Reset layout" item (topbar overflow / the export-button row)
  clears both key families and re-applies defaults via the panel refs — no
  reload required. Also the escape hatch for a corrupt saved layout.

### D6 — The docking seam (what v1 deliberately does NOT do)

No drag-to-rearrange, floating, or region reassignment in v1. The seam that
keeps a docking follow-up cheap:

- Panel **content components stay layout-ignorant**: Palette, NodeInspector,
  RunResultsPanel, ExportPanel/SourceEditor keep their current props and
  render wherever mounted. All region knowledge lives in one place —
  `components/workbench/` (the shell, rails, tab strip).
- The right-dock **tab model** (D3) is already the unit a docking library
  moves around; if a later ADR adopts e.g. dockview, the migration is
  "replace the shell, keep the tabs' content components", contained to the
  workbench directory.
- We do **not** pre-abstract a layout interface over the library — YAGNI;
  the containment boundary is the directory, not an adapter layer.

## Verification criteria (Playwright, `tests/workbench-layout.spec.ts`)

All against the local Vite/preview server; the suite's standing
`EXTERNAL_REQUESTS must be 0` assertion applies (the new dependency is
bundled — no CDN, no runtime fetch).

1. **Resize by sash**: dragging each of the three sashes changes the
   adjacent regions' widths/heights (assert on bounding boxes), and
   `.ge-canvas` clientWidth/Height changes to match.
2. **Collapse to rail**: each region's collapse control hides the region and
   shows its rail (`data-testid="rail-left|rail-right|rail-bottom"`);
   clicking the rail re-expands to the pre-collapse size.
3. **Snap-collapse**: dragging a sash past a region's min snaps it collapsed
   (rail appears).
4. **Persistence**: resize + collapse, `page.reload()` — sizes and collapsed
   state restored (assert boxes, not just storage); the storage keys named in
   D5 exist.
5. **Canvas correctness**: after a sash drag settles, the graph is refit
   (all nodes within the viewport); *during* a sash drag ReactFlow's
   viewport transform does not change (no pan was triggered).
6. **Keyboard resize**: Tab reaches each sash (`role="separator"`); Arrow
   keys change the split (`aria-valuenow` moves); the collapse control and
   rails are focusable and Enter/Space-operable.
7. **Secondary docking**: Export opens as the active right tab at the code
   width and is resizable; New node likewise hosts the create-mode
   SourceEditor; tab switching restores per-tab-kind widths; the Inspector
   tab survives an Export open/close with selection intact.
8. **Escape cascade order unchanged** — the existing specs
   (`source-editing`, `canvas-editing`, `widgets`, `stale-run-sync`) stay
   green, with selector-only updates where the inspector's DOM home moved.
9. **Entry switch**: picking another graph (GraphPicker) preserves the
   workbench geometry (storage-restored across the remount).
10. **Auto-expand**: with the bottom region collapsed, Run auto-expands it;
    with the right dock collapsed, node selection auto-expands the Inspector.
11. **Offline build**: `pnpm build` completes with no network; bundle-size
    delta for the new dependency recorded in the PR (~5 kB gz expected).

## Build plan (post-sign-off)

| Stream | Scope | Owns (no overlap) | Model | Depends on |
|---|---|---|---|---|
| **14-W1 shell** | Add dependency; `Workbench.tsx` (groups/sashes), `Rail.tsx`, region headers; recompose `.ge-main` in App.tsx; workbench CSS section | `components/workbench/*`, App.tsx layout JSX, `styles.css` (new section + region blocks) | Opus | — |
| **14-W2 canvas** | Debounced refit; sash-isolation checks; `data-layout-ready` interplay | `GraphView.tsx` (observer effect only) | Opus | 14-W1 (interface: none — resize arrives via container) |
| **14-W3 right dock** | Tab strip; Inspector relocation out of `.ge-canvas`; Export/NewNode hosting; Escape-cascade wiring; per-tab widths | `workbench/RightDock.tsx`, `NodeInspector.tsx` / `ExportPanel.tsx` / `NewNodePanel.tsx` (header/mount changes), App.tsx handler wiring | Sonnet | 14-W1 |
| **14-W4 persistence + tests** | `store/layout.ts`; reset affordance; `workbench-layout.spec.ts`; selector updates in existing specs | `store/layout.ts`, `tests/workbench-layout.spec.ts`, touched existing specs | Sonnet | 14-W1 (W3 for tab tests) |

Sequencing: 14-W1 first (it defines the DOM); then W2 ∥ W3 ∥ W4. Land on
`integration/wave-1` behind nothing — the layout replaces the old CSS
composition wholesale (defaults reproduce today's look; there is no
meaningful "old layout" worth flagging).

## MAJOR DECISIONS / FOR REVIEW

1. **Library = `react-resizable-panels`** (D2) — the top sign-off. The
   runner-up (Allotment) trades built-in keyboard accessibility and
   persistence for pixel-true sashes; a docking library is scope v1 excludes.
2. **Secondary panels = right-dock tab stack** (Inspector · Export · New
   node) with per-tab-kind width memory (D3). Fallback if rejected: Export
   as a bottom tab beside Run results.
3. **No activity bar in v1** — per-edge collapse rails carry
   discoverability (D1).
4. **Bottom panel spans the center only**, not full-width under the
   sidebars (D1).
5. **Refit policy on canvas resize**: keep today's always-refit, debounced
   (~150ms) — vs. preserving the user's viewport (D4).
6. **Layout persistence is device-global**, not per graph entry (D5).
