// Layered (Sugiyama-style) left-to-right auto-layout for a small DAG.
//
// The engine emits `position: null` for every node, so the viewer owns the
// arrangement. Four phases, sized for graphs of 1 to ~a dozen nodes:
//
//  1. Layer assignment — longest path to any sink (right-aligned): a feeder
//     node sits immediately left of its consumer instead of being pinned to
//     column 0, which keeps every column busy and the graph short.
//  2. Crossing reduction — median-ordering sweeps (forward on predecessors,
//     backward on successors) to untangle edges between adjacent layers.
//  3. Coordinate assignment — layers spaced by their widest node, nodes
//     stacked with even gaps and relaxed toward the mean of their neighbours.
//  4. Row wrapping — a long chain would otherwise lay out as one wide ribbon
//     and force fitView to an illegible zoom, so the layer sequence wraps into
//     rows (like text) whenever that fills the viewport aspect clearly better.
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
  /** Vertical gap between wrapped rows of layers. */
  rowGap?: number;
  /**
   * Aspect ratio (width / height) of the viewport the graph will be fitted
   * into. Row wrapping targets this so the fitted zoom stays readable.
   */
  targetAspect?: number;
}

const DEFAULT_LAYER_GAP = 100;
const DEFAULT_NODE_GAP = 44;
const DEFAULT_ROW_GAP = 96;
const DEFAULT_TARGET_ASPECT = 16 / 9;

/**
 * Place only the UNPINNED nodes of a partially-pinned graph (ADR 0011 HD3:
 * sidecar-authoritative positions, auto-layout as the fallback for
 * `position: null` nodes — *relative to the pinned ones*, near their upstream
 * nodes). Pinned nodes are never moved; the returned map contains positions
 * for the unpinned nodes only.
 *
 * Strategy, per unpinned node in placement waves:
 *  - with placed predecessors: just right of its rightmost predecessor, at the
 *    mean of their vertical centres ("define it where its inputs exist");
 *  - otherwise with placed successors: just left of its leftmost successor;
 *  - otherwise (no placed neighbours): stacked below the occupied bounding box.
 * Every candidate is nudged downward until it overlaps nothing already placed.
 */
