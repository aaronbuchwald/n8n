// ADR 0008 Phase 1 (stream 8-S1) — the one client store.
//
// A single normalized source of truth for every shared surface (specs, graph,
// per-spec source, the last run) plus an optimistic overlay, stamped with a
// monotone `rev`. It is a plain vanilla object store: `getState` / `subscribe`
// / `setState`, consumed in React through `useSyncExternalStore`
// (see useSyncSelector.ts) — ZERO third-party state library (Open confirmation
// 2, re-decided 2026-07-23). It supersedes 8-P0's ad-hoc `useState` epochs in
// App.tsx: the `rev`/`runRev` stamps become `rev` + `run.forRev` here, and the
// `reloadSeq` write guard generalizes to seq-gated `ingestGraph` (below).
//
// THREE rules keep the `useSyncExternalStore` snapshot stable (its one real
// cost — see the ADR "one honest cost" section):
//   1. Single mutation funnel — ONLY this module calls `setState`; every
//      mutation is an exported named action. Everything else imports actions.
//   2. Selectors don't allocate — the derived `effective` view is computed once
//      per `setState` here (identity-preserving), never inside a selector.
//   3. No parallel state — any payload shown by >1 component enters via an
//      `ingest*` action, never component-local `useState`.

import type { GraphDoc, GraphEdge, GraphNode, NodeSpec, NodeSpecs, SpecInput } from '../types';
import type {
  GraphId,
  LiveGraph,
  RunResult,
  SaveSourceResult,
  SourceInfo,
  WorkspaceInfo,
  WritebackWarning,
} from '../api';
import { mintNodeId, validateGraphEdit, type IncompleteInputWarning } from '../api';
// queue.ts imports actions from THIS module; the cycle is safe because
// `schedulePump` is only *called* (inside commitLiteral/createNode), never at
// import time.
import { schedulePump } from './queue';

/** One optimistic literal write, awaiting server confirmation. */
export interface PendingLiteralWrite {
  seq: number; // client-assigned, monotone
  kind: 'literal';
  nodeId: string;
  param: string;
  value: unknown;
}

/** One optimistic node creation (a palette place / canvas drop, ADR 0011 W5). */
export interface PendingAddNodeWrite {
  seq: number; // client-assigned, monotone
  kind: 'addNode';
  node: GraphNode;
}

/** One optimistic edge add — a canvas connect/reconnect gesture (ADR 0011 W4).
 * Dropping onto an occupied input replaces the existing edge (D5). */
export interface PendingAddEdgeWrite {
  seq: number; // client-assigned, monotone
  kind: 'addEdge';
  edge: GraphEdge;
}

/** One optimistic edge removal — a canvas edge delete / reconnect-away (W4). */
export interface PendingRemoveEdgeWrite {
  seq: number; // client-assigned, monotone
  kind: 'removeEdge';
  edge: GraphEdge;
}

/** One optimistic node removal — a canvas node delete (W4). Incident edges
 * cascade client-side (D4); the graph output clears if this node carried it. */
export interface PendingRemoveNodeWrite {
  seq: number; // client-assigned, monotone
  kind: 'removeNode';
  nodeId: string;
}

/**
 * One optimistic equation commit (ADR 0007 D8) — a calc widget apply. It is a
 * TRANSACTION over one node: the equation literal changes AND the node's
 * derived socket set changes with it, so edges into now-removed sockets are
 * pruned and stale literals of removed symbols dropped in the SAME write (a
 * dangling edge would fail the server's bind).
 */
export interface PendingEquationWrite {
  seq: number; // client-assigned, monotone
  kind: 'equation';
  nodeId: string;
  /** The deriving parameter (e.g. "lines"). */
  param: string;
  /** The new equation literal. */
  value: string;
  /** Input names to KEEP: static spec inputs ∪ the new equation's symbols. */
  keep: readonly string[];
  /** User-typed inline values for derived symbols (never invented). */
  literals: Record<string, number>;
}

export type PendingWrite =
  | PendingLiteralWrite
  | PendingAddNodeWrite
  | PendingAddEdgeWrite
  | PendingRemoveEdgeWrite
  | PendingRemoveNodeWrite
  | PendingEquationWrite;

