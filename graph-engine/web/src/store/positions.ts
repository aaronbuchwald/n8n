// ADR 0011 stream W4 — the position-only save path, per the ADR 0008 note
// "position saves vs source-mutating saves (two consistency classes)".
//
// Node positions are presentation state: the server writes them to the
// `<module>.layout.json` sidecar and `compute_writeback` reports the `.py`
// unchanged, so a drag must NEVER rewrite Python, block a wiring save, or bump
// the run-staleness `rev`. This module is therefore deliberately NOT
// `store/queue.ts`:
//
//   * debounced — a drag emits a stream of coordinates; only the last position
//     per node id is persisted (coalesced in `queued`);
//   * sidecar-only — the PUT body is the AUTHORITATIVE graph with nothing but
//     positions patched, so the server's diff is `strategy: "unchanged"` and
//     only the sidecar is written. To keep that true, a flush DEFERS while the
//     source queue has pending writes: a body built from the authoritative
//     graph while an overlay write is un-acked would race the source save with
//     stale content (e.g. structurally delete a just-created node). Deferring
//     is not queueing — the two paths still share no lock, no coalescing key,
//     and no epoch; positions simply wait for truth to settle.
//   * rev-neutral — the response is ingested via `ingestPositions`, which
//     patches positions in place without touching `rev`, `run`, or `pending`
//     (dragging a node does not invalidate a run).

import { getState, ingestPositions, setWriteError } from './sync';
import { saveGraph } from '../api';
import type { GraphId } from '../api';

export const POSITION_SAVE_DEBOUNCE_MS = 500;

interface QueuedPositions {
  graphId: GraphId; // the entry the drags belong to; dropped on a switch
  byNode: Map<string, { x: number; y: number }>;
}

let queued: QueuedPositions | null = null;
let timer: ReturnType<typeof setTimeout> | null = null;
let inflight = false;

function schedule(delay: number): void {
  if (timer !== null) clearTimeout(timer);
  timer = setTimeout(() => {
    timer = null;
    void flushPositionSaves();
  }, delay);
}

/**
 * Record a node's final drag position (or a tidy-layout placement) for the
 * debounced sidecar save. Last position per node id wins.
 */
export function queuePositionSave(nodeId: string, position: { x: number; y: number }): void {
  const graphId = getState().graphId;
  if (queued && queued.graphId !== graphId) queued = null; // entry switched mid-debounce
  if (!queued) queued = { graphId, byNode: new Map() };
  queued.byNode.set(nodeId, { x: position.x, y: position.y });
  schedule(POSITION_SAVE_DEBOUNCE_MS);
}

/**
 * Flush the queued positions now (the debounce timer's target; also called
 * directly by tests). Single-flight within THIS path only — a source-queue PUT
 * neither blocks nor is blocked by it.
 */
export async function flushPositionSaves(): Promise<void> {
  if (inflight) return; // the in-flight flush's finally re-schedules
  const state = getState();
  if (!queued || queued.byNode.size === 0) return;
  if (queued.graphId !== state.graphId || !state.graph) {
    queued = null; // drags belong to an entry we navigated away from
    return;
  }
  if (state.pending.length > 0) {
    // Source writes are in flight/queued: the authoritative graph is behind the
    // draft, so a body built from it would write back stale content. Wait for
    // the queue to drain (positions are presentation; latency here is fine).
    schedule(POSITION_SAVE_DEBOUNCE_MS);
    return;
  }

  const { graphId, byNode } = queued;
  queued = null;
  // The authoritative graph with ONLY positions patched — structurally
  // identical to the served graph, so the server writes only the sidecar.
  const body = {
    ...state.graph,
    nodes: state.graph.nodes.map((n) => {
      const p = byNode.get(n.id);
      return p ? { ...n, position: p } : n;
    }),
  };

  inflight = true;
  try {
    await saveGraph(body, graphId);
    // Rev-neutral ingest: reflect what we persisted, nothing else. NOT
    // `ingestGraph` — that would bump `rev` and falsely stale the last run.
    if (getState().graphId === graphId) ingestPositions(byNode);
  } catch (err: unknown) {
    if (getState().graphId === graphId) {
      setWriteError(err instanceof Error ? err.message : String(err));
    }
  } finally {
    inflight = false;
    if (queued !== null) schedule(POSITION_SAVE_DEBOUNCE_MS); // drags landed mid-flight
  }
}

/** Test-only reset (paired with sync's __resetForTest). */
export function __resetPositionsForTest(): void {
  if (timer !== null) clearTimeout(timer);
  timer = null;
  queued = null;
  inflight = false;
}