export function placeUnpinned(
  nodes: LayoutNode[],
  edges: LayoutEdge[],
  pinned: ReadonlyMap<string, LayoutPoint>,
  options: LayoutOptions = {},
): Map<string, LayoutPoint> {
  const layerGap = options.layerGap ?? DEFAULT_LAYER_GAP;
  const nodeGap = options.nodeGap ?? DEFAULT_NODE_GAP;

  const size = new Map(nodes.map((n) => [n.id, n]));
  const placed = new Map<string, LayoutPoint>();
  for (const [id, p] of pinned) if (size.has(id)) placed.set(id, p);

  const preds = new Map<string, string[]>();
  const succs = new Map<string, string[]>();
  for (const n of nodes) {
    preds.set(n.id, []);
    succs.set(n.id, []);
  }
  for (const e of edges) {
    if (!size.has(e.source) || !size.has(e.target) || e.source === e.target) continue;
    preds.get(e.target)?.push(e.source);
    succs.get(e.source)?.push(e.target);
  }

  const overlaps = (id: string, at: LayoutPoint): LayoutNode | null => {
    const n = size.get(id);
    if (!n) return null;
    for (const [otherId, p] of placed) {
      const o = size.get(otherId);
      if (!o) continue;
      const clear =
        at.x + n.width + nodeGap <= p.x ||
        p.x + o.width + nodeGap <= at.x ||
        at.y + n.height + nodeGap <= p.y ||
        p.y + o.height + nodeGap <= at.y;
      if (!clear) return o;
    }
    return null;
  };

  /** Drop the candidate downward until it collides with nothing placed. */
  const settle = (id: string, at: LayoutPoint): LayoutPoint => {
    const spot = { ...at };
    for (let guard = 0; guard < nodes.length + pinned.size + 8; guard++) {
      const hit = overlaps(id, spot);
      if (!hit) break;
      const hitPos = placed.get(hit.id);
      spot.y = (hitPos?.y ?? spot.y) + hit.height + nodeGap;
    }
    return spot;
  };

  const result = new Map<string, LayoutPoint>();
  const unplaced = nodes.filter((n) => !placed.has(n.id)).map((n) => n.id);

  // Waves: place anything with a placed neighbour until no progress remains.
  let progressed = true;
  while (progressed && unplaced.length > 0) {
    progressed = false;
    for (let i = 0; i < unplaced.length; i++) {
      const id = unplaced[i];
      const n = size.get(id);
      if (!n) continue;
      const placedPreds = (preds.get(id) ?? []).filter((p) => placed.has(p));
      const placedSuccs = (succs.get(id) ?? []).filter((s) => placed.has(s));
      let candidate: LayoutPoint | null = null;
      if (placedPreds.length > 0) {
        const x = Math.max(
          ...placedPreds.map((p) => (placed.get(p)?.x ?? 0) + (size.get(p)?.width ?? 0)),
        );
        const y =
          placedPreds.reduce(
            (sum, p) => sum + (placed.get(p)?.y ?? 0) + (size.get(p)?.height ?? 0) / 2,
            0,
          ) / placedPreds.length;
        candidate = { x: x + layerGap, y: y - n.height / 2 };
      } else if (placedSuccs.length > 0) {
        const x = Math.min(...placedSuccs.map((s) => placed.get(s)?.x ?? 0));
        const y =
          placedSuccs.reduce(
            (sum, s) => sum + (placed.get(s)?.y ?? 0) + (size.get(s)?.height ?? 0) / 2,
            0,
          ) / placedSuccs.length;
        candidate = { x: x - layerGap - n.width, y: y - n.height / 2 };
      }
      if (!candidate) continue;
      const spot = settle(id, candidate);
      placed.set(id, spot);
      result.set(id, spot);
      unplaced.splice(i, 1);
      i--;
      progressed = true;
    }
  }

  // Islands (no placed neighbours at any point): stack below everything.
  if (unplaced.length > 0) {
    let left = 0;
    let bottom = 0;
    if (placed.size > 0) {
      left = Math.min(...[...placed.entries()].map(([, p]) => p.x));
      bottom = Math.max(
        ...[...placed.entries()].map(([id, p]) => p.y + (size.get(id)?.height ?? 0)),
      );
      bottom += DEFAULT_ROW_GAP;
    }
    let y = bottom;
    for (const id of unplaced) {
      const n = size.get(id);
      if (!n) continue;
      const spot = settle(id, { x: left, y });
      placed.set(id, spot);
      result.set(id, spot);
      y = spot.y + n.height + nodeGap;
    }
  }

  return result;
}

