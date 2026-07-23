// Shapes mirror the engine's JSON contract v0.2.0 (see graph-engine/engine/README.md).
// Only the fields this read-only renderer consumes are typed; the contract is
// additive-tolerant, so unknown fields are ignored.

export interface Widget {
  kind: string;
  subtype?: string;
  // Optional, editor-specific options declared in Python via `Widget(kind, **config)`
  // (ADR 0005 A-D3). Opaque to the shell; passed through to the editor component.
  config?: Record<string, unknown>;
}

export interface SpecInput {
  name: string;
  type: string;
  kind: string;
  required: boolean;
  default: unknown;
  widget: Widget | null;
  // True on an input entry derived from a dynamic node's literal (ADR 0007 D3).
  // Absent on the static spec entries GET /api/specs serves; present on the
  // entries POST /api/specs/{id}/derive returns.
  derived?: boolean;
}

export interface SpecOutput {
  name: string;
  type: string;
}

// A node-level rendering declaration (ADR 0010 D2): `kind` resolves against the
// JS renderer registry (web/src/node-renderers/); `config` is opaque options
// declared in Python via `Renderer(kind, **config)`. Optional and additive —
// specs without it render exactly as before.
export interface RendererDecl {
  kind: string;
  config?: Record<string, unknown>;
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
  // Optional whole-node renderer declaration (ADR 0010). Absent/null on specs
  // from engines that predate the field — the UI falls back to result chips.
  renderer?: RendererDecl | null;
  // Additive marker (ADR 0007 D1): present on a dynamic node type whose extra
  // input sockets are derived from the value of one literal parameter. The
  // derivation itself is server-side (POST /api/specs/{id}/derive).
  dynamicInputs?: { param: string } | null;
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
  // The graph node's id and declared type, always present so a spec-less node
  // can still identify itself.
  id: string;
  type: string;
  // Null when the graph references a type that has no matching spec.
  spec: NodeSpec | null;
  // The concrete literal value bound to each input in the graph (if any).
  boundInputs: Record<string, unknown>;
  // Input names that are fed by an edge (wired) rather than a literal widget value.
  wiredInputs: Set<string>;
  // Output names this node feeds into an edge. Used to render matching source
  // handles on a spec-less node so its outgoing edges still connect.
  wiredOutputs: Set<string>;
  // True when this node produces the graph's final output socket.
  isOutput: boolean;
  // The socket values this node produced in the most recent run (null before a
  // run, or when the run failed before reaching this node).
  result: Record<string, unknown> | null;
  // True when the most recent run failed at this node.
  hasError: boolean;
  // Required inputs neither wired nor given a literal, per the latest edit-mode
  // validation (ADR 0011 D6) — the on-canvas "needs wiring" badge (stream W4).
  needsWiring: string[];
}
