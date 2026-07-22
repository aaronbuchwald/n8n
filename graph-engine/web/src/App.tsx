import { useMemo } from 'react';
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

import graphDoc from './fixtures/example.graph.json';
import nodeSpecs from './fixtures/example.node-specs.json';
import { buildFlow } from './buildGraph';
import { SpecNode } from './components/SpecNode';
import type { GraphDoc, NodeSpecs } from './types';

const nodeTypes: NodeTypes = { specNode: SpecNode };

export default function App() {
  const { nodes: initialNodes, edges: initialEdges } = useMemo(
    () => buildFlow(graphDoc as GraphDoc, nodeSpecs as NodeSpecs),
    [],
  );

  // Controlled state so ReactFlow can sync node dimensions back (minimap) and
  // apply drag position changes. Without change handlers both are inert.
  const [nodes, , onNodesChange] = useNodesState(initialNodes);
  const [edges, , onEdgesChange] = useEdgesState(initialEdges);

  const doc = graphDoc as GraphDoc;

  return (
    <div className="ge-app">
      <header className="ge-topbar">
        <h1 className="ge-topbar__title">graph-engine</h1>
        <span className="ge-topbar__sub">
          example graph · read-only · contract v{doc.version}
        </span>
        <span className="ge-topbar__out" data-testid="graph-output-label">
          output → {doc.output ? `${doc.output.node}.${doc.output.socket}` : 'none'}
        </span>
      </header>
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
    </div>
  );
}
