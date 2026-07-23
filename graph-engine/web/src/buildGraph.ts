import type { Edge, Node } from '@xyflow/react';
import { computeLayout, placeUnpinned, type LayoutEdge, type LayoutNode } from './layout';
import type { GraphDoc, NodeSpec, NodeSpecs, SpecInput, SpecNodeData } from './types';

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
 *
 * With `pinnedIds` (ADR 0011 HD3), pinned nodes keep their current positions
 * and only the rest are auto-placed relative to them (`placeUnpinned`); without
 * it — the "Tidy layout" command and all-auto graphs — everything is laid out.
 */
export function layoutFlowNodes(
  nodes: Node<SpecNodeData>[],
  edges: Edge[],
  /** Viewport aspect (width/height) the layout's row wrapping should target. */
  targetAspect?: number,
  /** Node ids whose positions are user/sidecar-authoritative — never moved. */
  pinnedIds?: ReadonlySet<string>,
): Node<SpecNodeData>[] {
  const layoutEdges: LayoutEdge[] = edges.map((e) => ({ source: e.source, target: e.target }));
  const layoutNodes: LayoutNode[] = nodes.map((n) => ({
    id: n.id,
    width: n.measured?.width ?? NODE_WIDTH,
    height: n.measured?.height ?? estimateHeight(n.data.spec),
  }));

  if (pinnedIds && pinnedIds.size > 0) {
    if (nodes.every((n) => pinnedIds.has(n.id))) return nodes; // nothing to place
    const pinned = new Map(
      nodes.filter((n) => pinnedIds.has(n.id)).map((n) => [n.id, n.position]),
    );
    const positions = placeUnpinned(layoutNodes, layoutEdges, pinned);
    return nodes.map((n) => {
      const p = positions.get(n.id);
      return p ? { ...n, position: p } : n;
    });
  }

  const positions = computeLayout(
    layoutNodes,
    layoutEdges,
    targetAspect !== undefined ? { targetAspect } : {},
  );
  return nodes.map((n) => {
    const p = positions.get(n.id);
    return p ? { ...n, position: p } : n;
  });
}

/** Node ids whose served `position` is non-null — the sidecar-pinned set (HD3). */
export function pinnedIdsOf(graph: GraphDoc): Set<string> {
  const pinned = new Set<string>();
  for (const n of graph.nodes) if (n.position !== null) pinned.add(n.id);
  return pinned;
}

/**
 * Convert the engine's graph + node-spec JSON into ReactFlow nodes and edges.
 *
 * Positions are sidecar-authoritative (ADR 0011 HD3): a node with a served
 * `position` (the server merges the `*.layout.json` sidecar in) keeps it;
 * only `position: null` nodes are auto-placed — relative to the pinned ones
 * (`layoutFlowNodes`). A graph with no pinned nodes (code-first authoring)
 * gets the full auto-layout, exactly as before: estimated sizes here for the
 * initial mount, refreshed with measured sizes in GraphView.
 */
export function buildFlow(
  graph: GraphDoc,
  specs: NodeSpecs,
  // Per-node derived input entries for dynamic nodes (ADR 0007): the store's
  // precomputed `derivedByNode` view (each node's committed deriving literal
  // resolved through `state.derived`). Merged into that node's rendered input
  // list so derived sockets get real handles, wiring states and widget slots
  // exactly like static ones. Absent (or an absent node key) → static spec
  // only, which keeps existing wires on screen when derivation fails.
  derivedByNode?: ReadonlyMap<string, SpecInput[]>,
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
    let spec: NodeSpec | undefined = specs[gn.type];
    const derived = derivedByNode?.get(gn.id);
    if (spec && derived && derived.length > 0) {
      spec = { ...spec, inputs: [...spec.inputs, ...derived] };
    }
    return {
      id: gn.id,
      type: 'specNode',
      // Sidecar-authoritative (HD3); auto-layout below replaces the null case.
      position: gn.position ?? { x: 0, y: 0 },
      data: {
        id: gn.id,
        type: gn.type,
        spec: spec ?? null,
        boundInputs: gn.inputs ?? {},
        wiredInputs: wiredByNode.get(gn.id) ?? new Set<string>(),
        wiredOutputs: wiredOutByNode.get(gn.id) ?? new Set<string>(),
        isOutput: graph.output?.node === gn.id,
        // Run results and edit-mode validation badges are patched in after the
        // fact (see GraphView).
        result: null,
        hasError: false,
        needsWiring: [],
      },
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

  return { nodes: layoutFlowNodes(nodes, edges, undefined, pinnedIdsOf(graph)), edges };
}