/** A cached source buffer, tagged with the `rev` it was fetched/served at. */
export interface StoredSource extends SourceInfo {
  rev: number;
}

/** The last run, stamped with the `rev` it executed against (epoch discipline). */
export type StampedRun = RunResult & { forRev: number };

/**
 * The authoritative graph composed with the optimistic overlay — recomputed
 * once per `setState`, reusing the object of every node the overlay didn't
 * touch so selectors reading it (and ReactFlow's memoized cards) stay stable.
 */
export interface EffectiveGraph {
  graph: GraphDoc | null;
  nodesById: ReadonlyMap<string, GraphNode>;
}

export interface SyncState {
  // --- entry-point selection (ADR 0009 D6) --------------------------------
  // The `?graph=` id everything below is scoped to. `null` = the legacy
  // unscoped routes (no catalog, or the catalog hasn't resolved yet). Set only
  // by `hydrate`, which is also the seam that resets the per-entry state below
  // when the id changes — the picker just moves this key, the store reacts.
  graphId: GraphId;
  // Whether the open source-editor buffer has diverged from its saved source —
  // the ONE volatile surface a graph switch must confirm-discard (ADR 0009 D6).
  sourceDirty: boolean;

  // --- authoritative (server-confirmed) — replaced only by ingest*/hydrate ---
  specs: NodeSpecs;
  graph: GraphDoc | null;
  version: string | null; // contract version from /api/specs
  rev: number; // bumps on every authoritative acceptance
  sources: Record<string, StoredSource>; // per-spec source cache (Gap G5)
  derived: Record<string, SpecInput[]>; // ADR 0007 seam: key `${specId}\n${literal}`
  run: StampedRun | null;
  workspace: WorkspaceInfo | null;
  // Last widget-commit rejection (A-D5 banner surface). Lives here because the
  // write queue (plain async, no React) reports it.
  writeError: string | null;
  // The latest edit-mode validation (ADR 0011 D6): one entry per unsatisfied
  // required input in the draft. The "needs wiring" badge source — W5's palette
  // status strip today, W4's canvas badges later.
  incomplete: IncompleteInputWarning[];
  // The last structural save's lossy-fallback warning (ADR 0011 HD2 §4): the
  // wiring block was regenerated and hand-written comments were dropped. Set
  // from the PUT envelope by the write queue; the canvas shows it as a banner.
  writebackWarning: WritebackWarning | null;

  // What an equation commit disconnected (ADR 0007 D8 prune-with-toast):
  // "F_max removed from equation — unwired from max_force". Transient; the
  // shell renders it as a toast and clears it after a timeout.
  pruneNotice: string | null;

  // --- optimistic overlay ---
  pending: PendingWrite[];

  // --- derived (recomputed once per setState; NEVER in a selector) ---
  effective: EffectiveGraph;
  // Derived input entries per dynamic node id (ADR 0007), resolved from
  // `derived` by each node's COMMITTED deriving literal in `effective.graph`.
  // Precomputed here (never in a selector) so the canvas reads a stored ref.
  derivedByNode: ReadonlyMap<string, SpecInput[]>;
}

const EMPTY_NODES: ReadonlyMap<string, GraphNode> = new Map();
const EMPTY_DERIVED: ReadonlyMap<string, SpecInput[]> = new Map();

const INITIAL: SyncState = {
  graphId: null,
  sourceDirty: false,
  specs: {},
  graph: null,
  version: null,
  rev: 0,
  sources: {},
  derived: {},
  run: null,
  workspace: null,
  writeError: null,
  incomplete: [],
  writebackWarning: null,
  pruneNotice: null,
  pending: [],
  effective: { graph: null, nodesById: EMPTY_NODES },
  derivedByNode: EMPTY_DERIVED,
};

function indexNodes(nodes: readonly GraphNode[]): ReadonlyMap<string, GraphNode> {
  const map = new Map<string, GraphNode>();
  for (const node of nodes) map.set(node.id, node);
  return map;
}

/**
 * Compose authoritative graph ⊕ pending writes (literals + created nodes).
 * Untouched node objects keep their identity (so `sameGraphData`/ReactFlow skip
 * them, and a per-node selector re-renders only its own card). Empty overlay →
 * the authoritative graph object is returned unchanged (max stability).
 */
