import type { Edge, Node } from '@xyflow/react';
import type { GraphDoc, NodeSpec, NodeSpecs, SpecNodeData } from './types';

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

  const COL_W = 320;
  // Card height is unbounded (socket count + doc length drive it), so a fixed
  // row pitch overlaps tall nodes. Estimate each node's height and stack columns
  // with a running per-column offset instead.
  const COL_GAP = 40; // top margin + vertical gap between stacked cards
  const HEADER_H = 40; // title/badge row
  const SOCKET_H = 22; // per input/output row
  const CHARS_PER_LINE = 34; // ~doc chars that fit on one wrapped line
  const DOC_LINE_H = 15;
  const BASE_PADDING = 24; // body padding above/below the socket columns

  const estimateHeight = (spec: NodeSpec | undefined): number => {
    if (!spec) return HEADER_H + BASE_PADDING + SOCKET_H; // id + type rows on the unknown card
    const socketRows = Math.max(spec.inputs.length, spec.outputs.length, 1);
    const docLen = spec.doc?.length ?? 0;
    const docLines = docLen > 0 ? Math.ceil(docLen / CHARS_PER_LINE) : 0;
    return HEADER_H + BASE_PADDING + socketRows * SOCKET_H + docLines * DOC_LINE_H;
  };

  // Running vertical offset (next free y) per column.
  const yByColumn = new Map<number, number>();

  const nodes: Node<SpecNodeData>[] = graph.nodes.map((gn) => {
    const spec = specs[gn.type];
    const col = depth.get(gn.id) ?? 0;
    const y = yByColumn.get(col) ?? COL_GAP;
    const height = estimateHeight(spec);
    yByColumn.set(col, y + height + COL_GAP);

    const position = gn.position ?? { x: col * COL_W + 40, y };

    return {
      id: gn.id,
      type: 'specNode',
      position,
      data: {
        id: gn.id,
        type: gn.type,
        spec: spec ?? null,
        boundInputs: gn.inputs ?? {},
        wiredInputs: wiredByNode.get(gn.id) ?? new Set<string>(),
        wiredOutputs: wiredOutByNode.get(gn.id) ?? new Set<string>(),
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
    // Marching-ants reads as "executing"; reserve animation for run-progress.
    animated: false,
  }));

  return { nodes, edges };
}
