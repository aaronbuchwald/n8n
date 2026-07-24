// The commit seam (ADR 0005 A-D5). An editor's `onCommit(next)` ultimately
// writes the literal into the graph and PUTs /api/graph — the *existing*
// endpoint, no new RPC. Whether editing is live is the shell's decision, so the
// slot reads a commit function from context: when no provider is mounted the
// canvas stays read-only (today's behavior) and no editors appear.
//
// ADR 0008 Phase 1 (8-S1): the committer is retired. The shell now provides the
// store's `commitLiteral` — a STABLE module-level function — as the context
// value. Because it never changes identity, `WidgetSlot` no longer re-renders
// through context churn on every graph update (the R2 fan-out the store fixes),
// and the whole lost-update machine (serialize + rebase + seq-gate) moves into
// the store's single-flight queue (store/queue.ts).

import { createContext, useContext } from 'react';

/** Commit one input's literal on a node. Provided by the shell; null = read-only. */
export type CommitInput = (nodeId: string, param: string, value: unknown) => void;

const WidgetEditingContext = createContext<CommitInput | null>(null);

/** Wrap the canvas to enable widget editing. Value is a {@link CommitInput}. */
export const WidgetEditingProvider = WidgetEditingContext.Provider;

/** The active commit function, or null when the canvas is read-only. */
export const useWidgetCommit = (): CommitInput | null => useContext(WidgetEditingContext);
