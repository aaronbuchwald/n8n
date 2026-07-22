// Shapes mirror the engine's JSON contract v0.2.0 (see graph-engine/engine/README.md).
// Only the fields this read-only renderer consumes are typed; the contract is
// additive-tolerant, so unknown fields are ignored.

export interface Widget {
  kind: string;
  subtype?: string;
}

export interface SpecInput {
  name: string;
  type: string;
  kind: string;
  required: boolean;
  default: unknown;
  widget: Widget | null;
}

export interface SpecOutput {
  name: string;
  type: string;
}

export interface NodeSpec {
  id: string;
  name: string;
  title: string;
  module: string;
  qualname: string;
  doc: string;
  inputs: SpecInput[];
  outputs: SpecOutput[];
}

export type NodeSpecs = Record<string, NodeSpec>;

export interface GraphNode {
  id: string;
  type: string;
  inputs: Record<string, unknown>;
  position: { x: number; y: number } | null;
}

export interface GraphEdge {
  source: string;
  sourceOutput: string;
  target: string;
  targetInput: string;
}

export interface GraphOutput {
  node: string;
  socket: string;
}

export interface GraphDoc {
  version: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  output: GraphOutput | null;
}

// Data carried by each ReactFlow custom node.
export interface SpecNodeData extends Record<string, unknown> {
  spec: NodeSpec;
  // The concrete literal value bound to each input in the graph (if any).
  boundInputs: Record<string, unknown>;
  // Input names that are fed by an edge (wired) rather than a literal widget value.
  wiredInputs: Set<string>;
  // True when this node produces the graph's final output socket.
  isOutput: boolean;
}
