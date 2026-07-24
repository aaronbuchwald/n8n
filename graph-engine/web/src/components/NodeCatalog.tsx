// ADR 0017 (node catalog) — the on-demand "Add node" catalog.
//
// A top-bar button opens an anchored command-palette popover: an autofocused
// search over every registered spec, grouped into the D2 capability sections
// (Input/Data · Table · Math · Logic · Render/Output, + Other only when
// non-empty) as collapsible sections, plus a persistent "Create new node…"
// footer. Click-to-insert drops the node at the visible canvas centre (D4),
// closes the catalog, and selects the new node so the Inspector opens.
//
// Stream 17-W1 delivered the surface (button, popover, search, click-collapse,
// click-insert, footer). Stream 17-W2 (this file) adds the full D5 keyboard
// model + ARIA and moves collapse persistence into `store/catalog.ts`:
//   - Ctrl/Cmd+K opens (guarded from Monaco/editable targets), again closes.
//   - A virtual highlight (`aria-activedescendant`) roves the visible rows with
//     ↑/↓/Home/End, flowing across section boundaries and skipping headers.
//   - ←/→ collapse/expand the highlighted row's section.
//   - Enter inserts + closes; Alt+Enter (and Alt+click) inserts + stays open
//     (multi-add). Escape is two-stage and consumed so App's cascade never
//     double-fires.
//   - Section collapse persists across reloads via `ge:catalog:v1`, cleared by
//     "Reset layout". Highlight and query stay ephemeral (reset each open).
//
// Stream 17-W3 (this file) adds drag-out-of-catalog via the D6 ghost-state
// model: rows are now `draggable` and set the SAME `PALETTE_SPEC_MIME` payload
// the old Palette set, so `GraphView`'s existing drop handler creates the node
// at the drop point with zero canvas changes. On `dragstart` the popover stays
// mounted/open but enters a ghost state (`data-dragging="true"` → dimmed to
// opacity 0.25 + `pointer-events: none`) so the drop lands on the canvas
// beneath, not the popover; light-dismiss is suspended for the drag's duration.
// On `dragend` the `dataTransfer.dropEffect` decides: a real drop ('copy')
// closes the catalog; a cancelled drag ('none') restores it fully, query and
// highlight intact. Reads specs from the store exactly as the palette does (no
// new fetch); every insert funnels through the existing `createNode`.

import { useEffect, useMemo, useRef, useState } from 'react';

import { CATEGORY_SECTIONS, categoryFor, type CategoryId } from '../catalog/categories';
// The catalog reuses the W5→W4 drag contract byte-for-byte; the constant now
// lives in a neutral module (W4 retired the Palette it used to live in).
import { PALETTE_SPEC_MIME } from '../catalog/dnd';
import { setCatalogSectionCollapsed, toggleCatalogSection } from '../store/catalog';
import { createNode } from '../store/sync';
import { useCatalogSelector } from '../store/useCatalog';
import { useSyncSelector } from '../store/useSyncSelector';
import type { NodeSpec } from '../types';

interface NodeCatalogProps {
  /** Disabled until the store has hydrated (like Run/Export) so it can't open
   *  against an empty spec set. */
  disabled: boolean;
  /** The visible canvas centre in graph coords (D4), or null when unavailable. */
  getInsertPosition: () => { x: number; y: number } | null;
  /** Select the freshly-inserted node — opens the Inspector in the right dock. */
  onSelectNode: (nodeId: string) => void;
  /** Open the existing New-node dock tab (the footer's escape hatch). */
  onCreateNewNode: () => void;
}

interface CatalogEntry {
  spec: NodeSpec;
  category: CategoryId;
  summary: string; // first doc line, '' when undocumented
}

/** A visible (navigable) row: its spec id and the section it lives in. */
interface VisibleEntry {
  specId: string;
  category: CategoryId;
}

/** DOM id for an entry's `role="option"` — the target of `aria-activedescendant`. */
function optionDomId(specId: string): string {
  return `ge-catalog-opt-${specId}`;
}

