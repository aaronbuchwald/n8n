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
import type { GraphDoc, NodeSpecs } from './types';

const nodeTypes: NodeTypes = { specNode: SpecNode };

// Smoothstep reads cleanly for a layered left-to-right DAG: edges leave/enter
// horizontally and take soft right-angle turns between layers.
const defaultEdgeOptions = { type: 'smoothstep' as const, pathOptions: { borderRadius: 14 } };

interface GraphViewProps {
  graph: GraphDoc;
  specs: NodeSpecs;
  // Per-node socket values from the latest run (null before any run).
  runOutputs: Record<string, SocketValues> | null;
  // The node the latest run failed at, if any.
  errorNodeId: string | null;
}

// mount → nodes measured → final layout applied → graph framed → visible.
type LayoutPhase = 'measuring' | 'framing' | 'ready';

function GraphCanvas({ graph, specs, runOutputs, errorNodeId }: GraphViewProps) {
  const { nodes: initialNodes, edges: initialEdges } = useMemo(
    () => buildFlow(graph, specs),
    [graph, specs],
  );

  // Controlled state so ReactFlow can sync node dimensions back (minimap) and
  // apply drag position changes. Without change handlers both are inert.
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, , onEdgesChange] = useEdgesState(initialEdges);

  const nodesInitialized = useNodesInitialized();
  const { fitView } = useReactFlow();
  const [phase, setPhase] = useState<LayoutPhase>('measuring');

  // The initial layout uses estimated node sizes. Once ReactFlow has measured
  // the real DOM sizes, re-run the layout with them, then frame the whole
  // graph. The canvas stays invisible (CSS keyed on data-layout-ready) until
  // framing is done, so the user never sees the pre-measurement arrangement.
  useEffect(() => {
    if (phase !== 'measuring' || !nodesInitialized) return;
    setNodes((current) => layoutFlowNodes(current, initialEdges));
    setPhase('framing');
  }, [phase, nodesInitialized, setNodes, initialEdges]);

  useEffect(() => {
    if (phase !== 'framing') return;
    // Two frames: one for React to commit the new positions, one for ReactFlow
    // to ingest them — then fitView sees the final geometry.
    let raf2 = 0;
    const raf1 = requestAnimationFrame(() => {
      raf2 = requestAnimationFrame(() => {
        void fitView({ padding: 0.15, maxZoom: 1.05 }).then(() => setPhase('ready'));
      });
    });
    return () => {
      cancelAnimationFrame(raf1);
      cancelAnimationFrame(raf2);
    };
  }, [phase, fitView]);

  // Keep the graph framed when the canvas itself resizes (e.g. the run-results
  // panel opening below it, or the export dock beside it).
  const canvasRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (phase !== 'ready' || !canvasRef.current) return;
    let first = true;
    const observer = new ResizeObserver(() => {
      if (first) {
        first = false; // ignore the initial observe callback
        return;
      }
      requestAnimationFrame(() => void fitView({ padding: 0.15, maxZoom: 1.05 }));
    });
    observer.observe(canvasRef.current);
    return () => observer.disconnect();
  }, [phase, fitView]);

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
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const onNodeClick: NodeMouseHandler = useCallback((_event, node) => {
    setSelectedId(node.id);
  }, []);
  const onPaneClick = useCallback(() => setSelectedId(null), []);

  const inspected = useMemo(
    () => (selectedId ? inspectNode(graph, specs, selectedId, runOutputs) : null),
    [graph, specs, selectedId, runOutputs],
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
        <Controls showInteractive={false} />
        {phase === 'ready' && !inspected && (
          <Panel position="top-left" className="ge-hint">
            Select a node to inspect its inputs &amp; outputs
          </Panel>
        )}
      </ReactFlow>
      {inspected && <NodeInspector node={inspected} onClose={() => setSelectedId(null)} />}
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