function computeEffective(graph: GraphDoc | null, pending: readonly PendingWrite[]): EffectiveGraph {
  if (!graph) return { graph: null, nodesById: EMPTY_NODES };
  if (pending.length === 0) return { graph, nodesById: indexNodes(graph.nodes) };

  // Latest value per (nodeId, param). `pending` is already coalesced per key,
  // but one node can carry pending writes on several params.
  const overrides = new Map<string, Map<string, unknown>>();
  for (const write of pending) {
    if (write.kind !== 'literal') continue;
    let byParam = overrides.get(write.nodeId);
    if (!byParam) {
      byParam = new Map();
      overrides.set(write.nodeId, byParam);
    }
    byParam.set(write.param, write.value);
  }

  let nodes = graph.nodes.map((node) => {
    const byParam = overrides.get(node.id);
    if (!byParam) return node; // identity preserved — untouched card won't re-render
    const inputs = { ...node.inputs };
    for (const [param, value] of byParam) inputs[param] = value;
    return { ...node, inputs };
  });

  // Structural writes replay chronologically over the authoritative topology,
  // so a reconnect (removeEdge then addEdge) or a create-then-delete composes
  // the way the gestures happened. The addNode id guard covers the window where
  // the authoritative graph already contains the node (the PUT landed) but its
  // overlay entry has not been acked/dropped yet.
  let edges = graph.edges;
  let output = graph.output;
  for (const write of pending) {
    switch (write.kind) {
      case 'literal':
        break; // folded above
      case 'addNode':
        if (!nodes.some((n) => n.id === write.node.id)) nodes = [...nodes, write.node];
        break;
      case 'removeNode':
        nodes = nodes.filter((n) => n.id !== write.nodeId);
        // Client-side cascade (D4): incident edges go with the node…
        edges = edges.filter((e) => e.source !== write.nodeId && e.target !== write.nodeId);
        // …and the graph output clears if this node carried it.
        if (output?.node === write.nodeId) output = null;
        break;
      case 'addEdge':
        // An input is wired by at most one edge (D5): dropping onto an occupied
        // input replaces the existing edge rather than double-wiring it.
        edges = [
          ...edges.filter(
            (e) => !(e.target === write.edge.target && e.targetInput === write.edge.targetInput),
          ),
          write.edge,
        ];
        break;
      case 'removeEdge':
        edges = edges.filter((e) => !sameEdge(e, write.edge));
        break;
      case 'equation': {
        // The calc transaction (ADR 0007 D8): prune edges into sockets the new
        // equation no longer derives, drop stale literals of removed symbols
        // (a stale kwarg would fail bind), then lay the user's explicit symbol
        // values and the new equation literal on top.
        const keep = new Set(write.keep);
        edges = edges.filter((e) => e.target !== write.nodeId || keep.has(e.targetInput));
        nodes = nodes.map((n) => {
          if (n.id !== write.nodeId) return n;
          const inputs: Record<string, unknown> = {};
          for (const [name, literal] of Object.entries(n.inputs)) {
            if (keep.has(name)) inputs[name] = literal;
          }
          for (const [name, literal] of Object.entries(write.literals)) inputs[name] = literal;
          inputs[write.param] = write.value;
          return { ...n, inputs };
        });
        break;
      }
    }
  }
  const effectiveGraph: GraphDoc = { ...graph, nodes, edges, output };
  return { graph: effectiveGraph, nodesById: indexNodes(nodes) };
}

/** Edge identity: all four endpoints match. */
function sameEdge(a: GraphEdge, b: GraphEdge): boolean {
  return (
    a.source === b.source &&
    a.sourceOutput === b.sourceOutput &&
    a.target === b.target &&
    a.targetInput === b.targetInput
  );
}

/** The `derived` cache key for a dynamic spec + committed literal (ADR 0007). */
export function derivedKeyOf(specId: string, literal: string): string {
  return `${specId}\n${literal}`;
}

