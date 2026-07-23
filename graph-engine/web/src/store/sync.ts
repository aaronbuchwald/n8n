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

import type { GraphDoc, GraphNode, NodeSpecs, SpecInput } from '../types';
import type { GraphId, LiveGraph, RunResult, SaveSourceResult, SourceInfo, WorkspaceInfo } from '../api';
// queue.ts imports actions from THIS module; the cycle is safe because
// `schedulePump` is only *called* (inside commitLiteral), never at import time.
import { schedulePump } from './queue';

/** One optimistic literal write, awaiting server confirmation. */
export interface PendingWrite {
  seq: number; // client-assigned, monotone
  kind: 'literal'; // v1: widget commits only; source saves are not optimistic
  nodeId: string;
  param: string;
  value: unknown;
}

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

  // --- optimistic overlay ---
  pending: PendingWrite[];

  // --- derived (recomputed once per setState; NEVER in a selector) ---
  effective: EffectiveGraph;
}

const EMPTY_NODES: ReadonlyMap<string, GraphNode> = new Map();

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
  pending: [],
  effective: { graph: null, nodesById: EMPTY_NODES },
};

function indexNodes(nodes: readonly GraphNode[]): ReadonlyMap<string, GraphNode> {
  const map = new Map<string, GraphNode>();
  for (const node of nodes) map.set(node.id, node);
  return map;
}

/**
 * Compose authoritative graph ⊕ pending literals. Untouched node objects keep
 * their identity (so `sameGraphData`/ReactFlow skip them, and a per-node
 * selector re-renders only its own card). Empty overlay → the authoritative
 * graph object is returned unchanged (max stability).
 */
function computeEffective(graph: GraphDoc | null, pending: readonly PendingWrite[]): EffectiveGraph {
  if (!graph) return { graph: null, nodesById: EMPTY_NODES };
  if (pending.length === 0) return { graph, nodesById: indexNodes(graph.nodes) };

  // Latest value per (nodeId, param). `pending` is already coalesced per key,
  // but one node can carry pending writes on several params.
  const overrides = new Map<string, Map<string, unknown>>();
  for (const write of pending) {
    let byParam = overrides.get(write.nodeId);
    if (!byParam) {
      byParam = new Map();
      overrides.set(write.nodeId, byParam);
    }
    byParam.set(write.param, write.value);
  }

  const nodes = graph.nodes.map((node) => {
    const byParam = overrides.get(node.id);
    if (!byParam) return node; // identity preserved — untouched card won't re-render
    const inputs = { ...node.inputs };
    for (const [param, value] of byParam) inputs[param] = value;
    return { ...node, inputs };
  });
  const effectiveGraph: GraphDoc = { ...graph, nodes };
  return { graph: effectiveGraph, nodesById: indexNodes(nodes) };
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

// The ONLY mutation funnel. Recomputes `effective` exactly when its inputs
// (authoritative graph or the overlay) change, so snapshots stay referentially
// stable across mutations that touch neither (e.g. setRun).
function setState(patch: Partial<SyncState>): void {
  const next: SyncState = { ...state, ...patch };
  if (next.graph !== state.graph || next.pending !== state.pending) {
    next.effective = computeEffective(next.graph, next.pending);
  }
  state = next;
  for (const listener of listeners) listener();
}

let seqCounter = 0;
const nextSeq = (): number => ++seqCounter;

/** Latest value wins per (nodeId, param): drop the superseded write, append the new. */
function coalesce(pending: readonly PendingWrite[], next: PendingWrite): PendingWrite[] {
  const kept = pending.filter((w) => w.nodeId !== next.nodeId || w.param !== next.param);
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
  setState({
    specs: live.specs,
    graph: live.graph,
    version: live.version,
    graphId,
    rev: state.rev + 1,
    ...(switchingEntry
      ? { sources: {}, derived: {}, pending: [], run: null, writeError: null, sourceDirty: false }
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

/** The server rejected (or never heard) a write: drop the overlay → revert to truth. */
export function rejectWrite(seq: number): void {
  setState({ pending: state.pending.filter((w) => w.seq !== seq) });
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
  seqCounter = 0;
}
