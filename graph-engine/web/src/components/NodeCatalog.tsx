// ADR 0017 (node catalog) stream 17-W1 — the on-demand "Add node" catalog.
//
// A top-bar button opens an anchored command-palette popover: an autofocused
// search over every registered spec, grouped into the D2 capability sections
// (Input/Data · Table · Math · Logic · Render/Output, + Other only when
// non-empty) as collapsible sections, plus a persistent "Create new node…"
// footer. Click-to-insert drops the node at the visible canvas centre (D4),
// closes the catalog, and selects the new node so the Inspector opens.
//
// This is a PURE ADDITION: the left Palette (11-W5) still works and coexists;
// W4 retires it later. Reads specs from the store exactly as the palette does
// (no new fetch); every insert funnels through the existing `createNode`.
//
// Scope note: the full keyboard model (Ctrl/Cmd+K, virtual highlight, arrow
// nav), collapse *persistence* (`store/catalog.ts`), and drag-out-of-catalog
// are LATER streams (W2/W3). W1 delivers click-insert + search + collapsible
// sections, leaving clean seams for those. Collapse here is ephemeral local
// state; the popover's dismiss/Escape mirrors the GraphPicker precedent.

import { useEffect, useMemo, useRef, useState } from 'react';

import { CATEGORY_SECTIONS, categoryFor, type CategoryId } from '../catalog/categories';
import { createNode } from '../store/sync';
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

export function NodeCatalog({
  disabled,
  getInsertPosition,
  onSelectNode,
  onCreateNewNode,
}: NodeCatalogProps) {
  const specs = useSyncSelector((s) => s.specs);
  const nodesById = useSyncSelector((s) => s.effective.nodesById);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  // Ephemeral collapse (W2 persists it via store/catalog.ts). Query overrides it.
  const [collapsed, setCollapsed] = useState<ReadonlySet<CategoryId>>(new Set());
  const [inserting, setInserting] = useState(false);

  const rootRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  // Close if the app leaves the ready state while the catalog is open.
  useEffect(() => {
    if (disabled && open) setOpen(false);
  }, [disabled, open]);

  // Autofocus the search on open; reset the ephemeral query each visit.
  useEffect(() => {
    if (open) searchRef.current?.focus();
    else setQuery('');
  }, [open]);

  // Light-dismiss (outside pointer-down) + Escape, mirroring GraphPicker. Escape
  // is two-stage: a non-empty query clears; an empty query closes. Consumed in
  // capture phase so App's Escape cascade never fires through the catalog.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
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
  }, [open]);

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

  const toggleSection = (id: CategoryId) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const insert = async (specId: string) => {
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
      setOpen(false);
      onSelectNode(id);
    } catch {
      // A mint failure is already surfaced on the store's writeError banner.
    } finally {
      setInserting(false);
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
              value={query}
              onChange={(event) => setQuery(event.target.value)}
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
                  const expanded = searching || !collapsed.has(section.id);
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
                        onClick={() => toggleSection(section.id)}
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
                          {entries.map(({ spec, category, summary }) => (
                            <li key={spec.id}>
                              <button
                                type="button"
                                className="ge-catalog__entry"
                                data-testid="node-catalog-entry"
                                data-spec-id={spec.id}
                                data-category={category}
                                role="option"
                                aria-selected={false}
                                disabled={inserting}
                                title={summary || `add a ${spec.id} node`}
                                onClick={() => void insert(spec.id)}
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
                          ))}
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
