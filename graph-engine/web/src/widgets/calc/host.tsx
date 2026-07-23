// The calc widget's shell seam (ADR 0007 D8). The plain widget commit path
// (context.tsx) writes ONE literal — enough for every other editor, but a calc
// commit is a transaction: the equation literal changes AND the node's derived
// socket set changes with it, so edges into now-removed sockets must be pruned
// in the SAME save (the server binds the graph before writing; a dangling edge
// would 422 the whole commit). The shell mounts this context next to the plain
// one; the calc editor prefers it and degrades to the plain `onCommit` when it
// is absent (e.g. an editor mounted in isolation in a test).

import { createContext, useContext } from 'react';
import { fetchLiveGraph, saveGraph, type SaveGraphResult } from '../../api';
import type { GraphDoc, GraphEdge, NodeSpecs, SpecInput } from '../../types';

/** One equation commit: the new literal plus the socket set it implies. */
export interface EquationCommitRequest {
  nodeId: string;
  /** The deriving parameter (e.g. "lines"). */
  param: string;
  /** The new equation literal. */
  value: string;
  /** Derived input names of the NEW equation — the sockets to keep. */
  derivedNames: string[];
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

export type CommitEquation = (req: EquationCommitRequest) => Promise<EquationCommitResult>;

/** Everything the calc editor needs from the shell. Null = degrade to onCommit. */
export interface CalcHost {
  graph: GraphDoc;
  specs: NodeSpecs;
  /** Per-node derived inputs for the COMMITTED literals (see useDerivedInputs). */
  derivedByNode: ReadonlyMap<string, SpecInput[]>;
  commitEquation: CommitEquation;
}

const CalcHostContext = createContext<CalcHost | null>(null);

export const CalcHostProvider = CalcHostContext.Provider;

export const useCalcHost = (): CalcHost | null => useContext(CalcHostContext);

/**
 * Build the equation committer. Mirrors `makeGraphCommitter`'s lost-update
 * safety (serialize commits, rebase each on a fresh GET) and adds the calc
 * transaction on top:
 *
 *  1. keep = static spec inputs ∪ `derivedNames` (the new equation's symbols);
 *  2. prune every edge into this node whose target socket is not kept, and drop
 *     the inline literals of removed symbols (a stale kwarg would fail bind);
 *  3. write the equation literal (+ any user-typed symbol values) and PUT.
 *
 * After a successful save, `onToast(message)` names exactly what was
 * disconnected — one line per pruned edge. A failed save (e.g. bind rejecting a
 * required symbol that is neither wired nor valued) reaches `onError` AND the
 * returned result, so the editor can show it inline; the file stays untouched.
 */
export function makeEquationCommitter(
  specs: NodeSpecs,
  onSaved: (result: SaveGraphResult) => void,
  onError: (error: Error) => void,
  onToast: (message: string) => void,
): CommitEquation {
  // Serialization point, same discipline as makeGraphCommitter: one
  // GET→patch→PUT at a time, in call order.
  let queue: Promise<unknown> = Promise.resolve();

  return (req) => {
    const run = async (): Promise<EquationCommitResult> => {
      const { graph: latest } = await fetchLiveGraph();
      const node = latest.nodes.find((n) => n.id === req.nodeId);
      if (!node) {
        throw new Error(`node '${req.nodeId}' no longer exists in the graph`);
      }
      const spec = specs[node.type];
      const keep = new Set<string>(req.derivedNames);
      for (const input of spec?.inputs ?? []) keep.add(input.name);

      const pruned = latest.edges.filter(
        (e) => e.target === req.nodeId && !keep.has(e.targetInput),
      );
      const edges =
        pruned.length > 0
          ? latest.edges.filter((e) => e.target !== req.nodeId || keep.has(e.targetInput))
          : latest.edges;

      // Keep only literals whose socket still exists, then lay the user's
      // explicit symbol values and the new equation on top.
      const inputs: Record<string, unknown> = {};
      for (const [name, literal] of Object.entries(node.inputs)) {
        if (keep.has(name)) inputs[name] = literal;
      }
      for (const [name, literal] of Object.entries(req.literals ?? {})) {
        inputs[name] = literal;
      }
      inputs[req.param] = req.value;

      const next: GraphDoc = {
        ...latest,
        edges,
        nodes: latest.nodes.map((n) => (n.id === req.nodeId ? { ...n, inputs } : n)),
      };
      const result = await saveGraph(next);
      onSaved(result);
      if (pruned.length > 0) {
        onToast(
          pruned
            .map((e) => `${e.targetInput} removed from equation — unwired from ${e.source}`)
            .join('\n'),
        );
      }
      return { ok: true, pruned };
    };

    const attempt = queue.catch(() => undefined).then(run);
    // A failure is reported below; keep the chain alive for the next commit.
    queue = attempt.catch(() => undefined);
    return attempt.catch((error: unknown) => {
      const err = error instanceof Error ? error : new Error(String(error));
      onError(err);
      return { ok: false, message: err.message, pruned: [] };
    });
  };
}
