// ADR 0008 Phase 1 — the single-flight write queue. Plain async module, ZERO
// React: it reads the store (the rebase base) and writes the response back
// (`ingestGraph`) directly — the whole reason the store is readable outside the
// component tree (constraint R1). Replaces `makeGraphCommitter`'s per-instance
// serialized queue + rebase-GET; its lost-update guarantees carry over as
// renderer-free unit tests (tests/store-queue.spec.ts).
//
// Invariants (each closes a diagnosed gap by construction):
//   * single-flight — one PUT at a time (`inflight` latch), so a slow response
//     can never land after a newer one and clobber it;
//   * store is the rebase base — the PUT body is `effective.graph`
//     (authoritative ⊕ overlay). The client is the only writer on this path, so
//     no pre-PUT GET is needed (Gap G4);
//   * seq-gated acceptance — only the writes we actually sent are acked and
//     dropped; anything coalesced in mid-flight survives and re-pumps (Gap G2);
//   * rejection reverts — a failed PUT drops the overlay entry rather than
//     patching state, so a rejected value is never left on screen (never stuck).

import { getState, ingestGraph, rejectWrite, setWriteError, setWritebackWarning } from './sync';
import { saveGraph } from '../api';

let inflight = false;
let scheduled = false;

/**
 * Entry point from `commitLiteral`. Defers the pump to a microtask so a
 * SYNCHRONOUS burst of commits (or several commits landing in one task)
 * coalesces into a single PUT carrying only the latest value per key — the
 * server never sees a dropped intermediate (Open confirmation 8). During an
 * in-flight PUT this is a no-op; `pump`'s own finally re-drains what arrived.
 */
export function schedulePump(): void {
  if (scheduled || inflight) return;
  scheduled = true;
  queueMicrotask(() => {
    scheduled = false;
    void pump();
  });
}

/**
 * Drain the optimistic overlay to the server. Coalescing already happened in
 * `commitLiteral` (latest-wins per (nodeId, param)); this sends one PUT for the
 * whole current overlay, then re-pumps if writes arrived while it was in flight.
 */
export async function pump(): Promise<void> {
  if (inflight) return;
  const snapshot = getState();
  const { effective, pending } = snapshot;
  if (!effective.graph || pending.length === 0) return;

  inflight = true;
  // Snapshot exactly what this PUT carries, so acceptance acks precisely these.
  const seqs = pending.map((w) => w.seq);
  const body = effective.graph; // authoritative ⊕ overlay — the rebase base
  const graphId = snapshot.graphId; // the entry this overlay belongs to (ADR 0009)
  try {
    const result = await saveGraph(body, graphId);
    // The user may have switched entries while this PUT was in flight — `hydrate`
    // already reset `pending`/`graph` for the new one, so a stale response here
    // must never land on top of it (it belongs to an entry we've navigated away
    // from, not the one now on screen).
    if (getState().graphId === graphId) {
      ingestGraph(result.graph, seqs);
      // ADR 0011 HD2 §4 — a structural save that fell back to regenerating the
      // wiring block rides a top-level `writeback` warning on the envelope;
      // surface it (and clear a stale one after a clean save).
      setWritebackWarning(result.writeback ?? null);
    }
  } catch (err: unknown) {
    if (getState().graphId === graphId) {
      const message = err instanceof Error ? err.message : String(err);
      // Overlay dropped → instant revert to truth; the message also settles any
      // per-write waiter (the calc editor's inline commit error, ADR 0007 D8).
      for (const seq of seqs) rejectWrite(seq, message);
      setWriteError(message);
    }
  } finally {
    inflight = false;
    // Writes coalesced during the flight (or after a rejection) still pending.
    if (getState().pending.length > 0) void pump();
  }
}

/** Test-only reset of the queue latches (paired with sync's __resetForTest). */
export function __resetQueueForTest(): void {
  inflight = false;
  scheduled = false;
}