/** Top-left positions for each node, keyed by node id. */
export function computeLayout(
  nodes: LayoutNode[],
  edges: LayoutEdge[],
  options: LayoutOptions = {},
): Map<string, LayoutPoint> {
  const layerGap = options.layerGap ?? DEFAULT_LAYER_GAP;
  const nodeGap = options.nodeGap ?? DEFAULT_NODE_GAP;
  const rowGap = options.rowGap ?? DEFAULT_ROW_GAP;
  const targetAspect = options.targetAspect ?? DEFAULT_TARGET_ASPECT;

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

  // ---- 1. layer assignment: longest path to any sink ----------------------
  // Layering by distance-to-sink (instead of distance-from-source) pulls each
  // feeder right next to the node that consumes it, so early columns don't
  // collect every source while later columns sit half-empty.
  const depthOf = new Map<string, number>();
  const computeDepth = (id: string, trail: Set<string>): number => {
    const known = depthOf.get(id);
    if (known !== undefined) return known;
    if (trail.has(id)) return 0; // cycle guard (the engine forbids cycles)
    trail.add(id);
    const ss = succs.get(id) ?? [];
    const depth = ss.length === 0 ? 0 : Math.max(...ss.map((s) => computeDepth(s, trail) + 1));
    trail.delete(id);
    depthOf.set(id, depth);
    return depth;
  };
  for (const n of nodes) computeDepth(n.id, new Set());

  const maxDepth = Math.max(...depthOf.values());
  const layerOf = new Map<string, number>();
  for (const n of nodes) layerOf.set(n.id, maxDepth - (depthOf.get(n.id) ?? 0));

  const layerCount = maxDepth + 1;
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
  // Horizontal: each layer is a column as wide as its widest node.
  const layerW = layers.map((layer) =>
    Math.max(...layer.map((id) => size.get(id)?.width ?? 0)),
  );

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

  // ---- 4. row wrapping ------------------------------------------------------
  // Vertical extent of each layer's stack (from the relaxed centres).
  const layerBounds = layers.map((layer) => {
    let top = Number.POSITIVE_INFINITY;
    let bottom = Number.NEGATIVE_INFINITY;
    for (const id of layer) {
      const h = size.get(id)?.height ?? 0;
      const c = centerY.get(id) ?? 0;
      top = Math.min(top, c - h / 2);
      bottom = Math.max(bottom, c + h / 2);
    }
    return { top, bottom, height: bottom - top };
  });

  // Contiguous partition of the layer sequence into ~k rows of similar width.
  const partitionFor = (k: number): number[][] => {
    const totalW =
      layerW.reduce((sum, w) => sum + w, 0) + layerGap * (layers.length - 1);
    const target = totalW / k;
    const rows: number[][] = [];
    let row: number[] = [];
    let width = 0;
    for (let i = 0; i < layers.length; i++) {
      const grown = width + (row.length > 0 ? layerGap : 0) + layerW[i];
      const rowsLeft = k - rows.length - 1;
      const layersLeft = layers.length - i;
      if (row.length > 0 && grown > target && rowsLeft > 0 && layersLeft > rowsLeft) {
        rows.push(row);
        row = [];
        width = 0;
      }
      width += (row.length > 0 ? layerGap : 0) + layerW[i];
      row.push(i);
    }
    if (row.length > 0) rows.push(row);
    return rows;
  };

  // The zoom fitView would settle at, up to a shared constant: the limiting
  // side of viewport(aspect × 1) over graph bounding box.
  const fitZoomOf = (rows: number[][]): number => {
    let w = 0;
    let h = 0;
    rows.forEach((row, r) => {
      const rw =
        row.reduce((sum, i) => sum + layerW[i], 0) + layerGap * (row.length - 1);
      const rh = Math.max(...row.map((i) => layerBounds[i].height));
      w = Math.max(w, rw);
      h += rh + (r > 0 ? rowGap : 0);
    });
    return Math.min(targetAspect / w, 1 / h);
  };

  let rows = partitionFor(1);
  let bestZoom = fitZoomOf(rows);
  for (let k = 2; k <= Math.min(layers.length, 3); k++) {
    const candidate = partitionFor(k);
    if (candidate.length === rows.length) continue;
    const zoom = fitZoomOf(candidate);
    // Wrap only for a clear win, so small graphs keep the single-ribbon shape.
    if (zoom > bestZoom * 1.15) {
      rows = candidate;
      bestZoom = zoom;
    }
  }

  // ---- final positions ------------------------------------------------------
  const rowWidth = (row: number[]) =>
    row.reduce((sum, i) => sum + layerW[i], 0) + layerGap * (row.length - 1);
  const maxRowWidth = Math.max(...rows.map(rowWidth));
  let rowTop = 0;
  for (const row of rows) {
    const top = Math.min(...row.map((i) => layerBounds[i].top));
    const bottom = Math.max(...row.map((i) => layerBounds[i].bottom));
    // Centre shorter rows so a wrapped graph reads as one balanced block.
    let x = (maxRowWidth - rowWidth(row)) / 2;
    for (const i of row) {
      for (const id of layers[i]) {
        const n = size.get(id);
        if (!n) continue;
        result.set(id, {
          x: x + (layerW[i] - n.width) / 2,
          y: rowTop + ((centerY.get(id) ?? 0) - n.height / 2 - top),
        });
      }
      x += layerW[i] + layerGap;
    }
    rowTop += bottom - top + rowGap;
  }
  return result;
}
