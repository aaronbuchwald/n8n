import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type Ref,
} from 'react';
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesInitialized,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type IsValidConnection,
  type Node,
  type NodeMouseHandler,
  type NodeTypes,
  type OnNodeDrag,
  type OnReconnect,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { buildFlow, layoutFlowNodes, pinnedIdsOf } from './buildGraph';
import { PALETTE_SPEC_MIME } from './components/Palette';
import { SpecNode } from './components/SpecNode';
import {
  connectEdge,
  createNode,
  deleteElements,
  reconnectEdge,
  selectErrorNodeId,
  selectRunIsStale,
  setWritebackWarning,
} from './store/sync';
import { queuePositionSave } from './store/positions';
import { useSyncSelector } from './store/useSyncSelector';
import type { GraphEdge, SpecNodeData } from './types';

const nodeTypes: NodeTypes = { specNode: SpecNode };

// One framing for every "fit the graph" path (initial frame, canvas resize,
// the Controls fit button), so they all settle on the same view. Padding is
// deliberately slim: every point of fit zoom is legibility on a big graph.
const FIT_VIEW = { padding: 0.1, maxZoom: 1.05 };

function sameSet(a: Set<string>, b: Set<string>): boolean {
  return a.size === b.size && [...a].every((x) => b.has(x));
}

// The graph-shaped data fields (everything buildFlow derives, minus the run
// results the run effect owns). Used to skip no-op re-renders during the
// controlled data sync below.
function sameGraphData(a: SpecNodeData, b: SpecNodeData): boolean {
  return (
    a.spec === b.spec &&
    a.type === b.type &&
    a.isOutput === b.isOutput &&
    JSON.stringify(a.boundInputs) === JSON.stringify(b.boundInputs) &&
    sameSet(a.wiredInputs, b.wiredInputs) &&
    sameSet(a.wiredOutputs, b.wiredOutputs)
  );
}

// A per-node socket signature: the node type plus its ordered input/output
// socket NAMES (from the spec, or the wired sockets on a spec-less node). It
// changes when a write reshapes a node — a source save that alters the
// signature, or a dynamic-handcalc equation edit whose free symbols ARE the
// sockets (ADR 0007) — so such a write is treated as structural (re-measure +
// re-layout) instead of an in-place literal patch (ADR 0008 G6).
function socketSignature(data: SpecNodeData): string {
  const inputs = data.spec ? data.spec.inputs.map((i) => i.name) : [...data.wiredInputs];
  const outputs = data.spec ? data.spec.outputs.map((o) => o.name) : [...data.wiredOutputs];
  return `${data.type}(${inputs.join(',')}|${outputs.join(',')})`;
}

// A structural signature: node ids + per-node socket signatures + edge ids. It
// changes on a real topology change (add/remove node or rewire) OR a shape
// change (G6), never on a plain literal edit — which is what lets a widget
// commit reflect in place without a re-layout/re-frame.
function structureKeyOf(nodes: { id: string; data: SpecNodeData }[], edges: { id: string }[]): string {
  return JSON.stringify({
    n: nodes.map((n) => [n.id, socketSignature(n.data)]),
    e: edges.map((e) => e.id),
  });
}

// Smoothstep reads cleanly for a layered left-to-right DAG: edges leave/enter
// horizontally and take soft right-angle turns between layers.
const defaultEdgeOptions = { type: 'smoothstep' as const, pathOptions: { borderRadius: 14 } };

// Handle-id namespaces (see buildGraph.ts inHandle/outHandle).
const OUT_PREFIX = 'out:';
const IN_PREFIX = 'in:';

/**
 * Map ReactFlow connection endpoints back onto the engine's edge shape. Null
 * when the gesture didn't land on namespaced socket handles (never on a
 * spec'd node; a spec-less node's generic handles carry no socket name).
 */
function graphEdgeOf(
  source: string | null | undefined,
  sourceHandle: string | null | undefined,
  target: string | null | undefined,
  targetHandle: string | null | undefined,
): GraphEdge | null {
  if (!source || !target) return null;
  if (!sourceHandle?.startsWith(OUT_PREFIX) || !targetHandle?.startsWith(IN_PREFIX)) return null;
  return {
    source,
    sourceOutput: sourceHandle.slice(OUT_PREFIX.length),
    target,
    targetInput: targetHandle.slice(IN_PREFIX.length),
  };
}

