import { test, expect } from '@playwright/test';

// ADR 0007 stream W, reconciled onto the 8-S1 store — renderer-free unit tests
// for `commitEquation`, the store action that replaced the retired
// `makeEquationCommitter` (which ran its own GET→patch→PUT queue). What must
// hold, driven as plain function calls (no browser, no JSDOM):
//  * ONE overlay entry carries the whole calc transaction: equation literal
//    written, user-typed symbol values applied, stale literals of removed
//    symbols dropped, edges into removed sockets pruned — all optimistic;
//  * the commit's derive outcome lands in `state.derived` in the same action,
//    so `derivedByNode` (the canvas's source of derived sockets) is ready the
//    frame the overlay applies — no module-local render state;
//  * persistence rides the store's EXISTING single-flight queue (one PUT of
//    `effective.graph`), acks are seq-gated, and the resolved result carries
//    the pruned edges so the shell can toast them (`pruneNotice`);
//  * a rejected PUT reverts the overlay to authoritative truth and resolves
//    the commit `ok: false` with the server's message (the editor's inline
//    error), alongside the queue's `writeError` banner.
//
// `as` casts below are test-only (allowed by the repo's TypeScript rules).

import {
  __resetForTest,
  commitEquation,
  getState,
  hydrate,
} from '../src/store/sync';
import { __resetQueueForTest } from '../src/store/queue';
import type { GraphDoc, NodeSpecs, SpecInput } from '../src/types';

// --- a controllable fetch transport ----------------------------------------

interface SentCall {
  method: string;
  url: string;
  graph: GraphDoc; // the PUT body's graph
  settle: (served: GraphDoc) => void; // resolve 200 {graph: served}
  fail: (message: string) => void; // resolve 422 {message}
}

let puts: SentCall[] = [];

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
    const parsed = init?.body ? JSON.parse(init.body as string) : {};
    return new Promise<Response>((resolve) => {
      const call: SentCall = {
        method,
        url,
        graph: parsed.graph as GraphDoc,
        settle: (served) => resolve(fakeResponse(200, { graph: served })),
        fail: (message) => resolve(fakeResponse(422, { message })),
      };
      // The advisory edit-mode validation POST is deliberately left pending —
      // it is best-effort and must not gate anything under test here.
      if (method === 'PUT') puts.push(call);
    });
  }) as typeof fetch;
}

// --- fixtures: a dynamic node with one wired + one literal symbol -----------

const OLD_EQ = 'margin = C_min - F_max + F_old';
const NEW_EQ = 'margin = C_min - safety';

const SPECS: NodeSpecs = {
  'sym.handcalc': {
    id: 'sym.handcalc',
    name: 'handcalc',
    title: 'handcalc',
    module: 'sym',
    qualname: 'handcalc',
    doc: '',
    inputs: [
      {
        name: 'lines',
        type: 'str',
        kind: 'positionalOrKeyword',
        required: false,
        default: '',
        widget: { kind: 'calc' },
      },
      {
        name: 'precision',
        type: 'int',
        kind: 'positionalOrKeyword',
        required: false,
        default: 3,
        widget: { kind: 'number' },
      },
    ],
    outputs: [{ name: 'latex', type: 'str' }],
    dynamicInputs: { param: 'lines' },
  },
};

const derivedEntry = (name: string): SpecInput => ({
  name,
  type: 'float',
  kind: 'keywordOnly',
  required: true,
  default: null,
  widget: { kind: 'number', subtype: 'float' },
  derived: true,
});

function fixtureGraph(): GraphDoc {
  return {
    version: 'v0',
    nodes: [
      { id: 'src', type: 't', inputs: {}, position: null },
      {
        id: 'steps',
        type: 'sym.handcalc',
        // F_old is an inline symbol value of the OLD equation — a stale kwarg
        // once the symbol is removed, which would fail bind if kept.
        inputs: { lines: OLD_EQ, precision: 2, F_old: 3 },
        position: null,
      },
    ],
    edges: [
      { source: 'src', sourceOutput: 'value', target: 'steps', targetInput: 'C_min' },
      { source: 'src', sourceOutput: 'value', target: 'steps', targetInput: 'F_max' },
    ],
    output: null,
  };
}