/**
 * The committed deriving literal of `node`, when its spec is dynamic: the bound
 * literal, else the deriving param's declared default. Null for non-dynamic
 * nodes or a non-string value (the deriving param is a literal by construction,
 * ADR 0007 D2 — anything else would 422 at derive, so the static spec renders).
 */
export function dynamicLiteralOf(node: GraphNode, spec: NodeSpec | undefined): string | null {
  const param = spec?.dynamicInputs?.param;
  if (!spec || !param) return null;
  const literal = Object.prototype.hasOwnProperty.call(node.inputs, param)
    ? node.inputs[param]
    : spec.inputs.find((i) => i.name === param)?.default;
  return typeof literal === 'string' ? literal : null;
}

/**
 * Resolve each dynamic node's derived input entries from the `derived` cache by
 * its committed literal in the (effective) graph. Nodes whose derivation is
 * missing (not yet fetched, or failed) are absent — the canvas then renders the
 * static spec, keeping existing wires on screen (ADR 0007 honesty analysis: a
 * derive failure never drops sockets).
 */
function computeDerivedByNode(
  graph: GraphDoc | null,
  specs: NodeSpecs,
  derived: Record<string, SpecInput[]>,
): ReadonlyMap<string, SpecInput[]> {
  if (!graph) return EMPTY_DERIVED;
  let map: Map<string, SpecInput[]> | null = null;
  for (const node of graph.nodes) {
    const literal = dynamicLiteralOf(node, specs[node.type]);
    if (literal === null) continue;
    const entries = derived[derivedKeyOf(node.type, literal)];
    if (!entries || entries.length === 0) continue;
    (map ??= new Map()).set(node.id, entries);
  }
  return map ?? EMPTY_DERIVED;
}

let state: SyncState = INITIAL;
const listeners = new Set<() => void>();

/** The current snapshot. Plain-async code (the write queue) reads it directly. */
export function getState(): SyncState {
  return state;
}

/** Subscribe to every mutation. Returns an unsubscribe fn (useSyncExternalStore). */
export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

// The ONLY mutation funnel. Recomputes `effective` (and the `derivedByNode`
// view that reads it) exactly when their inputs change, so snapshots stay
// referentially stable across mutations that touch neither (e.g. setRun).
function setState(patch: Partial<SyncState>): void {
  const next: SyncState = { ...state, ...patch };
  if (next.graph !== state.graph || next.pending !== state.pending) {
    next.effective = computeEffective(next.graph, next.pending);
  }
  if (
    next.effective !== state.effective ||
    next.specs !== state.specs ||
    next.derived !== state.derived
  ) {
    next.derivedByNode = computeDerivedByNode(next.effective.graph, next.specs, next.derived);
  }
  state = next;
  for (const listener of listeners) listener();
}

let seqCounter = 0;
const nextSeq = (): number => ++seqCounter;

// --- per-write outcome waiters ----------------------------------------------
// An action that needs the server's verdict on ONE write (the calc editor's
// inline commit error, ADR 0007 D8) registers a waiter on its seq. Settled by
// the same seq-gated paths that maintain the overlay: `ingestGraph` acks
// resolve ok, `rejectWrite` resolves with the queue's failure message, and an
// entry switch (`hydrate`) settles everything left — a waiter can never
// outlive the write it watches.

interface WriteOutcome {
  ok: boolean;
  message?: string;
}

const writeWaiters = new Map<number, (outcome: WriteOutcome) => void>();

function awaitWrite(seq: number): Promise<WriteOutcome> {
  return new Promise((resolve) => writeWaiters.set(seq, resolve));
}

function settleWrites(seqs: Iterable<number>, outcome: WriteOutcome): void {
  for (const seq of seqs) {
    const waiter = writeWaiters.get(seq);
    if (waiter) {
      writeWaiters.delete(seq);
      waiter(outcome);
    }
  }
}

/** Latest value wins per (nodeId, param): drop the superseded write, append the new. */
function coalesce(pending: readonly PendingWrite[], next: PendingLiteralWrite): PendingWrite[] {
  const kept = pending.filter(
    (w) => w.kind !== 'literal' || w.nodeId !== next.nodeId || w.param !== next.param,
  );
  kept.push(next);
  return kept;
}

