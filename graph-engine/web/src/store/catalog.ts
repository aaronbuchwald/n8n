// ADR 0017 (node catalog) D5 — the UI-local catalog store.
//
// The one *durable* slice of the NodeCatalog: which capability sections the user
// folded shut. Highlight and query are ephemeral (reset every open) and stay in
// the component; the collapsed set persists here. This is presentation state,
// device-global, and deliberately NOT the ADR 0008 sync store — it is the exact
// sibling of `store/layout.ts`: a plain module owning its own versioned
// localStorage path (`ge:catalog:v1`), with synchronous writes and a safe no-op
// when storage is unavailable.
//
// "Reset layout" (ADR 0014 D5 / this ADR's D5) also clears this key — the single
// escape hatch for all persisted UI state. That hook lives in
// `store/layout.ts::resetLayout`, which calls `resetCatalog()`.

import type { CategoryId } from '../catalog/categories';

export interface CatalogState {
  /** The capability sections the user has folded shut (persisted). */
  collapsed: readonly CategoryId[];
}

/** The versioned key for OUR slice; `v1` is the schema version (D5). */
export const STORAGE_KEY = 'ge:catalog:v1';

const DEFAULTS: CatalogState = { collapsed: [] };

/** The full set of legal category ids — anything else in a stored blob is dropped. */
const KNOWN_CATEGORIES: ReadonlySet<string> = new Set<CategoryId>([
  'input-data',
  'table',
  'math',
  'logic',
  'render-output',
  'other',
]);

function isCategoryId(value: unknown): value is CategoryId {
  return typeof value === 'string' && KNOWN_CATEGORIES.has(value);
}

function freeze(source: CatalogState): CatalogState {
  return { collapsed: [...source.collapsed] };
}

/**
 * Parse a persisted blob into a valid state, or fall back to defaults. Never
 * throws and never migrates (D5 "versioned + fail-safe"): unknown ids are
 * dropped and a corrupt shape discards to defaults, so a bad entry can never
 * wedge the catalog.
 */
function parse(raw: string | null): CatalogState {
  if (!raw) return freeze(DEFAULTS);
  try {
    const data = JSON.parse(raw) as Partial<CatalogState>;
    const collapsed = Array.isArray(data.collapsed) ? data.collapsed.filter(isCategoryId) : [];
    // De-dupe while preserving order.
    return { collapsed: [...new Set(collapsed)] };
  } catch {
    return freeze(DEFAULTS);
  }
}

// localStorage may be unavailable (privacy mode, embedded frame) — the fallback
// is an in-memory session copy, so the catalog still works, it just forgets on
// reload (the layout-store precedent).
function readStorage(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStorage(value: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, value);
  } catch {
    // in-memory only for this session
  }
}

let state: CatalogState = parse(readStorage());
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

function commit(next: CatalogState): void {
  state = freeze(next);
  writeStorage(JSON.stringify(state));
  emit();
}

/** The current immutable snapshot (stable ref until a mutator runs). */
export function getCatalog(): CatalogState {
  return state;
}

/** Subscribe to catalog changes (useSyncExternalStore contract). */
export function subscribeCatalog(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Fold a section shut or open it — the section-header toggle (D3). */
export function toggleCatalogSection(id: CategoryId): void {
  const has = state.collapsed.includes(id);
  const collapsed = has ? state.collapsed.filter((c) => c !== id) : [...state.collapsed, id];
  commit({ collapsed });
}

/** Set a section's collapsed state explicitly (used by the `←`/`→` keys, D5). */
export function setCatalogSectionCollapsed(id: CategoryId, collapsed: boolean): void {
  if (state.collapsed.includes(id) === collapsed) return;
  toggleCatalogSection(id);
}

/**
 * Clear all persisted catalog state back to defaults. Called by "Reset layout"
 * (`store/layout.ts::resetLayout`) so one affordance clears every persisted UI
 * slice; also the escape hatch for a corrupt saved value.
 */
export function resetCatalog(): void {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // storage unavailable — nothing persisted to clear
  }
  commit(freeze(DEFAULTS));
}

/** Test-only reset back to the pristine in-memory default. */
export function __resetCatalogForTest(): void {
  state = freeze(DEFAULTS);
  listeners.clear();
}
