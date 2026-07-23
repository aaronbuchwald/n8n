import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
  type NodeMouseHandler,
  type NodeTypes,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import type { SocketValues } from './api';
import { buildFlow, layoutFlowNodes } from './buildGraph';
import { NodeInspector } from './components/NodeInspector';
import { SpecNode } from './components/SpecNode';
import { inspectNode } from './inspect';
import type { GraphDoc, NodeSpecs, SpecInput, SpecNodeData } from './types';

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

// A structural signature: the node ids + edges. It changes only on a real
// topology change (add/remove node or rewire), never on a literal edit — which
// is what lets a widget commit reflect in place without a re-layout/re-frame.
function structureKeyOf(nodes: { id: string }[], edges: { id: string }[]): string {
  return JSON.stringify({ n: nodes.map((n) => n.id), e: edges.map((e) => e.id) });
}

// Smoothstep reads cleanly for a layered left-to-right DAG: edges leave/enter
// horizontally and take soft right-angle turns between layers.
const defaultEdgeOptions = { type: 'smoothstep' as const, pathOptions: { borderRadius: 14 } };

export interface FocusRequest {
  nodeId: string;
  /** Distinguishes repeated requests for the same node. */
  token: number;
}

interface GraphViewProps {
  graph: GraphDoc;
  specs: NodeSpecs;
  // Derived input entries per dynamic node id (ADR 0007), merged into the
  // rendered spec by buildFlow. Optional so callers without dynamic nodes
  // (and existing tests) are unchanged.
  derivedByNode?: ReadonlyMap<string, SpecInput[]>;
  // Per-node socket values from the latest run (null before any run).
  runOutputs: Record<string, SocketValues> | null;
  // The node the latest run failed at, if any.
  errorNodeId: string | null;
  // Selection is owned by the caller so panels outside the canvas (results
  // rows, the app-level Escape handler) can drive it too.
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string | null) => void;
  // A request (e.g. from a run-results row) to select + centre a node.
  focusRequest: FocusRequest | null;
  // Source editing for the selected node's type, owned by the app so the
  // Escape cascade and selection changes can close it.
  editingSource: boolean;
  onEditSourceChange: (open: boolean) => void;
  onSourceSaved: () => void;
}

// mount → nodes measured → final layout applied → graph framed → visible.
type LayoutPhase = 'measuring' | 'framing' | 'ready';