// --- actions (the single mutation funnel; also the future CRDT seam, Part 3) --

/**
 * Boot, explicit refresh, or an entry-point switch (ADR 0009 D6): adopt the
 * served palette + graph as the new truth, scoped to `graphId` (`null` = the
 * unscoped/default entry). This is the seam the picker drives: it never
 * touches the canvas itself, only the id passed here on the next call.
 *
 * A CHANGE of `graphId` also resets every per-entry cache — the previous
 * entry's source buffers, pending literal writes, run/export results, and any
 * write-error banner are meaningless for the newly selected program (D6:
 * "run/export panels ... cleared on switch"; an in-flight write for the old
 * entry must never land against the new one). Re-hydrating the SAME id (a
 * plain refresh) leaves them alone.
 */
export function hydrate(live: LiveGraph, graphId: GraphId = null): void {
  const switchingEntry = graphId !== state.graphId;
  // The overlay is reset below, so an in-flight write for the old entry can
  // never land — settle its waiters instead of leaving them pending forever.
  if (switchingEntry) settleWrites([...writeWaiters.keys()], { ok: false, message: 'switched graphs' });
  setState({
    specs: live.specs,
    graph: live.graph,
    version: live.version,
    graphId,
    rev: state.rev + 1,
    ...(switchingEntry
      ? {
          sources: {},
          derived: {},
          pending: [],
          run: null,
          writeError: null,
          sourceDirty: false,
          incomplete: [],
          writebackWarning: null,
          pruneNotice: null,
        }
      : {}),
  });
}

/**
 * Accept an authoritative graph (a PUT /api/graph or PUT /api/source response,
 * or — phase 2 — an SSE push). Seq-gated: only the writes named in `ackSeqs`
 * drop from the overlay, so a late/out-of-order response can never clobber a
 * newer optimistic value (generalizes 8-P0's `reloadSeq` guard; kills Gap G2).
 */
export function ingestGraph(graph: GraphDoc, ackSeqs: readonly number[] = []): void {
  const acked = new Set(ackSeqs);
  setState({
    graph,
    rev: state.rev + 1,
    pending: state.pending.filter((w) => !acked.has(w.seq)),
  });
  settleWrites(ackSeqs, { ok: true });
}

/** A GET /api/source landed (SourceEditor mount): cache it, tagged at current rev. */
export function ingestSource(info: SourceInfo): void {
  setState({ sources: { ...state.sources, [info.specId]: { ...info, rev: state.rev } } });
}

/**
 * A source save landed (PUT /api/source). The response carries the
 * re-introspected `spec`, the fresh source, AND the re-projected `graph`
 * (ADR 0008 G3 — "writes return truth") — ingest all three from the one
 * response, no follow-up GET (Gap G4). Bumps `rev`, so run-derived views read
 * as stale (Gap G1) and a signature change re-lays-out the card (Gap G6).
 */
export function ingestSourceSave(result: SaveSourceResult): void {
  const patch: Partial<SyncState> = {
    specs: { ...state.specs, [result.spec.id]: result.spec },
    sources: { ...state.sources, [result.specId]: { ...result, rev: state.rev + 1 } },
    rev: state.rev + 1,
  };
  if (result.graph) patch.graph = result.graph;
  setState(patch);
}

/** ADR 0007 seam: cache derived sockets for `(specId, literal)` (self-invalidating key). */
export function ingestDerived(specId: string, literal: string, inputs: SpecInput[]): void {
  setState({ derived: { ...state.derived, [`${specId}\n${literal}`]: inputs } });
}

/**
 * Optimistically bind a literal on a node (a widget commit). The overlay makes
 * every view reflect it NOW; the write queue persists it (single-flight,
 * coalescing) and confirms via `ingestGraph`. Replaces makeGraphCommitter.
 */
export function commitLiteral(nodeId: string, param: string, value: unknown): void {
  setState({
    pending: coalesce(state.pending, { seq: nextSeq(), kind: 'literal', nodeId, param, value }),
    writeError: null,
  });
  schedulePump();
}

