// The kind -> editor registry (ADR 0005 A-D4). A node's `widget.kind` resolves
// to an editor component here; an unknown kind falls back to today's behavior.
//
// This is a FROZEN contract (wave-α freeze 1): the `WidgetEditorProps` shape and
// the `editorFor(...)` fallback are inherited by streams B (math) and C-ui
// (table). Change them only by extending additively.

import { lazy, type ComponentType, type LazyExoticComponent } from 'react';
import type { Widget, SpecInput } from '../types';
import { DefaultEditor } from './DefaultEditor';

/**
 * The props every widget editor receives — the whole cross-stream contract.
 * `V` is the literal type the editor reads and commits (a graph literal, so
 * always in the literal-JSON subset per A-D5).
 */
export interface WidgetEditorProps<V = unknown> {
  /** Current literal from `graph.nodes[].inputs[name]` (undefined if unset). */
  value: V;
  /** `spec.widget.config`, opaque to the shell — passed straight through. */
  config: Record<string, unknown>;
  /** The input spec: name/type/required, for labels and the fallback editor. */
  input: SpecInput;
  /** Commit an edited literal; the shell writes it and PUTs `/api/graph`. */
  onCommit: (next: V) => void;
  /**
   * The graph node id this editor is editing (additive extension, ADR 0007
   * stream W). Editors that only edit their own literal ignore it; the calc
   * editor uses it to resolve its node's spec id for the derive endpoint and
   * to name the node in the prune-on-commit path. Optional so pre-existing
   * editors and tests that mount editors directly stay valid.
   */
  nodeId?: string;
}

export type WidgetEditor = ComponentType<WidgetEditorProps>;

// A registered editor is either eager (built-ins) or a lazy code-split chunk
// (heavy editors like `math`/`table-recipe`). Both render in JSX; the mounting
// slot supplies the Suspense boundary lazy ones need.
export type RegisteredEditor = WidgetEditor | LazyExoticComponent<WidgetEditor>;

const REGISTRY = new Map<string, RegisteredEditor>();

/** Register an editor for a `kind`. Built-ins register at startup (index.ts). */
export const registerWidget = (kind: string, editor: RegisteredEditor): void => {
  REGISTRY.set(kind, editor);
};

/**
 * Resolve a widget declaration to its editor. Unknown (or absent) kinds fall
 * back to {@link DefaultEditor} — the forward-compatibility mechanism for the
 * open `kind` vocabulary (A-D6): a spec authored against a newer pack degrades
 * gracefully instead of failing.
 */
export const editorFor = (widget: Widget | null | undefined): RegisteredEditor =>
  (widget && REGISTRY.get(widget.kind)) ?? DefaultEditor;

/** True when a kind has a registered editor (else `editorFor` uses the fallback). */
export const hasEditor = (kind: string): boolean => REGISTRY.has(kind);

/**
 * Wrap a dynamic import as a code-split editor (A-D4). Heavy editors register
 * with this so they are npm-bundled but lazily loaded; the mounting slot
 * (WidgetSlot) supplies the Suspense boundary. Built-ins stay eager.
 */
export const lazyEditor = (
  load: () => Promise<{ default: WidgetEditor }>,
): LazyExoticComponent<WidgetEditor> => lazy(load);