function sameGraphEdge(a: GraphEdge, b: GraphEdge): boolean {
  return (
    a.source === b.source &&
    a.sourceOutput === b.sourceOutput &&
    a.target === b.target &&
    a.targetInput === b.targetInput
  );
}

const EMPTY_WIRING: string[] = [];

function sameStrings(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((x, i) => x === b[i]);
}

export interface FocusRequest {
  nodeId: string;
  /** Distinguishes repeated requests for the same node. */
  token: number;
}

// The imperative seam the node catalog (ADR 0017 D4) reads to insert a node at
// the visible canvas centre — the `FocusRequest` seam precedent, but a pull
// (return a value) rather than a push. Returns null when the canvas ref isn't
// mounted, so callers fall back to a blind stagger.
export interface GraphViewHandle {
  getInsertPosition: () => { x: number; y: number } | null;
}

// The canvas reads the graph, specs and run from the store via selectors (8-S1);
// it takes only the UI-interaction wiring the shell owns as props, so the App
// stays a thin, selector-driven shell (and rebases over 9-S2c / 11-W4 cheaply).
interface GraphViewProps {
  // Selection is owned by the caller so panels outside the canvas (results
  // rows, the app-level Escape handler) can drive it too.
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string | null) => void;
  // A request (e.g. from a run-results row) to select + centre a node.
  focusRequest: FocusRequest | null;
}

// mount → nodes measured → final layout applied → graph framed → visible.
type LayoutPhase = 'measuring' | 'framing' | 'ready';

