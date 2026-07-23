// The kind -> renderer registry (ADR 0010 D4). A node spec's `renderer.kind`
// resolves to a whole-node renderer component here; an unknown (or absent)
// kind resolves to null and the mounting slot falls back to today's ResultChips.
//
// This is a FROZEN contract (ADR 0010 wave-1 freeze 2): the `NodeRendererProps`
// shape and the `rendererFor(...)` null-means-chips fallback are inherited by
// the kind streams (10-K html-card first). Change them only by extending
// additively. The registry is closed at build time: every renderer is
// npm-bundled (heavy kinds as lazy code-split chunks) — zero CDN.

import { lazy, type ComponentType, type LazyExoticComponent } from 'react';
import type { NodeSpec, RendererDecl } from '../types';

/**
 * The props every node renderer receives — the whole cross-stream contract
 * (ADR 0010 D4). The same component mounts on the node card and in the run
 * results panel; `surface` says which.
 */
export interface NodeRendererProps {
  /** The graph node id (the key run results / inspector rows use). */
  nodeId: string;
  /** The node's spec (title/doc/inputs/outputs) — never null at this mount. */
  spec: NodeSpec;
  /** `spec.renderer.config`, opaque to the shell — passed straight through. */
  config: Record<string, unknown>;
  /** Literals bound to unwired inputs (graph.nodes[].inputs). */
  boundInputs: Record<string, unknown>;
  /** Input names fed by an edge rather than a literal. */
  wiredInputs: ReadonlySet<string>;
  /** Per-socket values from the latest run; null before a run or when the
      run failed upstream. Values are JSON-safe with {"$repr","$type"}
      degradation (server/serialize.py) — renderers must tolerate both. */
  result: Record<string, unknown> | null;
  /** True when the latest run failed at this node. */
  hasError: boolean;
  /** Where the renderer is mounted: the node card or the results panel (D7). */
  surface: 'card' | 'panel';
}

export type NodeRenderer = ComponentType<NodeRendererProps>;

// A registered renderer is either eager (trivial kinds) or a lazy code-split
// chunk (heavy kinds like `html-card`). Both render in JSX; the mounting slot
// supplies the Suspense boundary lazy ones need.
export type RegisteredRenderer = NodeRenderer | LazyExoticComponent<NodeRenderer>;

const REGISTRY = new Map<string, RegisteredRenderer>();

/** Register a renderer for a `kind`. Kinds register at startup (index.ts). */
export const registerNodeRenderer = (kind: string, renderer: RegisteredRenderer): void => {
  REGISTRY.set(kind, renderer);
};

/**
 * Resolve a renderer declaration to its component. Unknown (or absent) kinds
 * resolve to null — the slot falls back to ResultChips. That fallback is the
 * versioning story for the open `kind` vocabulary (ADR 0010 D4): a spec
 * declaring a kind this bundle doesn't ship degrades to today's chips.
 */
export const rendererFor = (decl: RendererDecl | null | undefined): RegisteredRenderer | null =>
  (decl && REGISTRY.get(decl.kind)) ?? null;

/** True when a kind has a registered renderer (else the slot shows chips). */
export const hasRenderer = (kind: string): boolean => REGISTRY.has(kind);

/**
 * Wrap a dynamic import as a code-split renderer (ADR 0010 D4). Heavy kinds
 * register with this so they are npm-bundled but lazily loaded; the mounting
 * slot supplies the Suspense boundary. Trivial kinds stay eager.
 */
export const lazyNodeRenderer = (
  load: () => Promise<{ default: NodeRenderer }>,
): LazyExoticComponent<NodeRenderer> => lazy(load);
