import { test, expect } from '@playwright/test';

// ADR 0008 Phase 1 (8-S1) — renderer-free unit tests for the store + write
// queue state machine (§ Checkability). These drive the store as plain function
// calls: NO browser, NO JSDOM, NO renderHook — the one seam this cannot cover is
// the single line of official React API in useSyncSelector.ts. They also CARRY
// OVER makeGraphCommitter's lost-update guarantees (serialize + rebase, review
// 0005 finding #1), which the store's single-flight coalescing queue now owns.
//
// The only external dependency is `saveGraph`'s `fetch`; it is stubbed with a
// controllable transport so responses settle/fail on command. `as` casts below
// are test-only (allowed by the repo's TypeScript rules).

import {
  __resetForTest,
  commitLiteral,
  getState,
  hydrate,
  ingestGraph,
  type SyncState,
} from '../src/store/sync';
import { __resetQueueForTest } from '../src/store/queue';
import type { GraphDoc } from '../src/types';

// --- a controllable fetch transport ----------------------------------------

interface PutCall {
  method: string;
  graph: GraphDoc; // the PUT body's graph
  settle: (served: GraphDoc) => void; // resolve 200 {graph: served}
  fail: () => void; // resolve 422 {message}
}

let calls: PutCall[] = [];

function fakeResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    json: async () => body,
  } as unknown as Response;
}

function installFetch(): void {
  calls = [];
  globalThis.fetch = ((_url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET';
    const parsed = init?.body ? JSON.parse(init.body as string) : {};
    return new Promise<Response>((resolve) => {
      calls.push({
        method,
        graph: parsed.graph as GraphDoc,
        settle: (served) => resolve(fakeResponse(200, { graph: served })),
        fail: () => resolve(fakeResponse(422, { message: 'rejected' })),
      });
    });
  }) as typeof fetch;
}

// --- fixtures ---------------------------------------------------------------

function graphWith(x: number): GraphDoc {
  return {
    version: 'v0',
    nodes: [{ id: 'n1', type: 't', inputs: { x }, position: null }],
    edges: [],
    output: null,
  };
}

const xOf = (g: GraphDoc | null): unknown => g?.nodes[0]?.inputs.x;

// Flush microtasks AND the scheduled-pump microtask deterministically.
const tick = () => new Promise((r) => setTimeout(r, 0));

test.beforeEach(() => {
  __resetForTest();
  __resetQueueForTest();
  installFetch();
  hydrate({ version: 'v0', specs: {}, graph: graphWith(0) });
});

test('a synchronous burst on one param coalesces into a single PUT with the latest value', async () => {
  commitLiteral('n1', 'x', 1);
  commitLiteral('n1', 'x', 2);

  // Overlay reflects the latest instantly (optimistic), before any network.
  expect(xOf(getState().effective.graph)).toBe(2);
  expect(calls.length).toBe(0); // pump is deferred to a microtask

  await tick();

  // ONE PUT, carrying the coalesced value — the intermediate `1` never left.
  expect(calls.length).toBe(1);
  expect(calls[0].method).toBe('PUT');
  expect(xOf(calls[0].graph)).toBe(2);

  calls[0].settle(graphWith(2));
  await tick();
  expect(getState().pending.length).toBe(0);
  expect(xOf(getState().effective.graph)).toBe(2);
});

test('writes coalesced during an in-flight PUT drop the intermediate and send only the latest', async () => {
  commitLiteral('n1', 'x', 1);
  await tick(); // PUT #1 (value 1) is now in flight
  expect(calls.length).toBe(1);
  expect(xOf(calls[0].graph)).toBe(1);

  // Two more arrive mid-flight: single-flight holds them; latest-wins coalesces.
  commitLiteral('n1', 'x', 2);
  commitLiteral('n1', 'x', 3);
  expect(calls.length).toBe(1); // no second PUT while one is in flight

  calls[0].settle(graphWith(1)); // server confirms value 1
  await tick();

  // Exactly one more PUT, carrying 3 — value 2 was dropped, never sent.
  expect(calls.length).toBe(2);
  expect(xOf(calls[1].graph)).toBe(3);
  calls[1].settle(graphWith(3));
  await tick();
  expect(getState().pending.length).toBe(0);
  expect(xOf(getState().effective.graph)).toBe(3);
});

test('acceptance is seq-gated: a response acks only the writes it carried, others survive (G2)', async () => {
  commitLiteral('n1', 'x', 1);
  await tick(); // PUT #1 snapshots + sends seq for x only
  expect(calls.length).toBe(1);

  // A different param commits while PUT #1 is in flight → its own pending write.
  // The in-flight x write stays in the overlay until acked, so pending is now 2.
  commitLiteral('n1', 'y', 7);
  expect(getState().pending.length).toBe(2); // x (in flight) + y (queued)

  // PUT #1 settles: it must drop ONLY x's write, never the un-acked y.
  calls[0].settle(graphWith(1));
  await tick();

  // y survived the ingest (seq-gate) and re-pumped as PUT #2.
  expect(calls.length).toBe(2);
  expect(calls[1].graph.nodes[0].inputs.y).toBe(7);
});

test('ingestGraph drops only the named seqs, never an unrelated newer write', () => {
  // Direct state-machine check of the seq guard, no network.
  commitLiteral('n1', 'x', 5); // seq assigned; pending length 1
  const only = getState().pending[0];
  const before = getState().rev;

  ingestGraph(graphWith(0), [only.seq - 1]); // ack a stale, non-matching seq

  expect(getState().pending.length).toBe(1); // the real write survives
  expect(getState().pending[0].seq).toBe(only.seq);
  expect(getState().rev).toBe(before + 1); // authoritative acceptance still bumped rev
});

test('a rejected PUT drops the overlay and reverts to authoritative truth (rollback)', async () => {
  commitLiteral('n1', 'x', 9);
  expect(xOf(getState().effective.graph)).toBe(9); // optimistic
  await tick();
  expect(calls.length).toBe(1);

  calls[0].fail(); // 422
  await tick();

  expect(getState().pending.length).toBe(0); // overlay gone
  expect(getState().writeError).toBeTruthy(); // banner surface set
  // Reverted exactly to authoritative — same object, original value.
  expect(getState().effective.graph).toBe(getState().graph);
  expect(xOf(getState().effective.graph)).toBe(0);
});

test('effective graph preserves untouched node identity (per-node re-render isolation, R2)', () => {
  const twoNodes: GraphDoc = {
    version: 'v0',
    nodes: [
      { id: 'a', type: 't', inputs: { x: 0 }, position: null },
      { id: 'b', type: 't', inputs: { y: 0 }, position: null },
    ],
    edges: [],
    output: null,
  };
  hydrate({ version: 'v0', specs: {}, graph: twoNodes });
  const before: SyncState = getState();
  const bBefore = before.effective.nodesById.get('b');

  commitLiteral('a', 'x', 1); // touches only node a

  const after = getState();
  // Node b's object identity is preserved → its card won't re-render.
  expect(after.effective.nodesById.get('b')).toBe(bBefore);
  // Node a's object changed and carries the optimistic value.
  expect(after.effective.nodesById.get('a')).not.toBe(before.effective.nodesById.get('a'));
  expect(after.effective.nodesById.get('a')?.inputs.x).toBe(1);
});
