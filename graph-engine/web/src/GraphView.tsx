import { useEffect, useMemo } from 'react';
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  type NodeTypes,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import type { SocketValues } from './api';
import { buildFlow } from './buildGraph';
import { SpecNode } from './components/SpecNode';
import type { GraphDoc, NodeSpecs } from './types';

const nodeTypes: NodeTypes = { specNode: SpecNode };

interface GraphViewProps {
  graph: GraphDoc;
  specs: NodeSpecs;
  // Per-node socket values from the latest run (null before any run).
  runOutputs: Record<string, SocketValues> | null;
  // The node the latest run failed at, if any.
  errorNodeId: string | null;
}

/**
 * The ReactFlow canvas for one graph + spec set. Kept as its own component so
 * ReactFlow's stateful hooks only mount once live data has loaded (App renders
 * loading/error states before this ever appears).
 */
export function GraphView({ graph, specs, runOutputs, errorNodeId }: GraphViewProps) {
  const { nodes: initialNodes, edges: initialEdges } = useMemo(
    () => buildFlow(graph, specs),
    [graph, specs],
  );

  // Controlled state so ReactFlow can sync node dimensions back (minimap) and
  // apply drag position changes. Without change handlers both are inert.
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, , onEdgesChange] = useEdgesState(initialEdges);

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

  return (
    <div className="ge-canvas" data-testid="flow-canvas">
      <ReactFlowProvider>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          colorMode="dark"
          fitView
          minZoom={0.1}
          nodesConnectable={false}
          edgesFocusable={false}
          proOptions={{ hideAttribution: true }}
        >
          <Background />
          <MiniMap pannable zoomable />
          <Controls showInteractive={false} />
        </ReactFlow>
      </ReactFlowProvider>
    </div>
  );
}
