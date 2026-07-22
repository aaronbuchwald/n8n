// The commit seam (ADR 0005 A-D5). An editor's `onCommit(next)` ultimately
// writes the literal into the graph and PUTs /api/graph — the *existing*
// endpoint, no new RPC. That write is the shell's job, so the slot reads it from
// context: when no provider is mounted the canvas stays read-only (today's
// behavior) and no editors appear.

import { createContext, useContext } from 'react';
import type { GraphDoc } from '../types';
import { saveGraph, type SaveGraphResult } from '../api';

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
 * (the round-trip proof), so `onSaved` receives the re-served graph.
 *
 * The shell owns *when* this is mounted; Stream A only defines the mechanism.
 */
export function makeGraphCommitter(
  graph: GraphDoc,
  onSaved: (result: SaveGraphResult) => void,
  onError?: (error: Error) => void,
): CommitInput {
  return (nodeId, param, value) => {
    const next: GraphDoc = {
      ...graph,
      nodes: graph.nodes.map((node) =>
        node.id === nodeId ? { ...node, inputs: { ...node.inputs, [param]: value } } : node,
      ),
    };
    void saveGraph(next)
      .then(onSaved)
      .catch((error: unknown) =>
        onError?.(error instanceof Error ? error : new Error(String(error))),
      );
  };
}
