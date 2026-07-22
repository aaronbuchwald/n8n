import type { Edge, Node } from '@xyflow/react';
import type { GraphDoc, NodeSpecs, SpecNodeData } from './types';

// Handle ids are namespaced by direction so a socket that is both an input and
// output name (e.g. "result") never collides.
export const inHandle = (name: string) => `in:${name}`;
export const outHandle = (name: string) => `out:${name}`;

/**
 * Convert the engine's graph + node-spec JSON into ReactFlow nodes and edges.
 *
 * The engine emits `position: null`, so we lay the graph out left-to-right in
 * topological-ish order using each node's longest distance from a root. This
 * keeps the read-only view readable without any stored coordinates.
 */
export function buildFlow(
  graph: GraphDoc,
  specs: NodeSpecs,
): { nodes: Node<SpecNodeData>[]; edges: Edge[] } {
  // name of each node fed by an edge, keyed by node id -> set of target inputs.
  const wiredByNode = new Map<string, Set<string>>();
  for (const e of graph.edges) {
    let set = wiredByNode.get(e.target);
    if (!set) {
      set = new Set();
      wiredByNode.set(e.target, set);
    }
    set.add(e.targetInput);
  }

  // Longest-path depth from any root, for column placement.
  const depth = new Map<string, number>();
  const incoming = new Map<string, string[]>();
  for (const n of graph.nodes) incoming.set(n.id, []);
  for (const e of graph.edges) incoming.get(e.target)?.push(e.source);

  const computeDepth = (id: string, seen: Set<string>): number => {
    if (depth.has(id)) return depth.get(id)!;
    if (seen.has(id)) return 0; // cycle guard (engine forbids cycles, but be safe)
    seen.add(id);
    const parents = incoming.get(id) ?? [];
    const d = parents.length === 0 ? 0 : Math.max(...parents.map((p) => computeDepth(p, seen) + 1));
    depth.set(id, d);
    return d;
  };
  for (const n of graph.nodes) computeDepth(n.id, new Set());

  // Vertical index within a column.
  const rowByColumn = new Map<number, number>();
  const COL_W = 320;
  const ROW_H = 200;

  const nodes: Node<SpecNodeData>[] = graph.nodes.map((gn) => {
    const spec = specs[gn.type];
    const col = depth.get(gn.id) ?? 0;
    const row = rowByColumn.get(col) ?? 0;
    rowByColumn.set(col, row + 1);

    const position = gn.position ?? { x: col * COL_W + 40, y: row * ROW_H + 40 };

    return {
      id: gn.id,
      type: 'specNode',
      position,
      data: {
        spec,
        boundInputs: gn.inputs ?? {},
        wiredInputs: wiredByNode.get(gn.id) ?? new Set<string>(),
        isOutput: graph.output?.node === gn.id,
      },
      // Read-only: no dragging/selecting mutations matter, but keep nodes draggable
      // so a reviewer can rearrange while exploring.
    };
  });

  const edges: Edge[] = graph.edges.map((e, i) => ({
    id: `e${i}:${e.source}.${e.sourceOutput}->${e.target}.${e.targetInput}`,
    source: e.source,
    sourceHandle: outHandle(e.sourceOutput),
    target: e.target,
    targetHandle: inHandle(e.targetInput),
    animated: true,
  }));

  return { nodes, edges };
}