/** One equation commit (ADR 0007 D8): the new literal plus the sockets it implies. */
export interface EquationCommitRequest {
  nodeId: string;
  /** The deriving parameter (e.g. "lines"). */
  param: string;
  /** The new equation literal. */
  value: string;
  /** The NEW equation's derived input entries (the editor's server-verified
   * derive outcome for exactly this value) — the sockets to keep. */
  derivedInputs: SpecInput[];
  /**
   * Inline values the user typed for derived symbols in the editor (typically
   * freshly-added ones, so the save can bind — required semantics, ADR 0007 #5).
   * Never invented by the client: only what the user explicitly entered.
   */
  literals?: Record<string, number>;
}

export interface EquationCommitResult {
  ok: boolean;
  /** Human-readable failure (e.g. the server's bind error) when `ok` is false. */
  message?: string;
  /** Edges the commit pruned (targets removed from the equation). */
  pruned: GraphEdge[];
}

/**
 * Commit a dynamic node's equation (the calc widget's apply — ADR 0007 D8).
 * Replaces the retired `makeEquationCommitter`: ONE optimistic overlay entry
 * carries the whole transaction — prune edges into now-removed sockets, drop
 * stale literals of removed symbols, write the equation literal plus any
 * user-typed symbol values — and the store's existing single-flight queue
 * persists it (`PUT effective.graph`, seq-gated ack via `ingestGraph`,
 * revert + `writeError` on rejection). No second commit path, no rebase GET:
 * the store is the rebase base.
 *
 * The editor's derive outcome for the committed value is ingested into
 * `derived` FIRST, so the canvas folds the new socket set in the same frame
 * the overlay applies — derived sockets render from the store, nowhere else.
 *
 * Resolves once the server answered this write: `{ok: true, pruned}` on ack
 * (setting the prune-toast when edges were unwired), `{ok: false, message}`
 * on rejection — so the editor can show the failure inline (A-D5 keeps the
 * banner too, via the queue's `writeError`).
 */
export async function commitEquation(req: EquationCommitRequest): Promise<EquationCommitResult> {
  const draft = state.effective.graph;
  const node = draft?.nodes.find((n) => n.id === req.nodeId) ?? null;
  if (!draft || !node) {
    return { ok: false, message: `node '${req.nodeId}' no longer exists in the graph`, pruned: [] };
  }

  // keep = static spec inputs ∪ the new equation's symbols.
  const keep = req.derivedInputs.map((i) => i.name);
  for (const input of state.specs[node.type]?.inputs ?? []) keep.push(input.name);
  const keepSet = new Set(keep);
  const pruned = draft.edges.filter((e) => e.target === req.nodeId && !keepSet.has(e.targetInput));

  // The commit's own (server-verified) derivation IS the committed derivation:
  // land it in the store before the overlay applies, so the canvas never shows
  // a frame with the new literal but the old (or no) socket set.
  ingestDerived(node.type, req.value, req.derivedInputs);

  const seq = nextSeq();
  setState({
    pending: [
      ...state.pending,
      {
        seq,
        kind: 'equation',
        nodeId: req.nodeId,
        param: req.param,
        value: req.value,
        keep,
        literals: req.literals ?? {},
      },
    ],
    writeError: null,
  });
  schedulePump();
  // Advisory badge refresh (D6): a new symbol left unwired/unvalued badges
  // "needs wiring" instead of blocking the save.
  void refreshEditValidation();

  const outcome = await awaitWrite(seq);
  if (outcome.ok && pruned.length > 0) {
    setPruneNotice(
      pruned
        .map((e) => `${e.targetInput} removed from equation — unwired from ${e.source}`)
        .join('\n'),
    );
  }
  return outcome.ok
    ? { ok: true, pruned }
    : { ok: false, message: outcome.message, pruned: [] };
}

/** Surface (or clear) the equation commit's prune toast (ADR 0007 D8). */
export function setPruneNotice(notice: string | null): void {
  if (notice !== state.pruneNotice) setState({ pruneNotice: notice });
}