function GraphCanvas({
  selectedNodeId,
  onSelectNode,
  focusRequest,
  handleRef,
}: GraphViewProps & { handleRef: Ref<GraphViewHandle> }) {
  // The single source of truth (8-S1). `effective.graph` is authoritative ⊕ the
  // optimistic overlay, so an in-flight literal edit is on the canvas instantly;
  // each of these selectors returns a stored reference or a primitive, so the
  // snapshot stays stable (the useSyncExternalStore rule).
  const graph = useSyncSelector((s) => s.effective.graph);
  const specs = useSyncSelector((s) => s.specs);
  const runOutputs = useSyncSelector((s) => s.run?.outputs ?? null);
  const runIsStale = useSyncSelector(selectRunIsStale);
  const errorNodeId = useSyncSelector(selectErrorNodeId);
  const incomplete = useSyncSelector((s) => s.incomplete);
  const writebackWarning = useSyncSelector((s) => s.writebackWarning);
  // Derived sockets per dynamic node (ADR 0007): the store's precomputed view
  // over each node's COMMITTED literal — the calc editor's draft preview never
  // reaches the canvas. Folded into node specs by buildFlow below, which makes
  // a socket-set change a structural change (socketSignature/G6): the card
  // re-measures and re-lays-out exactly like a source-save signature change.
  const derivedByNode = useSyncSelector((s) => s.derivedByNode);

  const { nodes: initialNodes, edges: initialEdges } = useMemo(
    () => (graph ? buildFlow(graph, specs, derivedByNode) : { nodes: [], edges: [] }),
    [graph, specs, derivedByNode],
  );

  // The sidecar-pinned set (HD3): nodes whose served position is authoritative.
  // The measured relayout below re-places only the rest, relative to these.
  const pinnedIds = useMemo(() => (graph ? pinnedIdsOf(graph) : new Set<string>()), [graph]);

  // Controlled state so ReactFlow can sync node dimensions back (minimap) and
  // apply drag position changes. Without change handlers both are inert.
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  const nodesInitialized = useNodesInitialized();
  const { fitView, screenToFlowPosition, getViewport, setViewport } = useReactFlow();
  const [phase, setPhase] = useState<LayoutPhase>('measuring');
  const canvasRef = useRef<HTMLDivElement>(null);
  // Latest edges for callbacks that must not re-bind per edge change.
  const edgesRef = useRef(edges);
  edgesRef.current = edges;

  // When the served graph changes after a widget commit + quiet reload, fold the
  // freshly derived node DATA (bound literals, wiring, output flag) onto the
  // existing nodes IN PLACE — preserving each node's measured size and dragged
  // position, and NOT re-running the measuring→framing→fit pipeline. A real
  // topology change (nodes added/removed or rewired) re-seeds nodes and edges —
  // but on a live, already-framed canvas it KEEPS each surviving node's current
  // geometry and the viewport (11-W4: a connect/delete/drop must not yank the
  // view or undo an in-flight drag); only the initial mount runs the full
  // measuring→framing→fit pipeline (App remounts this component per entry
  // switch, so mount === new graph). buildFlow already recomputed
  // initialNodes/initialEdges on the [graph, specs] change that triggered this.
  const structureKey = structureKeyOf(initialNodes, initialEdges);
  const structureRef = useRef(structureKey);
  useEffect(() => {
    if (structureKey === structureRef.current) {
      // Same topology: patch data only, keeping geometry and run results.
      const byId = new Map(initialNodes.map((n) => [n.id, n]));
      setNodes((current) =>
        current.map((n) => {
          const built = byId.get(n.id);
          if (!built) return n;
          const data: SpecNodeData = {
            ...built.data,
            result: n.data.result,
            hasError: n.data.hasError,
            needsWiring: n.data.needsWiring,
          };
          return sameGraphData(n.data, data) ? n : { ...n, data };
        }),
      );
      return;
    }
    structureRef.current = structureKey;
    // Structural change on a live canvas: merge fresh data/topology onto the
    // current geometry. New nodes are born at their built position (a palette
    // drop is pinned at the drop point; an auto-placed node sits near its
    // neighbours) — no re-frame, the user keeps their viewport.
    setNodes((current) => {
      const byId = new Map(current.map((n) => [n.id, n]));
      return initialNodes.map((built) => {
        const cur = byId.get(built.id);
        if (!cur) return built;
        return {
          ...built,
          position: cur.position,
          selected: cur.selected,
          measured: cur.measured,
          data: {
            ...built.data,
            result: cur.data.result,
            hasError: cur.data.hasError,
            needsWiring: cur.data.needsWiring,
          },
        };
      });
    });
    setEdges(initialEdges);
  }, [structureKey, initialNodes, initialEdges, setNodes, setEdges]);

  // The initial layout uses estimated node sizes. Once ReactFlow has measured
  // the real DOM sizes, re-run the layout with them — targeting the actual
  // canvas aspect so row wrapping keeps the fitted zoom readable — then frame
  // the whole graph. Sidecar-pinned nodes are never moved (HD3): only the
  // `position: null` remainder is re-placed around them. The canvas stays
  // invisible (CSS keyed on data-layout-ready) until framing is done, so the
  // user never sees the pre-measurement arrangement.
  useEffect(() => {
    if (phase !== 'measuring' || !nodesInitialized) return;
    const el = canvasRef.current;
    const aspect = el && el.clientHeight > 0 ? el.clientWidth / el.clientHeight : undefined;
    setNodes((current) => layoutFlowNodes(current, initialEdges, aspect, pinnedIds));
    setPhase('framing');
  }, [phase, nodesInitialized, setNodes, initialEdges, pinnedIds]);

  useEffect(() => {
    if (phase !== 'framing') return;
    // Two frames: one for React to commit the new positions, one for ReactFlow
    // to ingest them — then fitView sees the final geometry.
    let raf2 = 0;
    const raf1 = requestAnimationFrame(() => {
      raf2 = requestAnimationFrame(() => {
        void fitView(FIT_VIEW).then(() => setPhase('ready'));
      });
    });
    return () => {
      cancelAnimationFrame(raf1);
      cancelAnimationFrame(raf2);
    };
  }, [phase, fitView]);

  // Resize policy (ADR 0014 #5 override), owned by W2. On a container resize the
  // viewport is PRESERVED: a panel/sash drag reveals more/less canvas at the SAME
  // pan+zoom and must never re-fit. `fitView` stays reserved for initial mount /
  // entry-switch (the framing phase above), the Controls fit button, run-row
  // focus, and Tidy layout — never a resize. An ordinary resize needs no code:
  // ReactFlow leaves its transform in place while its own observer re-reads the
  // box. The one case it can't self-recover from is a collapse→expand round-trip
  // that drives the host to ~0px and back — ReactFlow's internal sizing can stick
  // at 0 (blank canvas / stuck zoom). This rAF-throttled observer watches for
  // exactly that transition and re-asserts the remembered viewport, forcing a
  // recompute against the restored dimensions WITHOUT touching pan or zoom (no
  // fitView). A steady, non-zero resize only refreshes the remembered viewport,
  // so the framing above and the #5 no-refit contract are both left intact.
  useEffect(() => {
    // Only watch once the initial framing has settled, so the first layout pass
    // (measuring→framing→fitView) owns the view and this never fires during it.
    if (phase !== 'ready') return;
    const host = canvasRef.current;
    if (!host) return;
    const isCollapsed = () => host.clientWidth < 1 || host.clientHeight < 1;
    // Seed from the (framed, non-zero) box and its current view.
    let wasCollapsed = isCollapsed();
    let remembered = getViewport();
    let raf = 0;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        if (!canvasRef.current) return;
        const collapsed = isCollapsed();
        if (!collapsed && wasCollapsed) {
          // Recovered from a collapse: re-apply the pre-collapse view so
          // ReactFlow re-syncs its internal dimensions. Same x/y/zoom → the
          // transform is unchanged, only the stuck sizing is nudged loose.
          setViewport(remembered);
        } else if (!collapsed) {
          // Steady resize: transform is intact; keep the remembered view fresh.
          remembered = getViewport();
        } else if (!wasCollapsed) {
          // Just collapsed: snapshot the still-intact view for the recovery.
          remembered = getViewport();
        }
        wasCollapsed = collapsed;
      });
    });
    observer.observe(host);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(raf);
    };
  }, [phase, getViewport, setViewport]);

  // The store's edit-mode validation, regrouped per node (the on-canvas
  // "needs wiring" badge source — ADR 0011 D6, mirrored from W5's palette strip).
  const needsWiringByNode = useMemo(() => {
    const byNode = new Map<string, string[]>();
    for (const warning of incomplete) {
      const inputs = byNode.get(warning.nodeId);
      if (inputs) inputs.push(warning.input);
      else byNode.set(warning.nodeId, [warning.input]);
    }
    return byNode;
  }, [incomplete]);

  // Fold the latest run's outputs + error + needs-wiring badge into each node's
  // data (positions and measured dimensions are preserved — data patch only).
  useEffect(() => {
    setNodes((current) =>
      current.map((n) => {
        const result = runOutputs ? (runOutputs[n.id] ?? null) : null;
        const hasError = errorNodeId === n.id;
        const needsWiring = needsWiringByNode.get(n.id) ?? EMPTY_WIRING;
        if (
          n.data.result === result &&
          n.data.hasError === hasError &&
          sameStrings(n.data.needsWiring, needsWiring)
        ) {
          return n;
        }
        return { ...n, data: { ...n.data, result, hasError, needsWiring } };
      }),
    );
  }, [runOutputs, errorNodeId, needsWiringByNode, setNodes]);

  // Clicking a node opens the inspector for it; clicking the pane closes it.
  // The card is read-only now (ADR 0013 D1) — every click anywhere on it,
  // previews included, selects the node. No widget-slot exclusion, no dead zone.
  const onNodeClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      onSelectNode(node.id);
    },
    [onSelectNode],
  );
  const onPaneClick = useCallback(() => onSelectNode(null), [onSelectNode]);

  // An outside surface (a run-results row) asked to focus a node: mark it
  // selected on the canvas and bring it into view at a readable zoom.
  useEffect(() => {
    if (!focusRequest) return;
    const { nodeId } = focusRequest;
    setNodes((current) =>
      current.map((n) =>
        n.selected === (n.id === nodeId) ? n : { ...n, selected: n.id === nodeId },
      ),
    );
    void fitView({ nodes: [{ id: nodeId }], padding: 0.5, maxZoom: 1, duration: 300 });
  }, [focusRequest, fitView, setNodes]);

  // --- structural editing (ADR 0011 W4) — every gesture routes through the
  // --- store's actions; this component never mutates graph state itself.

  // Client-side pre-check during the drag (D6): reject self-loops and
  // connections that would close a cycle, so the connection line refuses the
  // drop. The server stays the authority on the completed graph — anything
  // that slips through is rejected by the save and reverted by the queue.
  const isValidConnection: IsValidConnection = useCallback((conn) => {
    const { source, target } = conn;
    if (!source || !target || source === target) return false;
    const adjacency = new Map<string, string[]>();
    for (const e of edgesRef.current) {
      const targets = adjacency.get(e.source);
      if (targets) targets.push(e.target);
      else adjacency.set(e.source, [e.target]);
    }
    // A cycle would exist iff `source` is already reachable from `target`.
    const stack = [target];
    const seen = new Set<string>();
    while (stack.length > 0) {
      const current = stack.pop();
      if (current === undefined) break;
      if (current === source) return false;
      if (seen.has(current)) continue;
      seen.add(current);
      for (const next of adjacency.get(current) ?? []) stack.push(next);
    }
    return true;
  }, []);

  // A completed connect: into the store (optimistic overlay → validate-on-
  // connect → single-flight save). Dropping onto an occupied input replaces
  // the existing edge (D5) inside the store's overlay composition.
  const onConnect = useCallback((connection: Connection) => {
    const edge = graphEdgeOf(
      connection.source,
      connection.sourceHandle,
      connection.target,
      connection.targetHandle,
    );
    if (edge) connectEdge(edge);
  }, []);

  // Dragging an edge end to a new socket: delete + add in one gesture, one save.
  const onReconnect: OnReconnect = useCallback((oldEdge, connection) => {
    const from = graphEdgeOf(oldEdge.source, oldEdge.sourceHandle, oldEdge.target, oldEdge.targetHandle);
    const to = graphEdgeOf(
      connection.source,
      connection.sourceHandle,
      connection.target,
      connection.targetHandle,
    );
    if (!from || !to || sameGraphEdge(from, to)) return;
    reconnectEdge(from, to);
  }, []);

  // Delete (keyboard or programmatic): one store mutation for the whole
  // selection; node removals cascade their edges in the store (D4).
  const onDelete = useCallback(
    ({ nodes: deletedNodes, edges: deletedEdges }: { nodes: Node[]; edges: Edge[] }) => {
      const graphEdges: GraphEdge[] = [];
      for (const e of deletedEdges) {
        const edge = graphEdgeOf(e.source, e.sourceHandle, e.target, e.targetHandle);
        if (edge) graphEdges.push(edge);
      }
      deleteElements(
        deletedNodes.map((n) => n.id),
        graphEdges,
      );
      if (deletedNodes.some((n) => n.id === selectedNodeId)) onSelectNode(null);
    },
    [selectedNodeId, onSelectNode],
  );

  // Drag-to-reposition: the debounced, sidecar-only, rev-neutral position save
  // (ADR 0008 position-save note) — NEVER the source queue, never a .py diff.
  const onNodeDragStop: OnNodeDrag<Node<SpecNodeData>> = useCallback((_event, _node, dragged) => {
    for (const n of dragged) queuePositionSave(n.id, n.position);
  }, []);

  // Drop from the palette (the W5→W4 contract): a dropped node is born pinned
  // at the drop point — `createNode(type, dropPosition)`.
  const onDragOver = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    if (!event.dataTransfer.types.includes(PALETTE_SPEC_MIME)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
  }, []);
  const onDrop = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      const specId = event.dataTransfer.getData(PALETTE_SPEC_MIME);
      if (!specId) return;
      event.preventDefault();
      const position = screenToFlowPosition({ x: event.clientX, y: event.clientY });
      // A mint failure is already surfaced on the store's writeError banner.
      void createNode(specId, position).catch(() => undefined);
    },
    [screenToFlowPosition],
  );

  // The node catalog's click-to-insert default position (ADR 0017 D4): the
  // centre of the visible canvas in graph coordinates. Null when the canvas
  // isn't mounted, so the catalog falls back to a blind stagger.
  const getInsertPosition = useCallback((): { x: number; y: number } | null => {
    const el = canvasRef.current;
    if (!el) return null;
    const rect = el.getBoundingClientRect();
    return screenToFlowPosition({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 });
  }, [screenToFlowPosition]);
  useImperativeHandle(handleRef, () => ({ getInsertPosition }), [getInsertPosition]);

  // "Tidy layout" (HD3): the full auto-layout over EVERYTHING, persisted — a
  // tidy you can lose on reload isn't tidy (open confirmation 5).
  const onTidyLayout = useCallback(() => {
    const el = canvasRef.current;
    const aspect = el && el.clientHeight > 0 ? el.clientWidth / el.clientHeight : undefined;
    const laidOut = layoutFlowNodes(nodes, edges, aspect);
    setNodes(laidOut);
    for (const n of laidOut) queuePositionSave(n.id, n.position);
    // Two frames so ReactFlow ingests the new positions before framing them.
    requestAnimationFrame(() => {
      requestAnimationFrame(() => void fitView(FIT_VIEW));
    });
  }, [nodes, edges, setNodes, fitView]);

  // The structural-save fallback warning (HD2 §4) auto-dismisses like the
  // write-error banner, but slower — it says real content was normalized.
  useEffect(() => {
    if (!writebackWarning) return;
    const timer = window.setTimeout(() => setWritebackWarning(null), 10_000);
    return () => window.clearTimeout(timer);
  }, [writebackWarning]);

  return (
    <div
      ref={canvasRef}
      className="ge-canvas"
      data-testid="flow-canvas"
      data-layout-ready={phase === 'ready'}
      data-run-stale={runIsStale ? 'true' : undefined}
      onDragOver={onDragOver}
      onDrop={onDrop}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        onConnect={onConnect}
        onReconnect={onReconnect}
        onDelete={onDelete}
        onNodeDragStop={onNodeDragStop}
        isValidConnection={isValidConnection}
        deleteKeyCode={['Backspace', 'Delete']}
        nodeTypes={nodeTypes}
        defaultEdgeOptions={defaultEdgeOptions}
        colorMode="dark"
        minZoom={0.1}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={28} size={1.4} />
        {/* Non-interactive overview: pointer events pass through (see styles.css)
            so nodes beneath the minimap in the bottom-right corner stay clickable. */}
        <MiniMap />
        {/* Same fit options as the app's own framing, so both fits agree. */}
        <Controls showInteractive={false} fitViewOptions={FIT_VIEW} />
        <Panel position="top-right" className="ge-canvas-tools">
          <button
            type="button"
            className="ge-btn"
            data-testid="tidy-layout"
            title="Auto-arrange every node and save the layout"
            onClick={onTidyLayout}
          >
            Tidy layout
          </button>
        </Panel>
        {writebackWarning && (
          <Panel position="top-center" className="ge-writeback-warning" role="status">
            <span data-testid="writeback-warning">{writebackWarning.message}</span>
            <button
              type="button"
              className="ge-btn ge-writeback-warning__dismiss"
              data-testid="writeback-warning-dismiss"
              onClick={() => setWritebackWarning(null)}
            >
              dismiss
            </button>
          </Panel>
        )}
        {phase === 'ready' && !selectedNodeId && (
          <Panel position="top-left" className="ge-hint">
            Select a node to inspect it — drag, wire and delete to edit the graph
          </Panel>
        )}
      </ReactFlow>
    </div>
  );
}

/**
 * The ReactFlow canvas for one graph + spec set. Kept as its own component so
 * ReactFlow's stateful hooks only mount once live data has loaded (App renders
 * loading/error states before this ever appears).
 */
export const GraphView = forwardRef<GraphViewHandle, GraphViewProps>(function GraphView(props, ref) {
  return (
    <ReactFlowProvider>
      <GraphCanvas {...props} handleRef={ref} />
    </ReactFlowProvider>
  );
});