function GraphCanvas({
  graph,
  specs,
  derivedByNode,
  runOutputs,
  errorNodeId,
  selectedNodeId,
  onSelectNode,
  focusRequest,
  editingSource,
  onEditSourceChange,
  onSourceSaved,
}: GraphViewProps) {
  const { nodes: initialNodes, edges: initialEdges } = useMemo(
    () => buildFlow(graph, specs, derivedByNode),
    [graph, specs, derivedByNode],
  );

  // Controlled state so ReactFlow can sync node dimensions back (minimap) and
  // apply drag position changes. Without change handlers both are inert.
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  const nodesInitialized = useNodesInitialized();
  const { fitView, getZoom } = useReactFlow();
  const [phase, setPhase] = useState<LayoutPhase>('measuring');
  const canvasRef = useRef<HTMLDivElement>(null);

  // When the served graph changes after a widget commit + quiet reload, fold the
  // freshly derived node DATA (bound literals, wiring, output flag) onto the
  // existing nodes IN PLACE — preserving each node's measured size and dragged
  // position, and NOT re-running the measuring→framing→fit pipeline. Only a real
  // topology change (nodes added/removed or rewired) re-seeds and re-frames, so a
  // literal edit feels instant and local. buildFlow already recomputed
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
          };
          return sameGraphData(n.data, data) ? n : { ...n, data };
        }),
      );
      return;
    }
    // Real structural change: adopt the freshly laid-out graph and re-frame it.
    structureRef.current = structureKey;
    setNodes(initialNodes);
    setEdges(initialEdges);
    setPhase('measuring');
  }, [structureKey, initialNodes, initialEdges, setNodes, setEdges]);

  // The initial layout uses estimated node sizes. Once ReactFlow has measured
  // the real DOM sizes, re-run the layout with them — targeting the actual
  // canvas aspect so row wrapping keeps the fitted zoom readable — then frame
  // the whole graph. The canvas stays invisible (CSS keyed on
  // data-layout-ready) until framing is done, so the user never sees the
  // pre-measurement arrangement.
  useEffect(() => {
    if (phase !== 'measuring' || !nodesInitialized) return;
    const el = canvasRef.current;
    const aspect = el && el.clientHeight > 0 ? el.clientWidth / el.clientHeight : undefined;
    setNodes((current) => layoutFlowNodes(current, initialEdges, aspect));
    setPhase('framing');
  }, [phase, nodesInitialized, setNodes, initialEdges]);

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

  // Keep the graph framed when the canvas itself resizes (e.g. the run-results
  // panel opening below it, or the export dock beside it).
  useEffect(() => {
    if (phase !== 'ready' || !canvasRef.current) return;
    let first = true;
    const observer = new ResizeObserver(() => {
      if (first) {
        first = false; // ignore the initial observe callback
        return;
      }
      requestAnimationFrame(() => void fitView(FIT_VIEW));
    });
    observer.observe(canvasRef.current);
    return () => observer.disconnect();
  }, [phase, fitView]);

  // When a widget editor opens somewhere on the canvas, make sure it is
  // legible: at fit zoom on a wide graph an editor renders far too small to
  // use. Detection is DOM-level (a [data-testid="widget-slot"] appearing, or
  // focus landing inside one) so it needs no signal from the widget files.
  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const zoomed = new WeakSet<Element>();
    const zoomToSlot = (slot: Element) => {
      if (zoomed.has(slot)) return;
      zoomed.add(slot);
      const nodeEl = slot.closest('.react-flow__node');
      const id = nodeEl?.getAttribute('data-id');
      if (!id) return;
      // Already readable — don't yank the viewport out from under the user.
      if (getZoom() >= 0.85) return;
      void fitView({ nodes: [{ id }], padding: 0.4, maxZoom: 1, duration: 250 });
    };
    const scan = (target: Element) => {
      if (target.matches('[data-testid="widget-slot"]')) zoomToSlot(target);
      for (const slot of target.querySelectorAll('[data-testid="widget-slot"]')) {
        zoomToSlot(slot);
      }
    };
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const added of mutation.addedNodes) {
          if (added instanceof Element) scan(added);
        }
      }
    });
    observer.observe(el, { childList: true, subtree: true });
    const onFocusIn = (event: FocusEvent) => {
      if (!(event.target instanceof Element)) return;
      const slot = event.target.closest('[data-testid="widget-slot"]');
      if (slot) zoomToSlot(slot);
    };
    el.addEventListener('focusin', onFocusIn);
    return () => {
      observer.disconnect();
      el.removeEventListener('focusin', onFocusIn);
    };
  }, [fitView, getZoom]);

  // Fold the latest run's outputs + error into each node's data (positions and
  // measured dimensions are preserved — we only patch the result fields).
  useEffect(() => {
    setNodes((current) =>
      current.map((n) => {
        const result = runOutputs ? (runOutputs[n.id] ?? null) : null;
        const hasError = errorNodeId === n.id;
        if (n.data.result === result && n.data.hasError === hasError) return n;
        return { ...n, data: { ...n.data, result, hasError } };
      }),
    );
  }, [runOutputs, errorNodeId, setNodes]);

  // Clicking a node opens the inspector for it; clicking the pane closes it.
  // A click that lands on a widget chip/editor is editing, not inspecting —
  // let it through without also sliding the inspector over the canvas.
  const onNodeClick: NodeMouseHandler = useCallback(
    (event, node) => {
      if (
        event.target instanceof Element &&
        event.target.closest('[data-testid="widget-chip"], [data-testid="widget-slot"]')
      ) {
        return;
      }
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

  const inspected = useMemo(
    () => (selectedNodeId ? inspectNode(graph, specs, selectedNodeId, runOutputs) : null),
    [graph, specs, selectedNodeId, runOutputs],
  );

  // Several nodes may share one @node function; the source editor says so.
  const sharedNodeCount = useMemo(
    () => (inspected ? graph.nodes.filter((n) => n.type === inspected.typeName).length : 0),
    [graph, inspected],
  );

  return (
    <div
      ref={canvasRef}
      className="ge-canvas"
      data-testid="flow-canvas"
      data-layout-ready={phase === 'ready'}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        nodeTypes={nodeTypes}
        defaultEdgeOptions={defaultEdgeOptions}
        colorMode="dark"
        minZoom={0.1}
        nodesConnectable={false}
        edgesFocusable={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={28} size={1.4} />
        <MiniMap pannable zoomable />
        {/* Same fit options as the app's own framing, so both fits agree. */}
        <Controls showInteractive={false} fitViewOptions={FIT_VIEW} />
        {phase === 'ready' && !inspected && (
          <Panel position="top-left" className="ge-hint">
            Select a node to inspect it — and edit its source
          </Panel>
        )}
      </ReactFlow>
      {inspected && (
        <NodeInspector
          node={inspected}
          sharedNodeCount={sharedNodeCount}
          editingSource={editingSource}
          onEditSource={onEditSourceChange}
          onSourceSaved={onSourceSaved}
          onClose={() => onSelectNode(null)}
        />
      )}
    </div>
  );
}

/**
 * The ReactFlow canvas for one graph + spec set. Kept as its own component so
 * ReactFlow's stateful hooks only mount once live data has loaded (App renders
 * loading/error states before this ever appears).
 */
export function GraphView(props: GraphViewProps) {
  return (
    <ReactFlowProvider>
      <GraphCanvas {...props} />
    </ReactFlowProvider>
  );
}