/**
 * Create a node of registered spec `type` at canvas `position` — THE W5→W4
 * CONTRACT (ADR 0011). W5's palette calls it on click-to-place today; 11-W4's
 * canvas calls the SAME action on drag-drop, passing the drop position. Flow:
 *
 *   1. `POST /api/graph/mint-id {type}` mints a collision-free id (HD4 —
 *      server-assisted, because the collision set lives in the module).
 *   2. The node `{id, type, inputs: {}, position}` enters the optimistic
 *      overlay, so every surface shows it immediately.
 *   3. The write queue persists it through the store's normal funnel
 *      (`PUT /api/graph`, single-flight, seq-gated ack via `ingestGraph` —
 *      D2: whole-graph save, the server diffs and splices one line in).
 *   4. Edit-mode validation (`mode:"edit"`, D6) refreshes `incomplete`, so the
 *      node's unwired required inputs badge "needs wiring" instead of erroring
 *      (bind-partial tolerates them; validation is advisory and never blocks
 *      the save).
 *
 * Resolves with the minted id once the node is in the store (persistence
 * continues in the queue; a failed PUT reverts the overlay and surfaces
 * `writeError`, like any write). Rejects — after surfacing `writeError` — only
 * when the id could not be minted: in that case nothing was added.
 */
export async function createNode(
  type: string,
  position: { x: number; y: number },
): Promise<{ id: string }> {
  let id: string;
  try {
    id = await mintNodeId(type);
  } catch (err: unknown) {
    setWriteError(err instanceof Error ? err.message : String(err));
    throw err;
  }
  const node: GraphNode = { id, type, inputs: {}, position };
  setState({
    pending: [...state.pending, { seq: nextSeq(), kind: 'addNode', node }],
    writeError: null,
  });
  schedulePump();

  // Advisory badge refresh on the draft that now includes the node.
  const draft = state.effective.graph;
  if (draft) {
    try {
      ingestEditValidation(await validateGraphEdit(draft));
    } catch {
      // Best-effort: a failed validation never blocks creation/persistence.
    }
  }
  return { id };
}

/** Adopt the latest edit-mode validation result (the "needs wiring" source). */
export function ingestEditValidation(warnings: IncompleteInputWarning[]): void {
  setState({ incomplete: warnings });
}

/**
 * Re-run edit-mode validation over the current draft and refresh `incomplete`.
 * Advisory and best-effort (D6): a validation failure never blocks or reverts
 * the optimistic edit — the save queue is the authority, and a genuinely
 * broken graph is rejected there (revert + `writeError`).
 */
async function refreshEditValidation(): Promise<void> {
  const draft = state.effective.graph;
  if (!draft) return;
  try {
    ingestEditValidation(await validateGraphEdit(draft));
  } catch {
    // Hard validate errors (cycle, unknown socket) surface via the queue's PUT.
  }
}

/**
 * Wire `edge.source`'s output into `edge.target`'s input — a completed canvas
 * connect gesture (ADR 0011 W4, D5). Optimistic overlay first, then the store's
 * single-flight source queue persists the whole graph (`PUT .../graph`, D2);
 * a server rejection (cycle, type mismatch) reverts the overlay and surfaces
 * the structured error on `writeError`. Edit-mode validation refreshes the
 * "needs wiring" badges alongside (advisory, non-blocking).
 */
export function connectEdge(edge: GraphEdge): void {
  setState({
    pending: [...state.pending, { seq: nextSeq(), kind: 'addEdge', edge }],
    writeError: null,
  });
  schedulePump();
  void refreshEditValidation();
}

/**
 * Move one end of an existing edge to a new socket — delete + add in ONE
 * gesture and one save (D5). Both writes enter the overlay in a single
 * mutation, so the pump's microtask coalesces them into one PUT.
 */
export function reconnectEdge(oldEdge: GraphEdge, newEdge: GraphEdge): void {
  setState({
    pending: [
      ...state.pending,
      { seq: nextSeq(), kind: 'removeEdge', edge: oldEdge },
      { seq: nextSeq(), kind: 'addEdge', edge: newEdge },
    ],
    writeError: null,
  });
  schedulePump();
  void refreshEditValidation();
}

/**
 * Delete nodes and/or edges from the canvas (D4). One mutation → one save:
 * node removals cascade their incident edges in the overlay (and clear the
 * graph output if a removed node carried it); the server's structural
 * write-back splices the statements out (11-W2, attached-comment policy).
 */
