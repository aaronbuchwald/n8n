import type { Edge, Node } from '@xyflow/react';
import { computeLayout, type LayoutEdge } from './layout';
import type { GraphDoc, NodeSpec, NodeSpecs, SpecNodeData } from './types';

// Handle ids are namespaced by direction so a socket that is both an input and
// output name (e.g. "result") never collides.
export const inHandle = (name: string) => `in:${name}`;
export const outHandle = (name: string) => `out:${name}`;

// Fixed card width — must match `.ge-node { width }` in styles.css. Content
// adapts to the card (ellipsis/clamping), never the other way around, so the
// pre-measurement width estimate is exact.
export const NODE_WIDTH = 280;

// Pre-measurement height estimate. Only used for the very first (invisible)
// paint; the layout re-runs with ReactFlow's measured sizes right after
// mounting (see GraphView), so this only needs to be in the right ballpark.
const HEADER_H = 41;
const DOC_H = 37; // docstring clamps to two lines
const ROW_H = 25; // one socket row
const BODY_PAD = 21;

function estimateHeight(spec: NodeSpec | null): number {
  if (!spec) return HEADER_H + DOC_H + 2 * ROW_H + BODY_PAD;
  const rows = Math.max(spec.inputs.length + spec.outputs.length, 1);
  return HEADER_H + (spec.doc ? DOC_H : 0) + rows * ROW_H + BODY_PAD;
}

/**
 * Re-run the auto-layout over existing ReactFlow nodes, preferring their
 * measured dimensions (available once ReactFlow has rendered them) and falling
 * back to estimates. Returns new node objects with updated positions.
 */
export function layoutFlowNodes(
  nodes: Node<SpecNodeData>[],
  edges: Edge[],
): Node<SpecNodeData>[] {
  const layoutEdges: LayoutEdge[] = edges.map((e) => ({ source: e.source, target: e.target }));
  const positions = computeLayout(
    nodes.map((n) => ({
      id: n.id,
      width: n.measured?.width ?? NODE_WIDTH,
      height: n.measured?.height ?? estimateHeight(n.data.spec),
    })),
    layoutEdges,
  );
  return nodes.map((n) => {
    const p = positions.get(n.id);
    return p ? { ...n, position: p } : n;
  });
}

/**
 * Convert the engine's graph + node-spec JSON into ReactFlow nodes and edges.
 *
 * The engine emits `position: null`, so positions always come from the
 * auto-layout (layout.ts): estimated sizes here for the initial mount, then
 * refreshed with measured sizes in GraphView before the canvas is revealed.
 */
export function buildFlow(
  graph: GraphDoc,
  specs: NodeSpecs,
): { nodes: Node<SpecNodeData>[]; edges: Edge[] } {
  // Input names of each node fed by an edge, keyed by node id.
  const wiredByNode = new Map<string, Set<string>>();
  for (const e of graph.edges) {
    let set = wiredByNode.get(e.target);
    if (!set) {
      set = new Set();
      wiredByNode.set(e.target, set);
    }
    set.add(e.targetInput);
  }

  // Source outputs each node feeds into an edge, keyed by node id.
  const wiredOutByNode = new Map<string, Set<string>>();
  for (const e of graph.edges) {
    let set = wiredOutByNode.get(e.source);
    if (!set) {
      set = new Set();
      wiredOutByNode.set(e.source, set);
    }
    set.add(e.sourceOutput);
  }

  const nodes: Node<SpecNodeData>[] = graph.nodes.map((gn) => {
    const spec = specs[gn.type];
    return {
      id: gn.id,
      type: 'specNode',
      position: { x: 0, y: 0 }, // replaced by layoutFlowNodes below
      data: {
        id: gn.id,
        type: gn.type,
        spec: spec ?? null,
        boundInputs: gn.inputs ?? {},
        wiredInputs: wiredByNode.get(gn.id) ?? new Set<string>(),
        wiredOutputs: wiredOutByNode.get(gn.id) ?? new Set<string>(),
        isOutput: graph.output?.node === gn.id,
        // Run results are patched in after execution (see GraphView).
        result: null,
        hasError: false,
      },
      // Read-only: no graph mutations, but keep nodes draggable so a reviewer
      // can rearrange while exploring.
    };
  });

  const edges: Edge[] = graph.edges.map((e, i) => ({
    id: `e${i}:${e.source}.${e.sourceOutput}->${e.target}.${e.targetInput}`,
    source: e.source,
    sourceHandle: outHandle(e.sourceOutput),
    target: e.target,
    targetHandle: inHandle(e.targetInput),
    // Marching-ants reads as "executing"; reserve animation for run-progress.
    animated: false,
  }));

  return { nodes: layoutFlowNodes(nodes, edges), edges };
}
