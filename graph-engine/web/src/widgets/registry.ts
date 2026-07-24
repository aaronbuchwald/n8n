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

// --- read-only preview axis (ADR 0013 D2) -----------------------------------
// A mirror of the editor registry above, added additively in the same file: a
// `kind -> preview` map so the card can show a rendered, READ-ONLY face of each
// widget value (typeset math/calc, a table-recipe summary chip). Editing lives
// in the inspector now; the card mounts previews only. An unregistered kind
// resolves to null and the mounting slot (WidgetPreview) falls back to today's
// value-chip markup — the same forward-compatibility story as `editorFor`.

/**
 * The props every widget preview receives. Read-only by construction — a
 * preview renders purely from the committed literal (no commit, no store, no
 * run data), the same status as layout in the bijection (ADR 0004 D6).
 */
export interface WidgetPreviewProps<V = unknown> {
  /** Current literal from `graph.nodes[].inputs[name]` (undefined if unset). */
  value: V;
  /** `spec.widget.config`, opaque to the shell — passed straight through. */
  config: Record<string, unknown>;
  /** The input spec, for labels and the fallback. */
  input: SpecInput;
}

export type WidgetPreview = ComponentType<WidgetPreviewProps>;

/**
 * Where the card mounts a kind's preview: inline in the socket row (chip-sized)
 * or as a block in the card's preview strip (typeset equations that need room).
 */
export type PreviewPlacement = 'inline' | 'block';

// A registered preview is either eager or a lazy code-split chunk (heavy
// previews share the editor's KaTeX/translator chunk per kind).
export type RegisteredPreview = WidgetPreview | LazyExoticComponent<WidgetPreview>;

interface PreviewEntry {
  component: RegisteredPreview;
  placement: PreviewPlacement;
}

const PREVIEWS = new Map<string, PreviewEntry>();

/** Register a read-only preview for a `kind` (index.ts, one line per kind). */
export const registerWidgetPreview = (
  kind: string,
  component: RegisteredPreview,
  placement: PreviewPlacement = 'inline',
): void => {
  PREVIEWS.set(kind, { component, placement });
};

/**
 * Resolve a widget declaration to its registered preview, or null when the kind
 * has none — the slot then falls back to the read-only value chip (D2).
 */
export const previewFor = (widget: Widget | null | undefined): PreviewEntry | null =>
  (widget && PREVIEWS.get(widget.kind)) ?? null;

/**
 * The placement the card should mount a widget's preview in. Unregistered kinds
 * (and the value-chip fallback) are `inline` — they live in the socket row.
 */
export const previewPlacementFor = (widget: Widget | null | undefined): PreviewPlacement =>
  previewFor(widget)?.placement ?? 'inline';

/**
 * Wrap a dynamic import as a code-split preview (mirrors {@link lazyEditor}).
 * Heavy previews register with this so KaTeX + the translators stay npm-bundled
 * and code-split per kind; the mounting slot supplies the Suspense boundary.
 */
export const lazyPreview = (
  load: () => Promise<{ default: WidgetPreview }>,
): LazyExoticComponent<WidgetPreview> => lazy(load);