/** First line of the spec's docstring — the entry's one-line summary (D3). */
function firstDocLine(doc: string): string {
  const newline = doc.indexOf('\n');
  return (newline === -1 ? doc : doc.slice(0, newline)).trim();
}

/**
 * Fallback insert point when the canvas centre is unavailable: the palette's
 * old blind top-left constant, staggered by node count so adds don't stack.
 */
function fallbackPosition(nodeCount: number): { x: number; y: number } {
  return { x: 80 + (nodeCount % 6) * 48, y: 80 + (nodeCount % 10) * 40 };
}

/** A small node-count-based offset so repeated centre inserts never stack (D4). */
function staggerOffset(nodeCount: number): { dx: number; dy: number } {
  return { dx: (nodeCount % 6) * 24, dy: (nodeCount % 10) * 20 };
}

/** True when the event originates in an editable surface Ctrl+K must not steal. */
function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false;
  return Boolean(
    target.closest('input, textarea, [contenteditable], [contenteditable="true"]') ||
      target.closest('.ge-source'), // Monaco owns Ctrl+K chords
  );
}

export function NodeCatalog({
  disabled,
  getInsertPosition,
  onSelectNode,
  onCreateNewNode,
}: NodeCatalogProps) {
  const specs = useSyncSelector((s) => s.specs);
  const nodesById = useSyncSelector((s) => s.effective.nodesById);
  // Durable collapse state (D5): the persisted `ge:catalog:v1` slice.
  const collapsedList = useCatalogSelector((s) => s.collapsed);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  // Ephemeral virtual highlight (D5): the spec id of the roving `role="option"`.
  // null falls back to the first visible entry (resolved below).
  const [highlightedId, setHighlightedId] = useState<string | null>(null);
  const [inserting, setInserting] = useState(false);
  // Transient D6 ghost state: true only while an entry is being dragged out.
  // Dims + pass-through the popover so the drop lands on the canvas beneath.
  const [dragging, setDragging] = useState(false);

  const rootRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  // Did the in-flight drag actually land a drop? A document-level `drop`
  // listener (added while dragging) is the reliable signal — `dragEnd`'s
  // `dropEffect` is only spec-settable during `dragover`, so it can't be
  // trusted (and synthetic events can't set it at all). See the drag effect.
  const droppedRef = useRef(false);

  const collapsedSet = useMemo(() => new Set(collapsedList), [collapsedList]);

  // Close if the app leaves the ready state while the catalog is open.
  useEffect(() => {
    if (disabled && open) setOpen(false);
  }, [disabled, open]);

  // While an entry is being dragged out, watch for a real `drop` anywhere in the
  // document (capture phase, so it fires even if the canvas handler stops the
  // event). That flag — not `dragEnd.dropEffect` — decides drop-vs-cancel.
  useEffect(() => {
    if (!dragging) return;
    const onDrop = () => {
      droppedRef.current = true;
    };
    document.addEventListener('drop', onDrop, true);
    return () => document.removeEventListener('drop', onDrop, true);
  }, [dragging]);

  // Autofocus the search on open; reset the ephemeral query + highlight each
  // visit (collapse state is durable and deliberately NOT reset here).
  useEffect(() => {
    if (open) searchRef.current?.focus();
    else {
      setQuery('');
      setHighlightedId(null);
      setDragging(false); // never leave the ghost state pinned across a close
    }
  }, [open]);

  // A new query re-seeds the highlight to the first match (D5).
  useEffect(() => {
    setHighlightedId(null);
  }, [query]);

  // Ctrl/Cmd+K: open (focus search) when closed, close when open. When closed,
  // ignored on an editable/Monaco target (the same guard shape as App's cascade)
  // so the shortcut never steals a chord the editor owns. Capture phase +
  // preventDefault so the browser's own Ctrl+K (e.g. Firefox search bar) yields.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const isK = (event.ctrlKey || event.metaKey) && (event.key === 'k' || event.key === 'K');
      if (!isK) return;
      if (open) {
        event.preventDefault();
        setOpen(false);
        return;
      }
      if (disabled) return;
      if (isEditableTarget(event.target)) return;
      event.preventDefault();
      setOpen(true);
    };
    window.addEventListener('keydown', onKeyDown, true);
    return () => window.removeEventListener('keydown', onKeyDown, true);
  }, [open, disabled]);

  // Light-dismiss (outside pointer-down) + Escape, mirroring GraphPicker. Escape
  // is two-stage: a non-empty query clears; an empty query closes. Consumed in
  // capture phase so App's Escape cascade never fires through the catalog.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      // Suspended mid-drag (D6): a drop on the canvas is not an "outside click".
      if (dragging) return;
      if (rootRef.current && event.target instanceof Node && !rootRef.current.contains(event.target)) {
        setOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      setQuery((q) => {
        if (q.trim() !== '') return '';
        setOpen(false);
        return q;
      });
    };
    document.addEventListener('mousedown', onPointerDown);
    window.addEventListener('keydown', onKeyDown, true);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      window.removeEventListener('keydown', onKeyDown, true);
    };
  }, [open, dragging]);

  // Group matching specs into the D2 sections, in pipeline order, dropping empty
  // sections. Match scope (D5): case-insensitive substring over name, the
  // one-line doc, AND the spec id — a strict superset of the palette's matching.
  const sections = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const byCategory = new Map<CategoryId, CatalogEntry[]>();
    for (const spec of Object.values(specs)) {
      const summary = firstDocLine(spec.doc);
      if (
        needle &&
        !spec.name.toLowerCase().includes(needle) &&
        !summary.toLowerCase().includes(needle) &&
        !spec.id.toLowerCase().includes(needle)
      ) {
        continue;
      }
      const category = categoryFor(spec);
      const entry: CatalogEntry = { spec, category, summary };
      const existing = byCategory.get(category);
      if (existing) existing.push(entry);
      else byCategory.set(category, [entry]);
    }
    return CATEGORY_SECTIONS.map((section) => ({
      section,
      entries: (byCategory.get(section.id) ?? []).sort((a, b) =>
        a.spec.name.localeCompare(b.spec.name),
      ),
    })).filter((group) => group.entries.length > 0);
  }, [specs, query]);

  const totalMatches = sections.reduce((count, group) => count + group.entries.length, 0);
  // A query in progress overrides collapse so a match is never hidden in a fold.
  const searching = query.trim() !== '';
  const isExpanded = (id: CategoryId) => searching || !collapsedSet.has(id);

  // The flat list of navigable rows, in render order, only inside expanded
  // sections — the roving highlight flows across this list (headers skipped).
  const visibleEntries = useMemo<VisibleEntry[]>(() => {
    const list: VisibleEntry[] = [];
    for (const { section, entries } of sections) {
      if (searching || !collapsedSet.has(section.id)) {
        for (const { spec, category } of entries) list.push({ specId: spec.id, category });
      }
    }
    return list;
  }, [sections, searching, collapsedSet]);

  // Resolve the effective highlight: the stored id if still visible, else the
  // first visible row. `-1` when nothing matches (the empty state).
  const activeIndex = useMemo(() => {
    if (visibleEntries.length === 0) return -1;
    const i = visibleEntries.findIndex((e) => e.specId === highlightedId);
    return i >= 0 ? i : 0;
  }, [visibleEntries, highlightedId]);
  const activeEntry = activeIndex >= 0 ? visibleEntries[activeIndex] : null;
  const activeSpecId = activeEntry?.specId ?? null;

  // Keep the highlighted row scrolled into view (focus never leaves the search,
  // so the browser won't do it for us).
  useEffect(() => {
    if (!open || !activeSpecId) return;
    rootRef.current
      ?.querySelector(`#${CSS.escape(optionDomId(activeSpecId))}`)
      ?.scrollIntoView({ block: 'nearest' });
  }, [open, activeSpecId]);

  const insert = async (specId: string, keepOpen: boolean) => {
    if (inserting) return;
    setInserting(true);
    try {
      const centre = getInsertPosition();
      const count = nodesById.size;
      let position: { x: number; y: number };
      if (centre) {
        const { dx, dy } = staggerOffset(count);
        position = { x: centre.x + dx, y: centre.y + dy };
      } else {
        position = fallbackPosition(count);
      }
      const { id } = await createNode(specId, position);
      if (keepOpen) {
        // Multi-add (D4): stay open, keep the search focused for the next add.
        searchRef.current?.focus();
      } else {
        setOpen(false);
        onSelectNode(id);
      }
    } catch {
      // A mint failure is already surfaced on the store's writeError banner.
    } finally {
      setInserting(false);
    }
  };

  // ← collapses the highlighted row's section; the highlight clamps into the
  // shrunken list so it never lands on nothing (D5).
  const collapseActiveSection = () => {
    if (!activeEntry || searching) return; // collapse has no visible effect mid-search
    if (collapsedSet.has(activeEntry.category)) return;
    const nextCollapsed = new Set(collapsedSet);
    nextCollapsed.add(activeEntry.category);
    const nextVisible: VisibleEntry[] = [];
    for (const { section, entries } of sections) {
      if (!nextCollapsed.has(section.id)) {
        for (const { spec, category } of entries) nextVisible.push({ specId: spec.id, category });
      }
    }
    setCatalogSectionCollapsed(activeEntry.category, true);
    if (nextVisible.length > 0) {
      const clamped = Math.min(activeIndex, nextVisible.length - 1);
      setHighlightedId(nextVisible[clamped].specId);
    }
  };

  // → expands the highlighted row's section if it is collapsed (no-op otherwise);
  // the highlight stays on the same row, which remains visible (D5).
  const expandActiveSection = () => {
    if (!activeEntry || searching) return;
    if (!collapsedSet.has(activeEntry.category)) return;
    setCatalogSectionCollapsed(activeEntry.category, false);
  };

  const moveHighlight = (delta: 1 | -1) => {
    if (visibleEntries.length === 0) return;
    const base = activeIndex < 0 ? 0 : activeIndex;
    const next = (base + delta + visibleEntries.length) % visibleEntries.length;
    setHighlightedId(visibleEntries[next].specId);
  };

  const jumpHighlight = (to: 'first' | 'last') => {
    if (visibleEntries.length === 0) return;
    setHighlightedId(visibleEntries[to === 'first' ? 0 : visibleEntries.length - 1].specId);
  };

  // The catalog's list navigation. Escape and Ctrl+K are handled in the capture
  // effects above; here we own the arrows/Home/End/Enter while the search keeps
  // real focus (all list movement is virtual — the listbox pattern).
  const onSearchKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        moveHighlight(1);
        break;
      case 'ArrowUp':
        event.preventDefault();
        moveHighlight(-1);
        break;
      case 'Home':
        event.preventDefault();
        jumpHighlight('first');
        break;
      case 'End':
        event.preventDefault();
        jumpHighlight('last');
        break;
      case 'ArrowLeft':
        event.preventDefault();
        collapseActiveSection();
        break;
      case 'ArrowRight':
        event.preventDefault();
        expandActiveSection();
        break;
      case 'Enter':
        if (activeSpecId) {
          event.preventDefault();
          void insert(activeSpecId, event.altKey); // Alt+Enter = multi-add (stay open)
        }
        break;
      default:
        break;
    }
  };

  const createNewNode = () => {
    setOpen(false);
    onCreateNewNode();
  };

  return (
    <div className="ge-catalog" ref={rootRef}>
      <button
        type="button"
        className="ge-btn"
        data-testid="add-node-button"
        aria-haspopup="dialog"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
      >
        ＋ Add node
      </button>

      {open && (
        <div
          className="ge-catalog__panel"
          data-testid="node-catalog"
          data-dragging={dragging ? 'true' : undefined}
          role="dialog"
          aria-label="Add node"
        >
          <div className="ge-catalog__search-row">
            <input
              ref={searchRef}
              className="ge-catalog__search"
              data-testid="node-catalog-search"
              type="search"
              placeholder="Search nodes…"
              aria-label="Search nodes"
              role="combobox"
              aria-expanded={open}
              aria-controls="ge-catalog-listbox"
              aria-activedescendant={activeSpecId ? optionDomId(activeSpecId) : undefined}
              autoComplete="off"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={onSearchKeyDown}
            />
          </div>

          <div className="ge-catalog__body">
            {totalMatches === 0 ? (
              <p className="ge-catalog__empty" data-testid="node-catalog-empty">
                no nodes match “{query.trim()}”
              </p>
            ) : (
              <div className="ge-catalog__sections" id="ge-catalog-listbox" role="listbox">
                {sections.map(({ section, entries }) => {
                  const expanded = isExpanded(section.id);
                  return (
                    <section
                      key={section.id}
                      className="ge-catalog__section"
                      data-testid="node-catalog-section"
                      data-category={section.id}
                    >
                      <button
                        type="button"
                        className="ge-catalog__section-toggle"
                        data-testid="node-catalog-section-toggle"
                        aria-expanded={expanded}
                        onClick={() => toggleCatalogSection(section.id)}
                      >
                        <span className="ge-catalog__chevron" aria-hidden="true">
                          {expanded ? '▾' : '▸'}
                        </span>
                        <span className="ge-catalog__section-glyph" aria-hidden="true">
                          {section.glyph}
                        </span>
                        <span className="ge-catalog__section-label">{section.label}</span>
                        <span className="ge-catalog__section-count">{entries.length}</span>
                      </button>
                      {expanded && (
                        <ul className="ge-catalog__list">
                          {entries.map(({ spec, category, summary }) => {
                            const active = spec.id === activeSpecId;
                            return (
                              <li key={spec.id}>
                                <button
                                  type="button"
                                  id={optionDomId(spec.id)}
                                  className={
                                    'ge-catalog__entry' +
                                    (active ? ' ge-catalog__entry--active' : '')
                                  }
                                  data-testid="node-catalog-entry"
                                  data-spec-id={spec.id}
                                  data-category={category}
                                  role="option"
                                  aria-selected={active}
                                  disabled={inserting}
                                  title={summary || `add a ${spec.id} node`}
                                  onClick={(event) => void insert(spec.id, event.altKey)}
                                  draggable
                                  onDragStart={(event) => {
                                    // Drag-to-place (D6): the SAME payload the old
                                    // Palette set, so GraphView's onDrop is byte-for-byte
                                    // compatible and the canvas needs no change. The drag
                                    // image is captured now, so dimming the panel next
                                    // does not affect the cursor ghost.
                                    event.dataTransfer.setData(PALETTE_SPEC_MIME, spec.id);
                                    event.dataTransfer.effectAllowed = 'copy';
                                    droppedRef.current = false;
                                    setDragging(true);
                                  }}
                                  onDragEnd={(event) => {
                                    // A real drop (seen by the document listener, or
                                    // reported via dropEffect) closes the catalog (D6);
                                    // a cancel (Esc / invalid target — no drop) restores it.
                                    const dropped =
                                      droppedRef.current || event.dataTransfer.dropEffect !== 'none';
                                    setDragging(false);
                                    if (dropped) setOpen(false);
                                  }}
                                >
                                  <span className="ge-catalog__entry-main">
                                    <span className="ge-catalog__entry-name">{spec.name}</span>
                                    {summary && (
                                      <span className="ge-catalog__entry-doc">{summary}</span>
                                    )}
                                  </span>
                                  <span className="ge-catalog__entry-id">{spec.id}</span>
                                </button>
                              </li>
                            );
                          })}
                        </ul>
                      )}
                    </section>
                  );
                })}
              </div>
            )}
          </div>

          <div className="ge-catalog__footer">
            <button
              type="button"
              className="ge-catalog__new-node"
              data-testid="node-catalog-new-node"
              onClick={createNewNode}
            >
              <span className="ge-catalog__new-node-glyph" aria-hidden="true">
                ＋
              </span>
              Create new node…
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