const commitNew = () =>
  commitEquation({
    nodeId: 'steps',
    param: 'lines',
    value: NEW_EQ,
    derivedInputs: [derivedEntry('C_min'), derivedEntry('safety')],
    literals: { safety: 2 },
  });

const stepsOf = (g: GraphDoc | null) => g?.nodes.find((n) => n.id === 'steps');

const tick = () => new Promise((r) => setTimeout(r, 0));

test.beforeEach(() => {
  __resetForTest();
  __resetQueueForTest();
  installFetch();
  hydrate({ version: 'v0', specs: SPECS, graph: fixtureGraph() });
});

test('the calc transaction is one optimistic overlay entry: literal + inline values written, stale symbol literal dropped, removed-socket edge pruned', async () => {
  const resultPromise = commitNew();

  // All of it reflects NOW, before any network.
  const steps = stepsOf(getState().effective.graph);
  expect(steps?.inputs.lines).toBe(NEW_EQ);
  expect(steps?.inputs.safety).toBe(2); // the user-typed inline value
  expect(steps?.inputs.precision).toBe(2); // static input literal preserved
  expect('F_old' in (steps?.inputs ?? {})).toBe(false); // stale symbol literal dropped
  // The F_max edge (its socket left the equation) is pruned; C_min survives.
  expect(getState().effective.graph?.edges).toEqual([
    { source: 'src', sourceOutput: 'value', target: 'steps', targetInput: 'C_min' },
  ]);

  await tick();
  expect(puts.length).toBe(1); // the store's own queue — no parallel committer
  puts[0].settle(puts[0].graph);
  const result = await resultPromise;
  expect(result.ok).toBe(true);
});

test('the committed derivation lands in the store in the same action (derivedByNode ready before the PUT settles)', async () => {
  const resultPromise = commitNew();

  // The canvas's derived-socket source is the store, populated synchronously.
  expect(getState().derived[`sym.handcalc\n${NEW_EQ}`]?.map((i) => i.name)).toEqual([
    'C_min',
    'safety',
  ]);
  expect(getState().derivedByNode.get('steps')?.map((i) => i.name)).toEqual(['C_min', 'safety']);

  await tick();
  puts[0].settle(puts[0].graph);
  await resultPromise;
});

test('an acked commit resolves ok with the pruned edges and sets the prune toast naming each unwired edge', async () => {
  const resultPromise = commitNew();
  await tick();
  expect(puts.length).toBe(1);
  puts[0].settle(puts[0].graph);

  const result = await resultPromise;
  expect(result.ok).toBe(true);
  expect(result.pruned).toEqual([
    { source: 'src', sourceOutput: 'value', target: 'steps', targetInput: 'F_max' },
  ]);
  expect(getState().pruneNotice).toBe('F_max removed from equation — unwired from src');
  expect(getState().pending.length).toBe(0); // seq-gated ack drained the overlay
});

test('a rejected PUT reverts the overlay to authoritative truth and resolves ok:false with the server message', async () => {
  const before = getState().graph;
  const resultPromise = commitNew();
  await tick();
  expect(puts.length).toBe(1);
  puts[0].fail("required input 'safety' is not satisfied");

  const result = await resultPromise;
  expect(result.ok).toBe(false);
  expect(result.message).toBe("required input 'safety' is not satisfied"); // the editor's inline error
  expect(result.pruned).toEqual([]);
  expect(getState().writeError).toBe("required input 'safety' is not satisfied"); // the banner too
  expect(getState().pruneNotice).toBeNull(); // nothing was unwired
  // Reverted exactly to authoritative — edges and literals restored.
  expect(getState().pending.length).toBe(0);
  expect(getState().effective.graph).toBe(before);
  expect(stepsOf(getState().effective.graph)?.inputs.lines).toBe(OLD_EQ);
  expect(getState().effective.graph?.edges.length).toBe(2);
});

test('a commit for a node that no longer exists resolves ok:false without touching the overlay', async () => {
  hydrate({ version: 'v0', specs: SPECS, graph: { ...fixtureGraph(), nodes: [], edges: [] } });
  const result = await commitEquation({
    nodeId: 'steps',
    param: 'lines',
    value: NEW_EQ,
    derivedInputs: [derivedEntry('C_min')],
  });
  expect(result.ok).toBe(false);
  expect(result.message).toContain('steps');
  expect(getState().pending.length).toBe(0);
});
