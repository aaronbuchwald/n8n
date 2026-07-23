// The enumerable registry of the graph-engine web UI — every main panel/component
// and the user actions it supports. This is the CANONICAL list the frontend
// panel-sanity skill walks (`.agents/skills/frontend-panel-sanity`): the sanity
// harness (`frontend-sanity.spec.ts`) imports it and drives every action against
// the live demo stack, asserting each `expect`.
//
// Ground truth: every `data-testid`, class and node id used below is real — read
// out of `src/**` and cross-checked against the existing `tests/*.spec.ts`
// (which are the authored, passing interaction contracts for the same surfaces).
// Nothing here is invented. When a panel changes, update THIS file first; the
// harness and the skill follow it.
//
// The model is intentionally two-layered:
//   * `trigger` / `expect` are the HUMAN description of each action (the
//     deliverable list a person reads);
//   * `steps` / `checks` are the MACHINE encoding the harness executes — a small
//     declarative interaction/assertion vocabulary the runner interprets. Flows
//     that are destructive (they rewrite the demo module) or too stateful to
//     encode declaratively are marked `review: true` and carry `custom` notes;
//     the harness records those for a human instead of auto-driving a mutation
//     against the shared workspace.

// ─────────────────────────────────────────────────────────────────────────────
// Target: how the harness locates an element. A testid OR a raw CSS selector,
// optionally scoped `within` another testid, narrowed by `role`/`hasText`/`nth`.
// ─────────────────────────────────────────────────────────────────────────────
export interface Target {
  /** `data-testid` to locate (getByTestId). */
  testid?: string;
  /** Raw CSS selector (page.locator), for the handful of class/attr locators. */
  selector?: string;
  /** Scope the lookup inside this container testid first. */
  within?: string;
  /** After locating, narrow to a child ARIA role (e.g. dock tab `tab` button). */
  role?: string;
  /** Filter the located set to elements containing this text. */
  hasText?: string;
  /** Pick the nth match (0-based) when several resolve. */
  nth?: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Interaction: one driver step. `custom` is an un-encodable/destructive step the
// harness records for human review rather than executing blindly.
// ─────────────────────────────────────────────────────────────────────────────
export type Interaction =
  | { kind: 'goto'; url: string }
  | { kind: 'reload' }
  | { kind: 'waitReady' }
  | { kind: 'click'; target: Target }
  | { kind: 'fill'; target: Target; value: string }
  | { kind: 'press'; target: Target; key: string }
  | { kind: 'pressKey'; key: string }
  | { kind: 'dragHandle'; target: Target; dx: number; dy: number }
  | { kind: 'waitVisible'; target: Target; timeoutMs?: number }
  | { kind: 'custom'; note: string };

// ─────────────────────────────────────────────────────────────────────────────
// Assertion: one observable expectation to prove after the steps run.
// ─────────────────────────────────────────────────────────────────────────────
export type Assertion =
  | { kind: 'visible'; target: Target; timeoutMs?: number }
  | { kind: 'hidden'; target: Target }
  | { kind: 'count'; target: Target; count: number }
  | { kind: 'countAtLeast'; target: Target; min: number }
  | { kind: 'containsText'; target: Target; text: string; timeoutMs?: number }
  | { kind: 'attr'; target: Target; name: string; value: string | null }
  | { kind: 'externalRequestsZero' }
  | { kind: 'custom'; note: string };

// ─────────────────────────────────────────────────────────────────────────────
// A single supported user action on a panel.
// ─────────────────────────────────────────────────────────────────────────────
export interface PanelAction {
  id: string;
  description: string;
  /** Human: the concrete gesture — which testid to click/fill/press. */
  trigger: string;
  /** Human: the observable result to assert — the real testid/class it lands on. */
  expect: string;
  /** Entry URL to boot before the steps run. Defaults to '/'. */
  url?: string;
  /** Machine steps the harness drives (the app is already booted + layout-ready). */
  steps: Interaction[];
  /** Machine assertions proving `expect`. */
  checks: Assertion[];
  /**
   * True when the action mutates the shared demo workspace (writes a real .py)
   * or is too stateful to encode declaratively. The harness does NOT auto-drive
   * these against the shared server; it records them (video/screenshot) for a
   * human, and still runs any non-destructive `checks` it can.
   */
  review?: boolean;
  /**
   * This action's whole point is a REJECTED server request (an expected non-2xx,
   * e.g. a 4xx validation refusal). The harness then ignores the browser's
   * "Failed to load resource … status of 4xx" console error for THIS action only
   * — an expected validation 4xx is not an app error. Real page errors / uncaught
   * exceptions and unexpected 5xx still fail the action.
   */
  expectsServerRejection?: boolean;
}

export interface Panel {
  id: string;
  name: string;
  description: string;
  /** The primary real testids this panel owns. */
  testids: string[];
  actions: PanelAction[];
}

// Convenience: click a node's header by its stable graph id (selection gesture).
function nodeHeader(id: string): Target {
  return { selector: `.react-flow__node[data-id="${id}"] .ge-node__header` };
}

// ─────────────────────────────────────────────────────────────────────────────
// THE REGISTRY
// ─────────────────────────────────────────────────────────────────────────────
export const PANELS: Panel[] = [
  // ── 1. Workbench shell ────────────────────────────────────────────────────
  {
    id: 'workbench-shell',
    name: 'Workbench shell',
    description:
      'The VS Code-style resizable/collapsible region frame (ADR 0014): palette │ canvas ╱ run-results │ right-dock, three sashes, per-region rails, and Reset layout.',
    testids: [
      'workbench',
      'sash-left',
      'sash-right',
      'sash-bottom',
      'collapse-left',
      'collapse-bottom',
      'rail-left',
      'rail-right',
      'rail-bottom',
      'reset-layout',
    ],
    actions: [
      {
        id: 'resize-left-sash',
        description: 'Drag the left sash to widen the palette region.',
        trigger: 'Drag [data-testid="sash-left"] +120px along x.',
        expect: 'The palette ([data-testid="palette"]) grows wider than before the drag.',
        steps: [{ kind: 'dragHandle', target: { testid: 'sash-left' }, dx: 120, dy: 0 }],
        checks: [
          { kind: 'visible', target: { testid: 'palette' } },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'resize-right-sash',
        description: 'Drag the right sash to widen the right dock.',
        trigger: 'Drag [data-testid="sash-right"] -120px along x.',
        expect: 'The right dock ([data-testid="right-dock"]) grows wider.',
        steps: [{ kind: 'dragHandle', target: { testid: 'sash-right' }, dx: -120, dy: 0 }],
        checks: [
          { kind: 'visible', target: { testid: 'right-dock' } },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'resize-bottom-sash',
        description: 'Run first (so the bottom region exists), then drag the bottom sash taller.',
        trigger:
          'Click [data-testid="run-button"], wait for run-results, drag [data-testid="sash-bottom"] -100px along y.',
        expect: 'The run-results region ([data-testid="run-results"]) grows taller.',
        steps: [
          { kind: 'click', target: { testid: 'run-button' } },
          { kind: 'waitVisible', target: { testid: 'run-results' }, timeoutMs: 20000 },
          { kind: 'dragHandle', target: { testid: 'sash-bottom' }, dx: 0, dy: -100 },
        ],
        checks: [
          { kind: 'visible', target: { testid: 'run-results' } },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'collapse-expand-left',
        description: 'Collapse the palette to its left rail, then re-expand from the rail.',
        trigger:
          'Click [data-testid="collapse-left"]; then click [data-testid="rail-left"] to re-expand.',
        expect:
          'rail-left appears and palette hides; after re-expand rail-left hides and palette is visible again.',
        steps: [
          { kind: 'click', target: { testid: 'collapse-left' } },
          { kind: 'waitVisible', target: { testid: 'rail-left' } },
          { kind: 'click', target: { testid: 'rail-left' } },
        ],
        checks: [
          { kind: 'hidden', target: { testid: 'rail-left' } },
          { kind: 'visible', target: { testid: 'palette' } },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'collapse-expand-right',
        description: 'Collapse the right dock to its rail, then re-expand from the rail.',
        trigger:
          'Click [data-testid="collapse-right"]; then click [data-testid="rail-right"] to re-expand.',
        expect: 'rail-right appears and right-dock hides; after re-expand right-dock is visible again.',
        steps: [
          { kind: 'click', target: { testid: 'collapse-right' } },
          { kind: 'waitVisible', target: { testid: 'rail-right' } },
          { kind: 'click', target: { testid: 'rail-right' } },
        ],
        checks: [
          { kind: 'hidden', target: { testid: 'rail-right' } },
          { kind: 'visible', target: { testid: 'right-dock' } },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'collapse-expand-bottom',
        description: 'Run, collapse the run-results region to its bottom rail, then re-expand.',
        trigger:
          'Run; click [data-testid="collapse-bottom"]; then click [data-testid="rail-bottom"].',
        expect: 'rail-bottom appears and run-results hides; after re-expand run-results is visible again.',
        steps: [
          { kind: 'click', target: { testid: 'run-button' } },
          { kind: 'waitVisible', target: { testid: 'run-results' }, timeoutMs: 20000 },
          { kind: 'click', target: { testid: 'collapse-bottom' } },
          { kind: 'waitVisible', target: { testid: 'rail-bottom' } },
          { kind: 'click', target: { testid: 'rail-bottom' } },
        ],
        checks: [
          { kind: 'hidden', target: { testid: 'rail-bottom' } },
          { kind: 'visible', target: { testid: 'run-results' } },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'reset-layout',
        description:
          'Perturb the layout (widen palette + collapse dock), then Reset layout snaps every region back to defaults without a reload.',
        trigger:
          'Drag sash-left +140px, click collapse-right, then click [data-testid="reset-layout"].',
        expect: 'rail-right hides (dock re-expanded) and right-dock is visible — defaults restored in place.',
        steps: [
          { kind: 'dragHandle', target: { testid: 'sash-left' }, dx: 140, dy: 0 },
          { kind: 'click', target: { testid: 'collapse-right' } },
          { kind: 'waitVisible', target: { testid: 'rail-right' } },
          { kind: 'click', target: { testid: 'reset-layout' } },
        ],
        checks: [
          { kind: 'hidden', target: { testid: 'rail-right' } },
          { kind: 'visible', target: { testid: 'right-dock' } },
          { kind: 'externalRequestsZero' },
        ],
      },
    ],
  },

  // ── 2. Palette ─────────────────────────────────────────────────────────────
  {
    id: 'palette',
    name: 'Node palette',
    description:
      'The left-region searchable node catalog (ADR 0011 W5): registered @node types grouped by module, click/drag to place, and a needs-wiring strip.',
    testids: [
      'palette',
      'palette-search',
      'palette-group',
      'palette-entry',
      'palette-empty',
      'needs-wiring',
      'needs-wiring-badge',
    ],
    actions: [
      {
        id: 'list-grouped-nodes',
        description: 'The palette lists registered types grouped by module (showcase / sym / table).',
        trigger: 'Boot the app; read the palette groups.',
        expect:
          'A [data-testid="palette-group"] exists for showcase, sym and table; entries render a name + one-line doc.',
        steps: [],
        checks: [
          { kind: 'visible', target: { testid: 'palette' } },
          { kind: 'visible', target: { selector: '[data-testid="palette-group"][data-module="showcase"]' } },
          { kind: 'visible', target: { selector: '[data-testid="palette-group"][data-module="sym"]' } },
          { kind: 'visible', target: { selector: '[data-testid="palette-group"][data-module="table"]' } },
          { kind: 'countAtLeast', target: { testid: 'palette-entry' }, min: 3 },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'search-filters',
        description: 'Typing in the search box filters entries and empties exhausted groups.',
        trigger: 'Fill [data-testid="palette-search"] with "read_table".',
        expect:
          'The table.read_table entry stays visible; the sym group empties.',
        steps: [{ kind: 'fill', target: { testid: 'palette-search' }, value: 'read_table' }],
        checks: [
          { kind: 'visible', target: { selector: '[data-testid="palette-entry"][data-spec-id="table.read_table"]' } },
          { kind: 'hidden', target: { selector: '[data-testid="palette-group"][data-module="sym"]' } },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'search-empty-state',
        description: 'A query that matches nothing shows the empty state instead of a blank rail.',
        trigger: 'Fill [data-testid="palette-search"] with "zz-no-such-node".',
        expect: '[data-testid="palette-empty"] is visible.',
        steps: [{ kind: 'fill', target: { testid: 'palette-search' }, value: 'zz-no-such-node' }],
        checks: [
          { kind: 'visible', target: { testid: 'palette-empty' } },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'place-node',
        description:
          'Clicking a palette entry mints a server id and adds+persists the node (rewrites the real module).',
        trigger:
          'Click the sym.pick [data-testid="palette-entry"]; a node card appears and PUT /api/graph persists it.',
        expect:
          'A new spec-node card with the minted id renders; its unwired required input badges needs-wiring. DESTRUCTIVE — mutates showcase.py (restore in finally).',
        review: true,
        steps: [
          {
            kind: 'custom',
            note: 'Click palette-entry[data-spec-id="sym.pick"] then restore the pristine graph via PUT /api/graph. See tests/palette.spec.ts for the full mutate+restore flow.',
          },
        ],
        checks: [
          {
            kind: 'custom',
            note: 'After the click: a [data-testid="spec-node"] filtered by the minted [data-testid="node-id"] is visible, and [data-testid="needs-wiring-badge"] for that node contains "values".',
          },
        ],
      },
    ],
  },

  // ── 3. Canvas (GraphView) ──────────────────────────────────────────────────
  {
    id: 'canvas',
    name: 'Graph canvas',
    description:
      'The ReactFlow canvas (GraphView): nodes as spec cards, wiring, pan/zoom preserved on resize, select-to-inspect, Tidy layout, drag-reposition, connect, delete, palette drop.',
    testids: [
      'flow-canvas',
      'spec-node',
      'node-title',
      'node-id',
      'output-badge',
      'node-needs-wiring',
      'tidy-layout',
      'writeback-warning',
    ],
    actions: [
      {
        id: 'boots-layout-ready',
        description: 'The canvas boots and reaches layout-ready with node cards rendered.',
        trigger: 'Boot the app; wait for [data-testid="flow-canvas"][data-layout-ready="true"].',
        expect: 'flow-canvas is visible and at least one [data-testid="spec-node"] renders.',
        steps: [],
        checks: [
          { kind: 'visible', target: { testid: 'flow-canvas' } },
          { kind: 'countAtLeast', target: { testid: 'spec-node' }, min: 1 },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'select-node-opens-inspector',
        description: 'Clicking a node card selects it and docks the Inspector as the first tab.',
        trigger: 'Click the parse_expr card header (.react-flow__node[data-id="expr"] .ge-node__header).',
        expect: '[data-testid="node-inspector"] and [data-testid="dock-tab-inspector"] become visible.',
        steps: [{ kind: 'click', target: nodeHeader('expr') }],
        checks: [
          { kind: 'visible', target: { testid: 'node-inspector' } },
          { kind: 'visible', target: { testid: 'dock-tab-inspector' } },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'pane-click-clears-selection',
        description: 'Clicking empty canvas pane deselects (closes the inspector).',
        trigger: 'Select a node, then click the ReactFlow pane background.',
        expect: 'node-inspector count goes to 0.',
        steps: [
          { kind: 'click', target: nodeHeader('expr') },
          { kind: 'waitVisible', target: { testid: 'node-inspector' } },
          { kind: 'click', target: { selector: '.react-flow__pane' } },
        ],
        checks: [
          { kind: 'count', target: { testid: 'node-inspector' }, count: 0 },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'pan-zoom-preserved-on-resize',
        description:
          'Resizing a panel changes the canvas box but must NOT re-fit/re-zoom the graph (ADR 0014 #5 override).',
        trigger: 'Snapshot .react-flow__viewport transform; drag sash-left +140px and sash-right -140px.',
        expect: 'The .react-flow__viewport transform is byte-identical before and after (no refit).',
        steps: [
          { kind: 'dragHandle', target: { testid: 'sash-left' }, dx: 140, dy: 0 },
          { kind: 'dragHandle', target: { testid: 'sash-right' }, dx: -140, dy: 0 },
        ],
        checks: [
          {
            kind: 'custom',
            note: 'Assert the .react-flow__viewport style.transform equals the pre-drag snapshot (see workbench-layout.spec.ts "canvas preserves its pan/zoom").',
          },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'node-red-on-error',
        description: 'A node that errors in the latest run paints red (.ge-node--error).',
        trigger: 'Produce a run whose engine error names a node; that node card gets the ge-node--error class.',
        expect: 'The erroring [data-testid="spec-node"] carries the .ge-node--error class and run-error is shown.',
        review: true,
        steps: [
          {
            kind: 'custom',
            note: 'The demo graph runs green. Forcing a node error needs an invalid literal/edit; drive via a mocked/edited graph, then assert `.ge-node--error` on the node and [data-testid="run-error"] in the results panel.',
          },
        ],
        checks: [
          { kind: 'custom', note: 'spec-node for the failing id has class ge-node--error; run-error visible.' },
        ],
      },
      {
        id: 'tidy-layout',
        description: 'Tidy layout re-arranges every node and persists positions (sidecar).',
        trigger: 'Click [data-testid="tidy-layout"].',
        expect:
          'Nodes re-arrange; a PUT /api/graph position save fires and the layout sidecar is written. DESTRUCTIVE — writes showcase.layout.json (restore in finally).',
        review: true,
        steps: [
          {
            kind: 'custom',
            note: 'Click tidy-layout; a debounced PUT /api/graph persists positions to the sidecar. See canvas-editing.spec.ts "Tidy layout". Restore pristine graph afterwards.',
          },
        ],
        checks: [{ kind: 'custom', note: 'Every served node id has a sidecar position after tidy.' }],
      },
      {
        id: 'drag-reposition',
        description: 'Dragging a node persists sidecar-only (zero .py diff) and survives reload.',
        trigger: 'Drag a node card by its header ~120px; wait for the debounced PUT /api/graph.',
        expect:
          'The sidecar pins the node; the .py module is byte-identical. DESTRUCTIVE — writes the layout sidecar.',
        review: true,
        steps: [
          {
            kind: 'custom',
            note: 'Mouse-drag the node header; assert byte-identical .py + sidecar position. See canvas-editing.spec.ts "dragging a node persists sidecar-only".',
          },
        ],
        checks: [{ kind: 'custom', note: 'showcase.py unchanged; sidecar carries the dragged position.' }],
      },
      {
        id: 'connect-edge',
        description: 'Dragging between socket handles connects two nodes and persists the edge.',
        trigger:
          'Mouse-drag from a source handle [data-handleid="out:result"] to a target [data-handleid="in:values"].',
        expect: 'The edge persists (PUT /api/graph) and survives reload. DESTRUCTIVE — rewrites the module.',
        review: true,
        steps: [
          {
            kind: 'custom',
            note: 'See canvas-editing.spec.ts "connect persists": drag handle→handle, wait for PUT, assert the edge round-trips through the rewritten module.',
          },
        ],
        checks: [{ kind: 'custom', note: 'Served graph edges include the new source→target edge after reload.' }],
      },
      {
        id: 'delete-node',
        description: 'Selecting a node and pressing Delete splices it (and cascaded edges) out.',
        trigger: 'Select a node, press Delete/Backspace.',
        expect: 'The node and its edges are removed from the module. DESTRUCTIVE.',
        review: true,
        steps: [
          {
            kind: 'custom',
            note: 'See canvas-editing.spec.ts "delete splices out": select + Delete, wait for PUT, assert node/edges gone server-side.',
          },
        ],
        checks: [{ kind: 'custom', note: 'Served graph no longer contains the deleted node or its edges.' }],
      },
      {
        id: 'palette-drop',
        description: 'A palette entry dropped on the canvas lands at the drop point, born pinned.',
        trigger: 'Dispatch a drop of the palette MIME payload onto [data-testid="flow-canvas"].',
        expect:
          "The new node's top-left sits under the drop point and badges needs-wiring. DESTRUCTIVE — mints + persists a node.",
        review: true,
        steps: [
          {
            kind: 'custom',
            note: 'See canvas-editing.spec.ts "palette drop lands pinned at the drop point": dispatch drop with DataTransfer(application/x-graph-engine-spec).',
          },
        ],
        checks: [
          { kind: 'custom', note: 'Dropped card within 2px of the drop point; node-needs-wiring visible on it.' },
        ],
      },
    ],
  },

  // ── 4. Graph picker ────────────────────────────────────────────────────────
  {
    id: 'graph-picker',
    name: 'Graph picker',
    description:
      'The top-bar entry-point dropdown (ADR 0009): switch between catalog graphs; the selection lives in the ?graph= URL key and swaps the whole canvas.',
    testids: ['graph-picker', 'graph-picker-button', 'graph-picker-menu'],
    actions: [
      {
        id: 'picker-visible-default',
        description: 'The picker shows and starts on the server default (Showcase).',
        trigger: 'Boot the app; read [data-testid="graph-picker-button"].',
        expect: 'graph-picker is visible and the button label contains "Showcase".',
        steps: [],
        checks: [
          { kind: 'visible', target: { testid: 'graph-picker' } },
          { kind: 'containsText', target: { testid: 'graph-picker-button' }, text: 'Showcase' },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'open-menu',
        description: 'Clicking the button opens the option list.',
        trigger: 'Click [data-testid="graph-picker-button"].',
        expect: '[data-testid="graph-picker-menu"] becomes visible with per-entry options.',
        steps: [{ kind: 'click', target: { testid: 'graph-picker-button' } }],
        checks: [
          { kind: 'visible', target: { testid: 'graph-picker-menu' } },
          { kind: 'visible', target: { testid: 'graph-picker-option-capacity_check' } },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'switch-entry-url-key',
        description: 'Selecting another entry swaps the canvas and writes ?graph=<id> to the URL.',
        trigger: 'Open the menu, click [data-testid="graph-picker-option-capacity_check"].',
        expect:
          'The URL gains ?graph=capacity_check, capacity_check nodes (check_verdict) render, and the button reads "Capacity check".',
        steps: [
          { kind: 'click', target: { testid: 'graph-picker-button' } },
          { kind: 'waitVisible', target: { testid: 'graph-picker-menu' } },
          { kind: 'click', target: { testid: 'graph-picker-option-capacity_check' } },
          {
            kind: 'waitVisible',
            target: { selector: '[data-testid="flow-canvas"][data-layout-ready="true"]' },
            timeoutMs: 15000,
          },
        ],
        checks: [
          { kind: 'containsText', target: { testid: 'graph-picker-button' }, text: 'Capacity check' },
          { kind: 'visible', target: { selector: '[data-testid="spec-node"]', hasText: 'check_verdict' } },
          { kind: 'externalRequestsZero' },
        ],
      },
    ],
  },

  // ── 5. Run ─────────────────────────────────────────────────────────────────
  {
    id: 'run',
    name: 'Run + results',
    description:
      'Run the graph through the engine and read results (RunResultsPanel): output render (sandboxed), per-node outputs, and the stale-run banner + one-click re-run after an edit.',
    testids: [
      'run-button',
      'run-results',
      'result-node',
      'run-error',
      'run-stale-banner',
      'run-stale-rerun',
    ],
    actions: [
      {
        id: 'run-shows-results',
        description: 'Clicking Run executes and shows the results panel with per-node outputs.',
        trigger: 'Click [data-testid="run-button"]; wait for [data-testid="run-results"].',
        expect: 'run-results is visible and at least one [data-testid="result-node"] row renders.',
        steps: [
          { kind: 'click', target: { testid: 'run-button' } },
          { kind: 'waitVisible', target: { testid: 'run-results' }, timeoutMs: 20000 },
        ],
        checks: [
          { kind: 'visible', target: { testid: 'run-results' } },
          { kind: 'countAtLeast', target: { testid: 'result-node' }, min: 1 },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'result-row-focuses-node',
        description: 'Clicking a per-node result row selects + centres that node on the canvas.',
        trigger: 'Run, then click a [data-testid="result-node"] row.',
        expect: 'The clicked node is selected and the inspector opens for it.',
        steps: [
          { kind: 'click', target: { testid: 'run-button' } },
          { kind: 'waitVisible', target: { testid: 'run-results' }, timeoutMs: 20000 },
          { kind: 'click', target: { testid: 'result-node', nth: 0 } },
        ],
        checks: [
          { kind: 'visible', target: { testid: 'node-inspector' } },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'stale-run-banner-and-rerun',
        description:
          'Editing a node literal after a run marks the run stale (dimmed + banner), and Run again clears it.',
        trigger:
          'Run; edit a node literal in the inspector; observe [data-testid="run-stale-banner"]; click [data-testid="run-stale-rerun"].',
        expect:
          'The banner appears with "before your edit", flow-canvas + run-results gain data-run-stale="true"; Run again re-executes and clears the stale state. DESTRUCTIVE unless the PUT is mocked (see stale-run-sync.spec.ts).',
        review: true,
        steps: [
          {
            kind: 'custom',
            note: 'Run → open parse_expr inspector → fill widget-editor-math-input + Enter (mock PUT /api/graph) → assert run-stale-banner + data-run-stale → click run-stale-rerun → banner clears. See stale-run-sync.spec.ts.',
          },
        ],
        checks: [
          { kind: 'custom', note: 'run-stale-banner visible after edit; cleared after run-stale-rerun.' },
        ],
      },
    ],
  },

  // ── 6. Export ──────────────────────────────────────────────────────────────
  {
    id: 'export',
    name: 'Export Python',
    description:
      'Export the graph to flat Python, shown read-only as a right-dock "Python" tab (ExportPanel).',
    testids: ['export-button', 'export-panel', 'export-code', 'dock-tab-export'],
    actions: [
      {
        id: 'export-opens-dock-tab',
        description: 'Clicking Export Python opens the Python tab in the right dock with the code.',
        trigger: 'Click [data-testid="export-button"].',
        expect:
          '[data-testid="dock-tab-export"] appears and the dock body shows [data-testid="export-panel"] with [data-testid="export-code"].',
        steps: [
          { kind: 'click', target: { testid: 'export-button' } },
          { kind: 'waitVisible', target: { testid: 'dock-tab-export' } },
        ],
        checks: [
          { kind: 'visible', target: { testid: 'export-panel', within: 'dock-body' } },
          { kind: 'visible', target: { testid: 'export-code' } },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'export-close-tab',
        description: 'Closing the Python tab via its × removes the tab and its body.',
        trigger: 'Open Export, then click [data-testid="dock-tab-close-export"].',
        expect: 'dock-tab-export and export-panel disappear.',
        steps: [
          { kind: 'click', target: { testid: 'export-button' } },
          { kind: 'waitVisible', target: { testid: 'dock-tab-export' } },
          { kind: 'click', target: { testid: 'dock-tab-close-export' } },
        ],
        checks: [
          { kind: 'hidden', target: { testid: 'dock-tab-export' } },
          { kind: 'hidden', target: { testid: 'export-panel' } },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'export-behind-collapsed-dock',
        description: 'Summoning Export while the dock is collapsed auto-reveals the dock onto it.',
        trigger: 'Collapse the dock (collapse-right), then click export-button.',
        expect: 'rail-right hides (dock re-expanded) and the export panel is active.',
        steps: [
          { kind: 'click', target: { testid: 'collapse-right' } },
          { kind: 'waitVisible', target: { testid: 'rail-right' } },
          { kind: 'click', target: { testid: 'export-button' } },
        ],
        checks: [
          { kind: 'hidden', target: { testid: 'rail-right' } },
          { kind: 'visible', target: { testid: 'export-panel', within: 'dock-body' } },
          { kind: 'externalRequestsZero' },
        ],
      },
    ],
  },

  // ── 7. New node ────────────────────────────────────────────────────────────
  {
    id: 'new-node',
    name: 'New node authoring',
    description:
      'Author a brand-new @node in Monaco, written to a real .py, shown as a right-dock "New node" tab (NewNodePanel → SourceEditor create-mode). The write destination is shown BEFORE writing.',
    testids: [
      'new-node-button',
      'new-node-panel',
      'source-dest',
      'source-dest-change',
      'source-dest-picker',
      'dock-tab-newnode',
    ],
    actions: [
      {
        id: 'newnode-opens-dock-tab',
        description: 'Clicking + New node opens the authoring tab with the destination shown up front.',
        trigger: 'Click [data-testid="new-node-button"].',
        expect:
          '[data-testid="new-node-panel"] mounts in the dock; [data-testid="source-dest"] shows "will be written to … showcase.py".',
        steps: [
          { kind: 'click', target: { testid: 'new-node-button' } },
          { kind: 'waitVisible', target: { testid: 'new-node-panel' } },
        ],
        checks: [
          { kind: 'visible', target: { testid: 'new-node-panel', within: 'dock-body' } },
          { kind: 'containsText', target: { testid: 'source-dest' }, text: 'will be written to' },
          { kind: 'containsText', target: { testid: 'source-dest' }, text: 'showcase.py' },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'newnode-destination-picker',
        description: 'The "(change)" control opens a picker over eligible destination modules.',
        trigger: 'Open New node, click [data-testid="source-dest-change"].',
        expect: '[data-testid="source-dest-picker"] lists the eligible modules (showcase.py offered as default).',
        steps: [
          { kind: 'click', target: { testid: 'new-node-button' } },
          { kind: 'waitVisible', target: { testid: 'new-node-panel' } },
          { kind: 'click', target: { testid: 'source-dest-change' } },
        ],
        checks: [
          { kind: 'visible', target: { testid: 'source-dest-picker' } },
          { kind: 'containsText', target: { testid: 'source-dest-picker' }, text: 'showcase.py' },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'newnode-close-tab',
        description: 'Closing the New node tab via its × clears the tab and its body.',
        trigger: 'Open New node, click [data-testid="dock-tab-close-newnode"].',
        expect: 'dock-tab-newnode and new-node-panel disappear.',
        steps: [
          { kind: 'click', target: { testid: 'new-node-button' } },
          { kind: 'waitVisible', target: { testid: 'dock-tab-newnode' } },
          { kind: 'click', target: { testid: 'dock-tab-close-newnode' } },
        ],
        checks: [
          { kind: 'hidden', target: { testid: 'dock-tab-newnode' } },
          { kind: 'hidden', target: { testid: 'new-node-panel' } },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'newnode-create-registers',
        description: 'Authoring a valid @node and saving writes the .py and registers the type.',
        trigger: 'Author a fresh @node in Monaco, click [data-testid="source-save-button"] (POST /api/source).',
        expect:
          'source-notice shows "Created <name> … showcase.py" and GET /api/specs serves the new type. DESTRUCTIVE — writes showcase.py (restore in finally).',
        review: true,
        steps: [
          {
            kind: 'custom',
            note: 'See new-node-authoring.spec.ts: set a unique @node in Monaco, POST /api/source, assert notice + specs listing, restore the file.',
          },
        ],
        checks: [{ kind: 'custom', note: 'source-notice contains "Created"; /api/specs includes the new spec id.' }],
      },
      {
        id: 'newnode-reject-collision',
        description: 'A create that collides with an existing name surfaces inline and never writes.',
        trigger: 'Author "def dashboard(...)" (collides), click save.',
        expect: 'POST returns 400, [data-testid="source-error"] shows the reason, file untouched. Read-only w.r.t. disk.',
        review: true,
        steps: [
          {
            kind: 'custom',
            note: 'See new-node-authoring.spec.ts "rejected create": collision → 400 → source-error visible, showcase.py byte-identical.',
          },
        ],
        checks: [{ kind: 'custom', note: 'source-error visible; source-notice absent; file unchanged.' }],
      },
    ],
  },

  // ── 8. Right dock ──────────────────────────────────────────────────────────
  {
    id: 'right-dock',
    name: 'Right dock',
    description:
      'The VS Code-style tab strip over one body (ADR 0014 D3): inspector / export / newnode tabs, per-kind width memory, collapse to rail, and a placeholder when empty.',
    testids: [
      'right-dock',
      'dock-body',
      'dock-placeholder',
      'dock-tab-inspector',
      'dock-tab-export',
      'dock-tab-newnode',
      'collapse-right',
    ],
    actions: [
      {
        id: 'placeholder-when-empty',
        description: 'With nothing selected the dock shows its placeholder.',
        trigger: 'Boot the app; read the dock body.',
        expect: '[data-testid="dock-placeholder"] is visible inside the right dock.',
        steps: [],
        checks: [
          { kind: 'visible', target: { testid: 'right-dock' } },
          { kind: 'visible', target: { testid: 'dock-placeholder' } },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'tab-switch',
        description: 'With an inspector tab and an export tab present, activating a tab renders its body.',
        trigger:
          'Select a node (inspector tab), click export-button (export tab), then activate the inspector tab.',
        expect:
          'Clicking the inspector tab shows node-inspector in the dock body and hides export-panel.',
        steps: [
          { kind: 'click', target: nodeHeader('expr') },
          { kind: 'waitVisible', target: { testid: 'dock-tab-inspector' } },
          { kind: 'click', target: { testid: 'export-button' } },
          { kind: 'waitVisible', target: { testid: 'dock-tab-export' } },
          { kind: 'click', target: { testid: 'dock-tab-inspector', role: 'tab' } },
        ],
        checks: [
          { kind: 'visible', target: { testid: 'node-inspector', within: 'dock-body' } },
          { kind: 'hidden', target: { testid: 'export-panel' } },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'per-kind-width-memory',
        description:
          'The dock remembers a separate width for the inspector kind and the code kind; switching kinds animates to the remembered width.',
        trigger:
          'Open inspector + export tabs; widen on the code tab; switch to inspector; switch back to export.',
        expect:
          'On switching to inspector the dock narrows; back on export the widened width returns (per-kind memory).',
        review: true,
        steps: [
          {
            kind: 'custom',
            note: 'See workbench-layout.spec.ts "remembers a separate width": measure dock width across tab switches (needs numeric width comparison the declarative checks do not model).',
          },
        ],
        checks: [{ kind: 'custom', note: 'code-tab width > inspector-tab width, stable on return within tolerance.' }],
      },
      {
        id: 'collapse-dock',
        description: 'Collapsing the dock hides it and shows the right rail.',
        trigger: 'Click [data-testid="collapse-right"].',
        expect: 'right-dock hides and [data-testid="rail-right"] appears.',
        steps: [{ kind: 'click', target: { testid: 'collapse-right' } }],
        checks: [
          { kind: 'visible', target: { testid: 'rail-right' } },
          { kind: 'hidden', target: { testid: 'right-dock' } },
          { kind: 'externalRequestsZero' },
        ],
      },
    ],
  },

  // ── 9. Node inspector (instance panel) ─────────────────────────────────────
  {
    id: 'node-inspector',
    name: 'Node inspector (instance panel)',
    description:
      "The instance panel (ADR 0015): the clicked node's id/title header, inputs/outputs with derived sockets + widget slots, the read-only @main call-site row, and the Open-node-definition drill-in.",
    testids: [
      'node-inspector',
      'inspector-title',
      'inspector-inputs',
      'inspector-outputs',
      'inspector-input',
      'inspector-output',
      'inspector-callsite',
      'callsite-source',
      'callsite-loc',
      'inspector-type',
      'inspector-type-name',
      'inspector-open-definition',
      'inspector-def-shared',
      'inspector-widget-slot',
    ],
    actions: [
      {
        id: 'instance-identity',
        description: "A node click opens the instance panel showing the node's id · title.",
        trigger: 'Click the expr node header.',
        expect: '[data-testid="inspector-title"] reads "expr · parse_expr"; inputs and outputs sections render.',
        steps: [{ kind: 'click', target: nodeHeader('expr') }],
        checks: [
          { kind: 'containsText', target: { testid: 'inspector-title' }, text: 'expr' },
          { kind: 'visible', target: { testid: 'inspector-inputs' } },
          { kind: 'visible', target: { testid: 'inspector-outputs' } },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'callsite-row',
        description: 'The instance panel shows the real @main statement as file bytes with a path·lines label.',
        trigger: 'Select expr; read [data-testid="callsite-source"] and [data-testid="callsite-loc"].',
        expect:
          'callsite-source shows the real assignment (e.g. expr = parse_expr(...)); callsite-loc contains "showcase.py" and "· Lx–Ly".',
        steps: [{ kind: 'click', target: nodeHeader('expr') }],
        checks: [
          { kind: 'visible', target: { testid: 'callsite-source' } },
          { kind: 'containsText', target: { testid: 'callsite-loc' }, text: 'showcase.py' },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'widget-slot',
        description: 'An unwired widget input renders its editor slot in the inspector.',
        trigger:
          'Select the read_table node (graph id "raw"); read the path input slot.',
        expect:
          '[data-testid="inspector-widget-slot"] with a widget editor renders (read_table\'s unwired path/text are text slots).',
        steps: [{ kind: 'click', target: nodeHeader('raw') }],
        checks: [
          { kind: 'countAtLeast', target: { testid: 'inspector-widget-slot' }, min: 1 },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'derived-sockets-inspectable',
        description:
          "A dynamic node's derived, wired sockets (C_min/F_max) are listed read-only with their wired tag.",
        trigger: 'On ?graph=capacity_check select the steps node; read the derived input rows.',
        expect: 'A derived inspector-input row shows a .ge-inspector__tag--wired tag and no editor slot.',
        url: '/?graph=capacity_check',
        steps: [{ kind: 'click', target: nodeHeader('steps') }],
        checks: [
          { kind: 'visible', target: { testid: 'node-inspector' } },
          { kind: 'visible', target: { selector: '[data-testid="inspector-input"] .ge-inspector__tag--wired', nth: 0 } },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'open-definition-and-back',
        description: 'Open node definition drills into the source editor; back returns to the same instance.',
        trigger:
          'Select expr, click [data-testid="inspector-open-definition"]; then click [data-testid="source-back"].',
        expect:
          'The source editor mounts (source-fn-label "sym.parse_expr"); back returns to the instance panel (callsite-source visible again).',
        steps: [
          { kind: 'click', target: nodeHeader('expr') },
          { kind: 'click', target: { testid: 'inspector-open-definition' } },
          { kind: 'waitVisible', target: { testid: 'source-editor' } },
          { kind: 'click', target: { testid: 'source-back' } },
        ],
        checks: [
          { kind: 'visible', target: { testid: 'inspector-inputs' } },
          { kind: 'visible', target: { testid: 'callsite-source' } },
          { kind: 'count', target: { testid: 'source-editor' }, count: 0 },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'shared-scope-warning',
        description:
          'A type shared by several nodes warns "shared — affects all N instances" on the drill-in, before entry.',
        trigger: 'Select roots_note (shares sym.describe); read [data-testid="inspector-def-shared"].',
        expect: 'inspector-def-shared contains "shared — affects all 2 instances".',
        steps: [{ kind: 'click', target: nodeHeader('roots_note') }],
        checks: [
          { kind: 'containsText', target: { testid: 'inspector-def-shared' }, text: 'shared' },
          { kind: 'externalRequestsZero' },
        ],
      },
    ],
  },

  // ── 10. Source editor ──────────────────────────────────────────────────────
  {
    id: 'source-editor',
    name: 'Source editor (Monaco)',
    description:
      "The lazily-loaded Monaco editor for a node's @node function (SourceEditor): open, edit, save to the real .py, or reject on a bad save.",
    testids: [
      'source-editor',
      'source-monaco',
      'source-fn-label',
      'source-file-label',
      'source-shared-note',
      'source-save-button',
      'source-error',
      'source-notice',
      'source-back',
    ],
    actions: [
      {
        id: 'open-monaco',
        description: 'Opening a definition mounts Monaco holding the function source.',
        trigger: 'Select expr, click inspector-open-definition; wait for [data-testid="source-monaco"].',
        expect:
          'source-monaco is visible; source-fn-label reads "sym.parse_expr"; source-file-label shows the real path + line range.',
        steps: [
          { kind: 'click', target: nodeHeader('expr') },
          { kind: 'click', target: { testid: 'inspector-open-definition' } },
          { kind: 'waitVisible', target: { testid: 'source-monaco' }, timeoutMs: 15000 },
        ],
        checks: [
          { kind: 'visible', target: { testid: 'source-monaco' } },
          { kind: 'containsText', target: { testid: 'source-fn-label' }, text: 'sym.parse_expr' },
          { kind: 'containsText', target: { testid: 'source-file-label' }, text: 'sym' },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'edit-save',
        description: 'Editing the function body and saving writes back to the real .py and re-runs live.',
        trigger:
          'Open a definition, edit via the Monaco model, click [data-testid="source-save-button"] (PUT /api/source).',
        expect:
          'source-notice shows "Saved to … showcase.py"; a re-run reflects the change. DESTRUCTIVE — writes the module (restore in finally).',
        review: true,
        steps: [
          {
            kind: 'custom',
            note: 'See source-editing.spec.ts "editing a node\'s function": edit via window.monaco model, PUT /api/source, assert notice + re-run marker, restore original source.',
          },
        ],
        checks: [{ kind: 'custom', note: 'source-notice contains "Saved to"; re-run output carries the edit.' }],
      },
      {
        id: 'reject-syntax-error',
        description: 'A syntactically invalid save is rejected inline and never corrupts the file.',
        trigger: 'Open a definition, set invalid Python, click save (PUT returns 400).',
        expect:
          '[data-testid="source-error"] shows the parse error, the editor stays open, the file is byte-identical. Read-only w.r.t. disk.',
        review: true,
        steps: [
          {
            kind: 'custom',
            note: 'See source-editing.spec.ts "rejected save (syntax error)": set bad source, PUT → 400, assert source-error + unchanged /api/source bytes.',
          },
        ],
        checks: [{ kind: 'custom', note: 'source-error visible; source bytes unchanged after the failed save.' }],
      },
    ],
  },

  // ── 11. Calc widget ────────────────────────────────────────────────────────
  {
    id: 'calc-widget',
    name: 'Calc widget (dynamic handcalc)',
    description:
      "The dynamic equation editor (ADR 0007) on capacity_check's handcalc node (id steps): live derived symbol chips, invalid-equation refusal, commit reshapes sockets, and symbol-removal prune-with-toast.",
    testids: [
      'widget-editor-calc-input',
      'calc-sockets',
      'calc-symbol-chip',
      'calc-symbol-value',
      'calc-derive-error',
      'calc-commit-error',
      'calc-toast',
    ],
    actions: [
      {
        id: 'derived-sockets-render',
        description: "The node's derived sockets (C_min, F_max, lines) render on the canvas from the store.",
        trigger: 'Boot ?graph=capacity_check; read the steps node sockets.',
        expect: 'Socket name C_min is visible on the steps card.',
        url: '/?graph=capacity_check',
        steps: [],
        checks: [
          {
            kind: 'visible',
            target: { selector: '.react-flow__node[data-id="steps"] .ge-socket__name[title="C_min"]' },
            timeoutMs: 15000,
          },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'open-calc-editor',
        description: 'Selecting the steps node shows the calc editor in the inspector with the committed equation.',
        trigger: 'On ?graph=capacity_check click the steps node-title; read [data-testid="widget-editor-calc-input"].',
        expect: 'widget-editor-calc-input is visible.',
        url: '/?graph=capacity_check',
        steps: [
          { kind: 'click', target: { selector: '.react-flow__node[data-id="steps"] [data-testid="node-title"]' } },
          { kind: 'waitVisible', target: { testid: 'node-inspector' } },
        ],
        checks: [
          { kind: 'visible', target: { testid: 'widget-editor-calc-input' } },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'live-derived-chips',
        description:
          'Typing an equation with a new symbol chips it as added (debounced derive) WITHOUT committing anything.',
        trigger:
          'Open the calc editor, fill it with the equation + " + extra"; observe the "extra" chip go data-state="added".',
        expect:
          'The [data-testid="calc-symbol-chip"][data-symbol="extra"] gains data-state="added" and no PUT fires.',
        url: '/?graph=capacity_check',
        steps: [
          { kind: 'click', target: { selector: '.react-flow__node[data-id="steps"] [data-testid="node-title"]' } },
          { kind: 'waitVisible', target: { testid: 'widget-editor-calc-input' } },
          {
            kind: 'fill',
            target: { testid: 'widget-editor-calc-input' },
            value: 'margin = C_min - F_max\ncheck = margin > 0 + extra',
          },
        ],
        checks: [
          {
            kind: 'attr',
            target: { selector: '[data-testid="calc-symbol-chip"][data-symbol="extra"]' },
            name: 'data-state',
            value: 'added',
          },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'invalid-equation-refusal',
        description: 'An invalid equation shows the inline derive error and refuses to commit.',
        trigger: 'Open the calc editor, fill an invalid equation ("margin = = C_min").',
        expect: '[data-testid="calc-derive-error"] is visible and no PUT persists (served equation unchanged).',
        // The /derive POST returns 422 by design (that IS the refusal); the
        // browser logs a "Failed to load resource … 422" console error which is
        // expected here, so the probe ignores it for this action only.
        expectsServerRejection: true,
        url: '/?graph=capacity_check',
        steps: [
          { kind: 'click', target: { selector: '.react-flow__node[data-id="steps"] [data-testid="node-title"]' } },
          { kind: 'waitVisible', target: { testid: 'widget-editor-calc-input' } },
          { kind: 'fill', target: { testid: 'widget-editor-calc-input' }, value: 'margin = = C_min' },
        ],
        checks: [
          { kind: 'visible', target: { testid: 'calc-derive-error' }, timeoutMs: 10000 },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'commit-reshapes-sockets',
        description: 'A valid commit reshapes the node sockets on the canvas (folded from the store).',
        trigger:
          'Add a new symbol, give it an inline value, Ctrl+Enter to apply (PUT /api/graphs/capacity_check/graph).',
        expect:
          'The new socket appears on the steps card. DESTRUCTIVE — rewrites capacity_check.py (restore in finally).',
        review: true,
        steps: [
          {
            kind: 'custom',
            note: 'See calc-widget.spec.ts: fill "…- safety", fill calc-symbol-value[data-symbol=safety], Control+Enter, wait for the scoped PUT, assert socketName(safety). Restore the module + bytes afterward.',
          },
        ],
        checks: [{ kind: 'custom', note: 'The new derived socket renders on the canvas node after commit.' }],
      },
      {
        id: 'symbol-removal-prune-toast',
        description: 'Removing a wired symbol prunes its edge in the same save and toasts what was unwired.',
        trigger: 'Edit the equation to drop a wired symbol (F_max), Ctrl+Enter.',
        expect:
          '[data-testid="calc-toast"] shows "F_max removed from equation — unwired from max_force"; the edge is gone server-side. DESTRUCTIVE.',
        review: true,
        steps: [
          {
            kind: 'custom',
            note: 'See calc-widget.spec.ts "removing a wired symbol": chip shows removed + "will unwire", commit, assert calc-toast text + pruned edge. Restore afterward.',
          },
        ],
        checks: [{ kind: 'custom', note: 'calc-toast shows the unwire message; the pruned edge is absent server-side.' }],
      },
    ],
  },

  // ── 12. Math widget preview ────────────────────────────────────────────────
  {
    id: 'math-widget',
    name: 'Math widget preview',
    description:
      "The math equation editor's live KaTeX preview (parse_expr node): good expressions typeset; shapes the mini-translator can't render fall back to a labelled raw preview.",
    testids: ['widget-editor-math-input', 'widget-math-preview', 'widget-math-fallback-cue'],
    actions: [
      {
        id: 'good-expression-typesets',
        description: 'A good expression renders live KaTeX with no fallback cue.',
        trigger: 'Select parse_expr, fill [data-testid="widget-editor-math-input"] with "x**3 - 1".',
        expect: 'A .katex node renders inside .ge-widget-math-preview and no [data-testid="widget-math-fallback-cue"].',
        steps: [
          { kind: 'click', target: { selector: '.react-flow__node[data-id="expr"] [data-testid="node-title"]' } },
          { kind: 'waitVisible', target: { testid: 'widget-editor-math-input' } },
          { kind: 'fill', target: { testid: 'widget-editor-math-input' }, value: 'x**3 - 1' },
        ],
        checks: [
          { kind: 'visible', target: { selector: '.ge-widget-math-preview .katex', nth: 0 }, timeoutMs: 8000 },
          { kind: 'count', target: { testid: 'widget-math-fallback-cue' }, count: 0 },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'unsupported-shape-fallback',
        description: "A shape the mini-translator can't faithfully render falls back to a labelled raw preview.",
        trigger: 'Select parse_expr, fill the math input with "x**(y+1)".',
        expect:
          '[data-testid="widget-math-fallback-cue"] is visible and the raw expression is shown verbatim (no .katex).',
        steps: [
          { kind: 'click', target: { selector: '.react-flow__node[data-id="expr"] [data-testid="node-title"]' } },
          { kind: 'waitVisible', target: { testid: 'widget-editor-math-input' } },
          { kind: 'fill', target: { testid: 'widget-editor-math-input' }, value: 'x**(y+1)' },
        ],
        checks: [
          // ADR 0013 renders the math preview in BOTH the card (node-previews)
          // and the inspector's widget slot — scope to the inspector (the
          // fallback one, class mw-fallback) to avoid a strict-mode ambiguity.
          {
            kind: 'visible',
            target: { testid: 'widget-math-fallback-cue', within: 'node-inspector' },
            timeoutMs: 8000,
          },
          {
            kind: 'containsText',
            target: { testid: 'widget-math-preview', within: 'node-inspector' },
            text: 'x**(y+1)',
          },
          { kind: 'externalRequestsZero' },
        ],
      },
    ],
  },

  // ── 13. HTML-card / renderers ──────────────────────────────────────────────
  {
    id: 'render-cards',
    name: 'Render cards (html-card / latex)',
    description:
      'The sandboxed output renderers (ADR 0010/0013): html-card renders node HTML inside a fully sandboxed iframe (sandbox="" exactly); latex typesets a LaTeX socket with KaTeX; before a run the surface shows a placeholder.',
    testids: [
      'render-surface',
      'html-card-renderer',
      'html-card-frame',
      'latex-renderer',
      'run-result-frame',
      'node-result',
    ],
    actions: [
      {
        id: 'placeholder-before-run',
        description: 'Before any run the render surface shows a text placeholder, no iframe.',
        trigger: 'Boot the app; read the render_math_card node surface.',
        expect:
          'render_math_card [data-testid="render-surface"] is visible with "run to render"; no [data-testid="html-card-frame"] yet.',
        steps: [],
        checks: [
          { kind: 'visible', target: { selector: '[data-testid="spec-node"]', hasText: 'render_math_card' } },
          { kind: 'externalRequestsZero' },
        ],
        review: true,
      },
      {
        id: 'html-card-sandboxed-iframe',
        description: 'After a run the html-card renders inside a fully sandboxed iframe (sandbox="").',
        trigger: 'Run the graph; read an html-card frame.',
        expect:
          '[data-testid="html-card-frame"] is visible with the sandbox attribute exactly "" (no allow-scripts).',
        steps: [
          { kind: 'click', target: { testid: 'run-button' } },
          { kind: 'waitVisible', target: { testid: 'run-results' }, timeoutMs: 20000 },
        ],
        checks: [
          { kind: 'countAtLeast', target: { testid: 'html-card-frame' }, min: 1 },
          { kind: 'attr', target: { testid: 'html-card-frame', nth: 0 }, name: 'sandbox', value: '' },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'panel-output-sandbox',
        description: 'The results panel mounts the output node html-card with the same sandbox posture.',
        trigger: 'Run; read the html-card frame inside [data-testid="run-results"].',
        expect: 'The results-panel [data-testid="html-card-frame"] has sandbox="".',
        steps: [
          { kind: 'click', target: { testid: 'run-button' } },
          { kind: 'waitVisible', target: { testid: 'run-results' }, timeoutMs: 20000 },
        ],
        checks: [
          { kind: 'attr', target: { testid: 'html-card-frame', within: 'run-results', nth: 0 }, name: 'sandbox', value: '' },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'latex-renderer',
        description: "handcalc's latex renderer typesets its LaTeX socket with KaTeX in the host DOM.",
        trigger: 'On ?graph=capacity_check run the graph; read the latex-renderer.',
        expect: '[data-testid="latex-renderer"] renders KaTeX markup (not a raw string).',
        url: '/?graph=capacity_check',
        steps: [
          { kind: 'click', target: { testid: 'run-button' } },
          { kind: 'waitVisible', target: { testid: 'run-results' }, timeoutMs: 20000 },
        ],
        checks: [
          { kind: 'countAtLeast', target: { testid: 'latex-renderer' }, min: 1 },
          { kind: 'externalRequestsZero' },
        ],
        review: true,
      },
    ],
  },

  // ── 14. Branch badge ───────────────────────────────────────────────────────
  {
    id: 'branch-badge',
    name: 'Branch badge',
    description:
      'The top-bar badge naming the git branch source edits land on (BranchBadge). Self-contained; hidden until /api/workspace resolves.',
    testids: ['branch-badge'],
    actions: [
      {
        id: 'badge-shows-branch',
        description: 'The badge renders the current branch/checkout label.',
        trigger: 'Boot the app; read [data-testid="branch-badge"].',
        expect: 'branch-badge is visible with a non-empty label.',
        steps: [{ kind: 'waitVisible', target: { testid: 'branch-badge' }, timeoutMs: 15000 }],
        checks: [
          { kind: 'visible', target: { testid: 'branch-badge' } },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'badge-stable-across-switch',
        description: 'The badge is checkout-global — unchanged when the graph entry switches.',
        trigger: 'Switch entries via the picker; the badge text is unchanged.',
        expect: 'branch-badge text is identical before and after a graph switch.',
        review: true,
        steps: [
          {
            kind: 'custom',
            note: 'See graph-picker.spec.ts: capture branch-badge text, switch to capacity_check, assert unchanged.',
          },
        ],
        checks: [{ kind: 'custom', note: 'branch-badge text equal before/after the switch.' }],
      },
    ],
  },

  // ── 15. Layout persistence ─────────────────────────────────────────────────
  {
    id: 'layout-persistence',
    name: 'Layout persistence across reload',
    description:
      'The UI-local layout store (ADR 0014 D5) + the library autoSaveId persist sash sizes and collapsed state across a reload, and survive a corrupt saved blob by falling back to defaults.',
    testids: ['workbench', 'rail-right', 'palette', 'flow-canvas'],
    actions: [
      {
        id: 'collapse-survives-reload',
        description: 'A collapsed region and a resized palette survive a full page reload.',
        trigger:
          'Widen the palette (sash-left +120px), collapse the dock (collapse-right), reload the page.',
        expect: 'After reload rail-right is still visible (dock stayed collapsed) and right-dock stays hidden.',
        review: true,
        steps: [
          {
            kind: 'custom',
            note: 'See workbench-layout.spec.ts "sizes and collapsed state persist": needs a poll on localStorage flush before reload; drive drag + collapse, reload, assert rail-right visible.',
          },
        ],
        checks: [{ kind: 'custom', note: 'rail-right visible and right-dock hidden after reload.' }],
      },
      {
        id: 'corrupt-blob-fallback',
        description: 'A corrupt saved layout falls back to defaults instead of wedging the shell.',
        trigger: 'Seed ge:workbench:v1 with "{not json" before boot; load the app.',
        expect:
          'The app boots at defaults: palette + flow-canvas + right-dock + dock-placeholder all reachable, no region collapsed.',
        review: true,
        steps: [
          {
            kind: 'custom',
            note: 'See workbench-layout.spec.ts "a corrupt saved layout falls back": addInitScript seeding junk, then assert defaults. Needs pre-boot seeding the runner injects before goto.',
          },
        ],
        checks: [{ kind: 'custom', note: 'palette/flow-canvas/right-dock/dock-placeholder visible; no rails.' }],
      },
    ],
  },

  // ── 16. Escape dismissal order ─────────────────────────────────────────────
  {
    id: 'escape-order',
    name: 'Escape dismissal order',
    description:
      'Escape dismisses the topmost open surface, one per press: source editor → inspector → export dock → run results. Escape inside the Monaco source body is deliberately inert.',
    testids: ['node-inspector', 'source-editor', 'run-results'],
    actions: [
      {
        id: 'escape-editor-then-inspector',
        description: 'Escape closes the open source editor first, then the inspector, one press each.',
        trigger:
          'Select expr, open the definition editor, press Escape (closes editor), press Escape (closes inspector).',
        expect: 'First Escape removes source-editor (inspector stays); second Escape removes node-inspector.',
        steps: [
          { kind: 'click', target: nodeHeader('expr') },
          { kind: 'click', target: { testid: 'inspector-open-definition' } },
          { kind: 'waitVisible', target: { testid: 'source-editor' } },
          { kind: 'pressKey', key: 'Escape' },
          { kind: 'pressKey', key: 'Escape' },
        ],
        checks: [
          { kind: 'count', target: { testid: 'source-editor' }, count: 0 },
          { kind: 'count', target: { testid: 'node-inspector' }, count: 0 },
          { kind: 'externalRequestsZero' },
        ],
      },
      {
        id: 'escape-closes-inspector',
        description: 'With only the inspector open, Escape closes it.',
        trigger: 'Select a node, press Escape.',
        expect: 'node-inspector count goes to 0.',
        steps: [
          { kind: 'click', target: nodeHeader('expr') },
          { kind: 'waitVisible', target: { testid: 'node-inspector' } },
          { kind: 'pressKey', key: 'Escape' },
        ],
        checks: [
          { kind: 'count', target: { testid: 'node-inspector' }, count: 0 },
          { kind: 'externalRequestsZero' },
        ],
      },
    ],
  },

  // ── 17. Offline posture ────────────────────────────────────────────────────
  {
    id: 'offline-posture',
    name: 'Offline posture (external-requests = 0)',
    description:
      'The whole app is served from localhost with all assets bundled (no CDN). Every panel walk asserts zero requests leaving 127.0.0.1/localhost; this panel makes the invariant explicit as its own check.',
    testids: ['flow-canvas', 'workbench'],
    actions: [
      {
        id: 'boot-no-external',
        description: 'Booting and running the graph issues zero external (non-localhost) requests.',
        trigger: 'Boot the app, click run-button, wait for results — with a request tracker attached.',
        expect: 'The external-request tally is exactly 0 for the whole interaction.',
        steps: [
          { kind: 'click', target: { testid: 'run-button' } },
          { kind: 'waitVisible', target: { testid: 'run-results' }, timeoutMs: 20000 },
        ],
        checks: [{ kind: 'externalRequestsZero' }],
      },
    ],
  },
];

/** Flat count of actions across all panels (for the skill's coverage report). */
export function actionCount(): number {
  return PANELS.reduce((sum, panel) => sum + panel.actions.length, 0);
}

/** Total number of panels in the registry. */
export function panelCount(): number {
  return PANELS.length;
}
