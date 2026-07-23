// The commit seam (ADR 0005 A-D5). An editor's `onCommit(next)` ultimately
// writes the literal into the graph and PUTs /api/graph — the *existing*
// endpoint, no new RPC. That write is the shell's job, so the slot reads it from
// context: when no provider is mounted the canvas stays read-only (today's
// behavior) and no editors appear.

import { createContext, useContext } from 'react';
import type { GraphDoc } from '../types';
import { fetchLiveGraph, saveGraph, type SaveGraphResult } from '../api';

/** Commit one input's literal on a node. Provided by the shell; null = read-only. */
export type CommitInput = (nodeId: string, param: string, value: unknown) => void;

const WidgetEditingContext = createContext<CommitInput | null>(null);

/** Wrap the canvas to enable widget editing. Value is a {@link CommitInput}. */
export const WidgetEditingProvider = WidgetEditingContext.Provider;

/** The active commit function, or null when the canvas is read-only. */
export const useWidgetCommit = (): CommitInput | null => useContext(WidgetEditingContext);

/**
 * Build a {@link CommitInput} that writes the literal into a graph node's
 * `inputs` and persists via `PUT /api/graph` (A-D5). The value rides an ordinary
 * literal — the server rewrites the composite's wiring line and reparses it
 * (the round-trip proof), so `onSaved` receives the re-served graph. The shell
 * ingests that `SaveGraphResult.graph` straight into its state — no post-commit
 * reload (ADR 0008 Phase 0, G4): the PUT response IS the authoritative graph.
 *
 * **Lost-update safety (review 0005, finding #1).** A naive committer PUTs a
 * whole-graph snapshot captured at the last reload. Two quick edits on
 * different widgets then race: both diff against the *same* stale snapshot, and
 * whichever PUT lands last silently reverts the other's field. Two mechanisms
 * remove that dependency:
 *   1. **Serialize** — every commit from this committer chains onto one internal
 *      promise (`queue`), so at most one GET→patch→PUT runs at a time, in call
 *      order; a slow PUT can no longer finish after and clobber a later one.
 *   2. **Rebase before each PUT** — immediately before writing, GET the freshest
 *      served graph (`fetchLiveGraph` → `/api/graph`) and patch *only* the one
 *      changed literal onto it. Each commit therefore reads the graph the server
 *      actually holds — including the field the previous queued commit just
 *      wrote — so no PUT is ever built on a stale snapshot. The closed-over
 *      `graph` is deliberately not the write source.
 *
 * The shell owns *when* this is mounted; Stream A only defines the mechanism.
 * `onSaved`/`onError` and the {@link CommitInput} signature are unchanged; the
 * shell simply consumes `onSaved`'s result instead of triggering a reload.
 */
export function makeGraphCommitter(
  graph: GraphDoc,
  onSaved: (result: SaveGraphResult) => void,
  onError?: (error: Error) => void,
): CommitInput {
  // The captured snapshot is intentionally not the write source (see above):
  // every PUT rebases on a fresh GET. Kept as a parameter so the shell's call
  // site is unchanged.
  void graph;
  // Serialization point: each commit appends its GET→patch→PUT onto this tail.
  let queue: Promise<void> = Promise.resolve();

  return (nodeId, param, value) => {
    queue = queue
      // A failed commit already reported to `onError` in its own catch below;
      // swallow the prior tail's rejection so the next commit still runs.
      .catch(() => undefined)
      .then(async () => {
        // Rebase on the latest served graph, not the closed-over snapshot.
        const { graph: latest } = await fetchLiveGraph();
        const next: GraphDoc = {
          ...latest,
          nodes: latest.nodes.map((node) =>
            node.id === nodeId
              ? { ...node, inputs: { ...node.inputs, [param]: value } }
              : node,
          ),
        };
        const result = await saveGraph(next);
        onSaved(result);
      })
      .catch((error: unknown) => {
        onError?.(error instanceof Error ? error : new Error(String(error)));
      });
  };
}
