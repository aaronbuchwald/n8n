// Layered (Sugiyama-style) left-to-right auto-layout for a small DAG.
//
// The engine emits `position: null` for every node, so the viewer owns the
// arrangement. Three classic phases, sized for graphs of 1 to ~a dozen nodes:
//
//  1. Layer assignment — longest path from any root (left → right).
//  2. Crossing reduction — median-ordering sweeps (forward on predecessors,
//     backward on successors) to untangle edges between adjacent layers.
//  3. Coordinate assignment — layers spaced by their widest node, nodes
//     stacked with even gaps and relaxed toward the mean of their neighbours,
//     every layer centred on a shared horizontal axis.
//
// The math is pure and framework-free so it can run twice: once with estimated
// sizes for the very first paint, and again with ReactFlow's *measured* node
// sizes (see GraphView) for the final arrangement.

export interface LayoutNode {
  id: string;
  width: number;
  height: number;
}

export interface LayoutEdge {
  source: string;
  target: string;
}

export interface LayoutPoint {
  x: number;
  y: number;
}

export interface LayoutOptions {
  /** Horizontal gap between adjacent layers. */
  layerGap?: number;
  /** Vertical gap between nodes stacked in the same layer. */
  nodeGap?: number;
}

const DEFAULT_LAYER_GAP = 120;
const DEFAULT_NODE_GAP = 56;

/** Top-left positions for each node, keyed by node id. */
export function computeLayout(
  nodes: LayoutNode[],
  edges: LayoutEdge[],
  options: LayoutOptions = {},
): Map<string, LayoutPoint> {
  const layerGap = options.layerGap ?? DEFAULT_LAYER_GAP;
  const nodeGap = options.nodeGap ?? DEFAULT_NODE_GAP;

  const result = new Map<string, LayoutPoint>();
  if (nodes.length === 0) return result;

  const size = new Map(nodes.map((n) => [n.id, n]));
  // Ignore edges that reference unknown nodes or self-loops; the layout must
  // never throw on malformed input.
  const links = edges.filter(
    (e) => size.has(e.source) && size.has(e.target) && e.source !== e.target,
  );

  const preds = new Map<string, string[]>();
  const succs = new Map<string, string[]>();
  for (const n of nodes) {
    preds.set(n.id, []);
    succs.set(n.id, []);
  }
  for (const e of links) {
    preds.get(e.target)?.push(e.source);
    succs.get(e.source)?.push(e.target);
  }

  // ---- 1. layer assignment: longest path from any root --------------------
  const layerOf = new Map<string, number>();
  const computeLayer = (id: string, trail: Set<string>): number => {
    const known = layerOf.get(id);
    if (known !== undefined) return known;
    if (trail.has(id)) return 0; // cycle guard (the engine forbids cycles)
    trail.add(id);
    const ps = preds.get(id) ?? [];
    const layer = ps.length === 0 ? 0 : Math.max(...ps.map((p) => computeLayer(p, trail) + 1));
    trail.delete(id);
    layerOf.set(id, layer);
    return layer;
  };
  for (const n of nodes) computeLayer(n.id, new Set());

  const layerCount = Math.max(...layerOf.values()) + 1;
  const layers: string[][] = Array.from({ length: layerCount }, () => []);
  for (const n of nodes) layers[layerOf.get(n.id) ?? 0].push(n.id);

  // ---- 2. crossing reduction: median ordering sweeps -----------------------
  const indexIn = new Map<string, number>();
  const refreshIndex = (layer: string[]) => layer.forEach((id, i) => indexIn.set(id, i));
  layers.forEach(refreshIndex);

  const medianIndex = (ids: string[]): number => {
    if (ids.length === 0) return Number.NaN;
    const xs = ids.map((id) => indexIn.get(id) ?? 0).sort((a, b) => a - b);
    const mid = Math.floor(xs.length / 2);
    return xs.length % 2 === 1 ? xs[mid] : (xs[mid - 1] + xs[mid]) / 2;
  };

  const orderBy = (layer: string[], neighbours: Map<string, string[]>) => {
    const keys = new Map<string, number>();
    layer.forEach((id, i) => {
      const m = medianIndex(neighbours.get(id) ?? []);
      // Nodes with no neighbours keep their current slot.
      keys.set(id, Number.isNaN(m) ? i : m);
    });
    layer.sort(
      (a, b) => (keys.get(a) ?? 0) - (keys.get(b) ?? 0) || (indexIn.get(a) ?? 0) - (indexIn.get(b) ?? 0),
    );
    refreshIndex(layer);
  };

  for (let sweep = 0; sweep < 4; sweep++) {
    if (sweep % 2 === 0) {
      for (let i = 1; i < layers.length; i++) orderBy(layers[i], preds);
    } else {
      for (let i = layers.length - 2; i >= 0; i--) orderBy(layers[i], succs);
    }
  }

  // ---- 3. coordinate assignment -------------------------------------------
  // Horizontal: each layer is a column as wide as its widest node; nodes are
  // centred within their column so left/right handles stay tidy.
  const layerW = layers.map((layer) =>
    Math.max(...layer.map((id) => size.get(id)?.width ?? 0)),
  );
  const layerX: number[] = [];
  let x = 0;
  for (let i = 0; i < layers.length; i++) {
    layerX[i] = x;
    x += layerW[i] + layerGap;
  }

  // Vertical, first pass: stack each layer with even gaps, centred on y = 0.
  const centerY = new Map<string, number>();
  for (const layer of layers) {
    const totalH =
      layer.reduce((sum, id) => sum + (size.get(id)?.height ?? 0), 0) +
      nodeGap * (layer.length - 1);
    let y = -totalH / 2;
    for (const id of layer) {
      const h = size.get(id)?.height ?? 0;
      centerY.set(id, y + h / 2);
      y += h + nodeGap;
    }
  }

  // Vertical, refinement: pull each node toward the mean of its neighbours'
  // centres while preserving in-layer order and minimum gaps, then re-centre
  // the layer so the relaxation doesn't drift the graph.
  const relax = (layer: string[], neighboursOf: (id: string) => string[]) => {
    if (layer.length === 0) return;
    const desired = layer.map((id) => {
      const ns = neighboursOf(id);
      if (ns.length === 0) return centerY.get(id) ?? 0;
      return ns.reduce((sum, n) => sum + (centerY.get(n) ?? 0), 0) / ns.length;
    });
    const placed: number[] = [];
    let prevBottom = Number.NEGATIVE_INFINITY;
    layer.forEach((id, j) => {
      const h = size.get(id)?.height ?? 0;
      const top = Math.max(desired[j] - h / 2, j === 0 ? Number.NEGATIVE_INFINITY : prevBottom + nodeGap);
      placed.push(top + h / 2);
      prevBottom = top + h;
    });
    const drift =
      placed.reduce((sum, c, j) => sum + (desired[j] - c), 0) / layer.length;
    layer.forEach((id, j) => centerY.set(id, placed[j] + drift));
  };

  for (let iter = 0; iter < 3; iter++) {
    for (let i = 1; i < layers.length; i++) relax(layers[i], (id) => preds.get(id) ?? []);
    for (let i = layers.length - 2; i >= 0; i--) relax(layers[i], (id) => succs.get(id) ?? []);
  }

  layers.forEach((layer, i) => {
    for (const id of layer) {
      const n = size.get(id);
      if (!n) continue;
      result.set(id, {
        x: layerX[i] + (layerW[i] - n.width) / 2,
        y: (centerY.get(id) ?? 0) - n.height / 2,
      });
    }
  });
  return result;
}
