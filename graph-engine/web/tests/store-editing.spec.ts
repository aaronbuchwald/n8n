import { test, expect } from '@playwright/test';

// ADR 0011 stream W4 — renderer-free unit tests for canvas structural editing
// and the position-only save path. Same discipline as store-queue.spec.ts: the
// store is driven as plain function calls (no browser, no JSDOM); only
// `fetch` is stubbed. What must hold:
//
//  * connect / reconnect / delete are optimistic overlay writes that persist
//    through the SOURCE queue (one PUT of the whole draft graph, seq-acked);
//  * a rejected structural PUT reverts the overlay (never stuck on screen);
//  * the PUT envelope's `writeback` warning surfaces in the store and a clean
//    save clears it (ADR 0011 HD2 §4);
//  * position saves are the OTHER consistency class (ADR 0008 note): debounced,
//    coalesced per node, sidecar-only — the PUT body is structurally identical
//    to the authoritative graph (a drag can never dirty the .py), `rev` does
//    not bump (a drag never stales a run), and the path defers while source
//    writes are pending instead of racing them with stale content.
//
// `as` casts below are test-only (allowed by the repo's TypeScript rules).

import {
  __resetForTest,
  connectEdge,
  commitLiteral,
  deleteElements,
  getState,
  hydrate,
  reconnectEdge,
  setRun,
  selectRunIsStale,
} from '../src/store/sync';
import { __resetQueueForTest } from '../src/store/queue';
import { __resetPositionsForTest, flushPositionSaves, queuePositionSave } from '../src/store/positions';
import type { GraphDoc, GraphEdge } from '../src/types';
import type { RunResult, WritebackWarning } from '../src/api';

// --- a controllable fetch transport ----------------------------------------
// PUT /api/graph is captured for manual settlement; POST /api/graphs/validate
// answers immediately (edit-mode validation is advisory and out of scope here).

interface PutCall {
  graph: GraphDoc; // the PUT body's graph
  settle: (served: GraphDoc, writeback?: WritebackWarning) => void;
  fail: () => void;
}

let puts: PutCall[] = [];

function fakeResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    json: async () => body,
  } as unknown as Response;
}

function installFetch(): void {
  puts = [];
  globalThis.fetch = ((url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET';
    if (url.includes('/api/graphs/validate')) {
      return Promise.resolve(fakeResponse(200, { ok: true, warnings: [] }));
    }
    if (method === 'PUT') {
      const parsed = init?.body ? JSON.parse(init.body as string) : {};
      return new Promise<Response>((resolve) => {
        puts.push({
          graph: parsed.graph as GraphDoc,
          settle: (served, writeback) =>
            resolve(fakeResponse(200, writeback ? { graph: served, writeback } : { graph: served })),
          fail: () => resolve(fakeResponse(422, { message: 'rejected' })),
        });
      });
    }
    return Promise.resolve(fakeResponse(404, {}));
  }) as typeof fetch;
}

// --- fixtures ---------------------------------------------------------------
// a --> b (a.out -> b.val); c dangling; output on b.

const EDGE_AB: GraphEdge = { source: 'a', sourceOutput: 'out', target: 'b', targetInput: 'val' };

function fixtureGraph(): GraphDoc {
  return {
    version: 'v0',
    nodes: [
      { id: 'a', type: 't', inputs: {}, position: { x: 10, y: 20 } },
      { id: 'b', type: 't', inputs: {}, position: { x: 300, y: 20 } },
      { id: 'c', type: 't', inputs: {}, position: null },
    ],
    edges: [EDGE_AB],
    output: { node: 'b', socket: 'out' },
  };
}

const tick = () => new Promise((r) => setTimeout(r, 0));
const waitFor = async (cond: () => boolean, ms = 2000): Promise<void> => {
  const deadline = Date.now() + ms;
  while (!cond() && Date.now() < deadline) await new Promise((r) => setTimeout(r, 25));
  expect(cond()).toBe(true);
};

test.beforeEach(() => {
  __resetForTest();
  __resetQueueForTest();
  __resetPositionsForTest();
  installFetch();
  hydrate({ version: 'v0', specs: {}, graph: fixtureGraph() });
});

// --- structural edits through the source queue ------------------------------

test('connect adds the edge optimistically and persists it through one source-queue PUT', async () => {
  const edge: GraphEdge = { source: 'c', sourceOutput: 'out', target: 'b', targetInput: 'other' };
  connectEdge(edge);

  // Overlay: on the draft instantly, before any network.
  expect(getState().effective.graph?.edges).toContainEqual(edge);
  expect(puts.length).toBe(0);

  await tick();
  expect(puts.length).toBe(1);
  expect(puts[0].graph.edges).toContainEqual(edge);

  const served: GraphDoc = { ...fixtureGraph(), edges: [EDGE_AB, edge] };
  puts[0].settle(served);
  await tick();
  expect(getState().pending.length).toBe(0);
  expect(getState().effective.graph?.edges).toContainEqual(edge);
});

test('connecting onto an occupied input replaces the existing edge (D5), never double-wires', async () => {
  const replacement: GraphEdge = { source: 'c', sourceOutput: 'out', target: 'b', targetInput: 'val' };
  connectEdge(replacement);

  const draft = getState().effective.graph;
  const intoInput = draft?.edges.filter((e) => e.target === 'b' && e.targetInput === 'val');
  expect(intoInput).toEqual([replacement]); // old a->b.val edge replaced in the draft

  await tick();
  const sent = puts[0].graph.edges.filter((e) => e.target === 'b' && e.targetInput === 'val');
  expect(sent).toEqual([replacement]);
});