export function deleteElements(nodeIds: readonly string[], edges: readonly GraphEdge[]): void {
  if (nodeIds.length === 0 && edges.length === 0) return;
  const removed = new Set(nodeIds);
  const writes: PendingWrite[] = [];
  for (const nodeId of nodeIds) writes.push({ seq: nextSeq(), kind: 'removeNode', nodeId });
  for (const edge of edges) {
    // Skip edges a removeNode already cascades — no redundant overlay entries.
    if (removed.has(edge.source) || removed.has(edge.target)) continue;
    writes.push({ seq: nextSeq(), kind: 'removeEdge', edge });
  }
  if (writes.length === 0) return;
  setState({ pending: [...state.pending, ...writes], writeError: null });
  schedulePump();
  void refreshEditValidation();
}

/**
 * Adopt persisted node positions — the position-only save path's ingest
 * (ADR 0008 position-save note; stream 11-W4). DELIBERATELY rev-neutral: it
 * patches `graph.nodes[].position` in place and touches nothing else — no
 * `rev` bump (a drag must never stale a run), no `pending` change (it never
 * enters the source queue), no `run`/`incomplete` change. Positions are
 * presentation state living in the `*.layout.json` sidecar, not the `.py`.
 */
export function ingestPositions(positions: ReadonlyMap<string, { x: number; y: number }>): void {
  if (!state.graph || positions.size === 0) return;
  const nodes = state.graph.nodes.map((n) => {
    const p = positions.get(n.id);
    return p ? { ...n, position: { x: p.x, y: p.y } } : n;
  });
  setState({ graph: { ...state.graph, nodes } });
}

/** Surface (or clear) the structural save's lossy-fallback warning (HD2 §4). */
export function setWritebackWarning(warning: WritebackWarning | null): void {
  if (warning !== state.writebackWarning) setState({ writebackWarning: warning });
}

/** The server rejected (or never heard) a write: drop the overlay → revert to
 * truth. `message` (the queue's failure) settles any waiter on this write. */
export function rejectWrite(seq: number, message?: string): void {
  setState({ pending: state.pending.filter((w) => w.seq !== seq) });
  settleWrites([seq], { ok: false, message });
}

/** Surface a write failure on the banner (or clear it with null). */
export function setWriteError(message: string | null): void {
  setState({ writeError: message });
}

/**
 * The open source-editor buffer diverged from (or returned to) its saved
 * source. The one thing App's switch-graph guard reads (ADR 0009 D6) — kept
 * in the store rather than threaded through GraphView/NodeInspector props, so
 * the picker's dirty check is a plain selector like everything else it reads.
 */
export function setSourceDirty(dirty: boolean): void {
  if (dirty !== state.sourceDirty) setState({ sourceDirty: dirty });
}

/** A run finished: stamp it with the rev it executed against. */
export function setRun(run: RunResult): void {
  setState({ run: { ...run, forRev: state.rev } });
}

/** Dismiss the run (Escape / close). */
export function clearRun(): void {
  setState({ run: null });
}

/** Cache the git/workspace badge info (was BranchBadge's private fetch, Gap G5). */
export function setWorkspace(info: WorkspaceInfo): void {
  setState({ workspace: info });
}

// --- derived selectors (pure reads over the snapshot; safe in useSyncSelector) ---

/**
 * The last run's values predate what the user now sees — either an
 * authoritative edit landed since it ran (`forRev !== rev`) or an optimistic
 * write is in flight (`pending`). Every run-derived surface renders honestly
 * stale instead of mixing epochs (Gap G1). Returns a primitive boolean, so it
 * is snapshot-stable.
 */
export function selectRunIsStale(s: SyncState): boolean {
  return s.run !== null && (s.run.forRev !== s.rev || s.pending.length > 0);
}

/** The node an engine run error points at (marked on the canvas), if any. */
export function selectErrorNodeId(s: SyncState): string | null {
  return s.run?.errors.find((e) => e.nodeId)?.nodeId ?? null;
}

// Test-only reset so renderer-free unit specs start from a clean store.
export function __resetForTest(): void {
  state = INITIAL;
  listeners.clear();
  writeWaiters.clear();
  seqCounter = 0;
}
