// ADR 0014 D5 — the UI-local workbench layout store.
//
// This is presentation state (which regions are collapsed, which dock tab is
// active, the per-tab-kind dock width), device-global, and deliberately NOT the
// sync store (ADR 0008): it shares no lock, queue, or epoch with it and never
// enters the mutation funnel. It is the sibling precedent of `store/positions.ts`
// — a plain module owning its own versioned localStorage path.
//
// Split *sizes* (sash positions) are NOT stored here: react-resizable-panels'
// `autoSaveId` persists those under its own `react-resizable-panels:*` keys.
// What lives here is the small slice the library does not own — the rail
// (collapsed) states, the last active right-dock tab, and each tab-kind's
// remembered dock width — under one versioned key so it survives the full
// `.ge-main` remount an entry switch causes (ADR 0009 D6 / ADR 0014 D5).
//
// W4 extends this module for persistence tests: the exported `STORAGE_KEY`,
// `LAYOUT_STORAGE_PREFIX`, `getLayout`, the mutators, and `resetLayout` are the
// stable seam.

/** The collapsible regions (the canvas is never collapsible). ADR 0017 W4
 *  retired the left region; the workbench narrows to `center │ right`. */
export type RegionKey = 'right' | 'bottom';

/** Dock tabs remember width per *kind*, not per tab (ADR 0014 D3). */
export type DockTabKind = 'inspector' | 'code';

export interface LayoutState {
  /** Rail states: a collapsed region renders a rail instead of the panel. */
  collapsed: Record<RegionKey, boolean>;
  /** Remembered right-dock width (percent of the main group) per tab kind. */
  rightWidthByTab: Record<DockTabKind, number>;
  /** The last active right-dock tab id, restored on mount. */
  activeRightTab: string | null;
}

/** The versioned key for OUR slice; `v2` is the schema version (bumped by ADR
 *  0017 W4 when the left region dropped out of `collapsed`; a stale v1 blob
 *  simply falls to defaults via the fail-safe parse below). */
export const STORAGE_KEY = 'ge:workbench:v2';

/** The prefix react-resizable-panels' `autoSaveId` writes sash sizes under. */
export const LAYOUT_STORAGE_PREFIX = 'react-resizable-panels:';

// Defaults mirror today's CSS at a 1440px reference viewport (ADR 0014 D1):
// inspector dock ~340px (~24%), code dock ~34rem (~34%).
const DEFAULTS: LayoutState = {
  collapsed: { right: false, bottom: false },
  rightWidthByTab: { inspector: 24, code: 34 },
  activeRightTab: null,
};

function freeze(source: LayoutState): LayoutState {
  return {
    collapsed: { ...source.collapsed },
    rightWidthByTab: { ...source.rightWidthByTab },
    activeRightTab: source.activeRightTab,
  };
}

/**
 * Parse a persisted blob into a valid state, or fall back to defaults. Never
 * throws and never migrates (D5 "versioned + fail-safe"): an unknown shape is
 * simply discarded to defaults so a corrupt entry can never wedge the shell.
 */
function parse(raw: string | null): LayoutState {
  if (!raw) return freeze(DEFAULTS);
  try {
    const data = JSON.parse(raw) as Partial<LayoutState>;
    const collapsed: Partial<Record<RegionKey, boolean>> = data.collapsed ?? {};
    const widths: Partial<Record<DockTabKind, number>> = data.rightWidthByTab ?? {};
    return {
      collapsed: {
        right: Boolean(collapsed.right),
        bottom: Boolean(collapsed.bottom),
      },
      rightWidthByTab: {
        inspector:
          typeof widths.inspector === 'number'
            ? widths.inspector
            : DEFAULTS.rightWidthByTab.inspector,
        code: typeof widths.code === 'number' ? widths.code : DEFAULTS.rightWidthByTab.code,
      },
      activeRightTab: typeof data.activeRightTab === 'string' ? data.activeRightTab : null,
    };
  } catch {
    return freeze(DEFAULTS);
  }
}

// localStorage may be unavailable (privacy mode, embedded frame) — the ADR's
// fallback is an in-memory session copy, so the shell still works, it just
// forgets on reload.
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

let state: LayoutState = parse(readStorage());
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

function commit(next: LayoutState): void {
  state = freeze(next);
  writeStorage(JSON.stringify(state));
  emit();
}

/** The current immutable snapshot (stable ref until a mutator runs). */
export function getLayout(): LayoutState {
  return state;
}

/** Subscribe to layout changes (useSyncExternalStore contract). */
export function subscribeLayout(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setRegionCollapsed(region: RegionKey, collapsed: boolean): void {
  if (state.collapsed[region] === collapsed) return;
  commit({ ...state, collapsed: { ...state.collapsed, [region]: collapsed } });
}

export function setActiveRightTab(tabId: string | null): void {
  if (state.activeRightTab === tabId) return;
  commit({ ...state, activeRightTab: tabId });
}

export function setRightWidth(kind: DockTabKind, widthPct: number): void {
  if (state.rightWidthByTab[kind] === widthPct) return;
  commit({ ...state, rightWidthByTab: { ...state.rightWidthByTab, [kind]: widthPct } });
}

/**
 * Reset the whole workbench to defaults (the D5 "Reset layout" affordance and
 * the escape hatch for a corrupt saved layout). Clears BOTH key families — our
 * slice and every `react-resizable-panels:*` autoSaveId entry — then re-applies
 * defaults so the panel refs can snap back without a reload. The node catalog
 * no longer persists any state (its section collapse is ephemeral, reset on
 * every open), so there is nothing catalog-side left to clear here.
 */
export function resetLayout(): void {
  try {
    const store = window.localStorage;
    const doomed: string[] = [];
    for (let i = 0; i < store.length; i += 1) {
      const key = store.key(i);
      if (key && key.startsWith(LAYOUT_STORAGE_PREFIX)) doomed.push(key);
    }
    for (const key of doomed) store.removeItem(key);
    store.removeItem(STORAGE_KEY);
  } catch {
    // storage unavailable — nothing persisted to clear
  }
  commit(freeze(DEFAULTS));
}

/** Test-only reset back to the pristine in-memory default. */
export function __resetLayoutForTest(): void {
  state = freeze(DEFAULTS);
  listeners.clear();
}