test('reconnect is delete + add in one gesture and ONE PUT', async () => {
  const moved: GraphEdge = { source: 'a', sourceOutput: 'out', target: 'c', targetInput: 'val' };
  reconnectEdge(EDGE_AB, moved);

  const draft = getState().effective.graph;
  expect(draft?.edges).not.toContainEqual(EDGE_AB);
  expect(draft?.edges).toContainEqual(moved);

  await tick();
  expect(puts.length).toBe(1); // both writes coalesced into a single save
  expect(puts[0].graph.edges).not.toContainEqual(EDGE_AB);
  expect(puts[0].graph.edges).toContainEqual(moved);
});

test('deleting a node cascades its edges and clears the graph output it carried (D4)', async () => {
  deleteElements(['b'], []);

  const draft = getState().effective.graph;
  expect(draft?.nodes.map((n) => n.id)).toEqual(['a', 'c']);
  expect(draft?.edges).toEqual([]); // a->b cascaded with the node
  expect(draft?.output).toBeNull(); // b carried the output

  await tick();
  expect(puts.length).toBe(1);
  expect(puts[0].graph.nodes.map((n) => n.id)).toEqual(['a', 'c']);
  expect(puts[0].graph.output).toBeNull();
});

test('a rejected structural save reverts the overlay and surfaces writeError', async () => {
  const edge: GraphEdge = { source: 'b', sourceOutput: 'out', target: 'a', targetInput: 'loop' };
  connectEdge(edge);
  await tick();
  expect(puts.length).toBe(1);

  puts[0].fail(); // e.g. the server detected a cycle / type mismatch
  await tick();

  expect(getState().pending.length).toBe(0);
  expect(getState().effective.graph?.edges).not.toContainEqual(edge); // reverted to truth
  expect(getState().writeError).toBe('rejected');
});

test('the PUT envelope writeback warning surfaces in the store and a clean save clears it', async () => {
  deleteElements([], [EDGE_AB]);
  await tick();
  const warning: WritebackWarning = {
    code: 'wiring-block-regenerated',
    message: 'Saved, but hand-written comments were not preserved.',
    droppedComments: true,
  };
  puts[0].settle({ ...fixtureGraph(), edges: [] }, warning);
  await tick();
  expect(getState().writebackWarning).toEqual(warning);

  // A subsequent lossless save clears the stale warning.
  const edge: GraphEdge = { source: 'a', sourceOutput: 'out', target: 'c', targetInput: 'val' };
  connectEdge(edge);
  await tick();
  puts[1].settle({ ...fixtureGraph(), edges: [edge] });
  await tick();
  expect(getState().writebackWarning).toBeNull();
});

// --- the position-only save path (ADR 0008 two consistency classes) ----------

test('a drag save is sidecar-only: the PUT body differs from the authoritative graph ONLY in positions', async () => {
  const before = getState();
  const revBefore = before.rev;
  setRun({ outputs: {}, order: [], output: null, errors: [] } as RunResult);
  expect(selectRunIsStale(getState())).toBe(false);

  queuePositionSave('a', { x: 111, y: 222 });
  queuePositionSave('a', { x: 123, y: 234 }); // last position per node wins
  const flushed = flushPositionSaves(); // resolves once the PUT settles below

  expect(puts.length).toBe(1);
  const body = puts[0].graph;
  const authoritative = getState().graph;
  expect(authoritative).not.toBeNull();
  // Structurally identical — same nodes/edges/output/inputs, so the server's
  // diff is `strategy: "unchanged"` and the .py is never touched…
  expect(body.edges).toEqual(authoritative?.edges);
  expect(body.output).toEqual(authoritative?.output);
  expect(body.nodes.map((n) => ({ ...n, position: null }))).toEqual(
    authoritative?.nodes.map((n) => ({ ...n, position: null })),
  );
  // …except the coalesced dragged position.
  expect(body.nodes.find((n) => n.id === 'a')?.position).toEqual({ x: 123, y: 234 });

  puts[0].settle(body);
  await flushed;
  await waitFor(() => getState().graph?.nodes.find((n) => n.id === 'a')?.position?.x === 123);

  // Rev-neutral: no rev bump, no staled run, no pending entries — ever.
  expect(getState().rev).toBe(revBefore);
  expect(selectRunIsStale(getState())).toBe(false);
  expect(getState().pending.length).toBe(0);
});

test('position saves never enter the source queue and defer while source writes are pending', async () => {
  commitLiteral('a', 'x', 42); // a source write, held un-acked (in flight)
  await tick();
  expect(puts.length).toBe(1); // the source queue's PUT

  queuePositionSave('c', { x: 7, y: 8 });
  await flushPositionSaves();
  // Deferred: the authoritative graph is behind the draft, so sending it now
  // would write back stale content. No second PUT, and crucially the position
  // was NOT folded into the source queue's overlay.
  expect(puts.length).toBe(1);
  expect(getState().pending.every((w) => w.kind === 'literal')).toBe(true);

  // The source save lands → the deferred flush retries on its own timer.
  const served: GraphDoc = {
    ...fixtureGraph(),
    nodes: fixtureGraph().nodes.map((n) => (n.id === 'a' ? { ...n, inputs: { x: 42 } } : n)),
  };
  puts[0].settle(served);
  await waitFor(() => puts.length === 2);

  // The retried position PUT carries the CONFIRMED literal — nothing stale.
  expect(puts[1].graph.nodes.find((n) => n.id === 'a')?.inputs.x).toBe(42);
  expect(puts[1].graph.nodes.find((n) => n.id === 'c')?.position).toEqual({ x: 7, y: 8 });
});
