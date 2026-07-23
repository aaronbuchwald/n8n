// ADR 0011 stream W5 — the node palette: a grouped, searchable projection of
// `GET /api/specs` (D1; `registry.specs()` is "the palette a UI renders from").
// It reads specs from the store (hydrated at boot, refreshed by source saves),
// groups them by module/pack, and filters by name/doc.
//
// Click-to-place is the standalone add affordance: clicking an entry calls the
// store's `createNode(type, position)` — the same action 11-W4's canvas will
// call on drag-drop. The strip at the bottom surfaces the latest edit-mode
// validation as per-node "needs wiring" badges (D6), W5's stand-in until W4
// badges them on the canvas from the same store field.

import { useMemo, useState } from 'react';

import { createNode } from '../store/sync';
import { useSyncSelector } from '../store/useSyncSelector';
import type { NodeSpec } from '../types';

interface PaletteEntry {
  spec: NodeSpec;
  summary: string; // first doc line, '' when undocumented
}

interface PaletteGroup {
  module: string;
  entries: PaletteEntry[];
}

/** First line of the spec's docstring — the entry's one-line summary. */
function firstDocLine(doc: string): string {
  const newline = doc.indexOf('\n');
  return (newline === -1 ? doc : doc.slice(0, newline)).trim();
}

/**
 * Default drop point for click-to-place, staggered by how many nodes the graph
 * already has so consecutive adds never stack exactly. W4's drag-drop passes
 * the real drop position instead.
 */
function defaultPosition(nodeCount: number): { x: number; y: number } {
  return { x: 80 + (nodeCount % 6) * 48, y: 80 + (nodeCount % 10) * 40 };
}

export function Palette() {
  const specs = useSyncSelector((s) => s.specs);
  const incomplete = useSyncSelector((s) => s.incomplete);
  const nodesById = useSyncSelector((s) => s.effective.nodesById);
  const [query, setQuery] = useState('');
  const [placing, setPlacing] = useState(false);

  const groups = useMemo<PaletteGroup[]>(() => {
    const needle = query.trim().toLowerCase();
    const byModule = new Map<string, PaletteEntry[]>();
    for (const spec of Object.values(specs)) {
      const summary = firstDocLine(spec.doc);
      if (
        needle &&
        !spec.name.toLowerCase().includes(needle) &&
        !summary.toLowerCase().includes(needle)
      ) {
        continue;
      }
      const entries = byModule.get(spec.module);
      if (entries) entries.push({ spec, summary });
      else byModule.set(spec.module, [{ spec, summary }]);
    }
    return [...byModule.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([module, entries]) => ({
        module,
        entries: entries.sort((a, b) => a.spec.name.localeCompare(b.spec.name)),
      }));
  }, [specs, query]);

  // One badge per incomplete node, its missing inputs joined.
  const needsWiring = useMemo(() => {
    const byNode = new Map<string, string[]>();
    for (const warning of incomplete) {
      const inputs = byNode.get(warning.nodeId);
      if (inputs) inputs.push(warning.input);
      else byNode.set(warning.nodeId, [warning.input]);
    }
    return [...byNode.entries()].map(([nodeId, inputs]) => ({ nodeId, inputs }));
  }, [incomplete]);

  const place = async (specId: string) => {
    if (placing) return;
    setPlacing(true);
    try {
      await createNode(specId, defaultPosition(nodesById.size));
    } catch {
      // Already surfaced on the store's writeError banner.
    } finally {
      setPlacing(false);
    }
  };

  return (
    <aside className="ge-palette" data-testid="palette" aria-label="Node palette">
      <div className="ge-palette__head">
        <span className="ge-palette__title">Nodes</span>
        <input
          className="ge-palette__search"
          data-testid="palette-search"
          type="search"
          placeholder="Search nodes…"
          aria-label="Search nodes"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      <div className="ge-palette__groups">
        {groups.map(({ module, entries }) => (
          <section
            key={module}
            className="ge-palette__group"
            data-testid="palette-group"
            data-module={module}
          >
            <h3 className="ge-palette__group-name">{module}</h3>
            <ul className="ge-palette__list">
              {entries.map(({ spec, summary }) => (
                <li key={spec.id}>
                  <button
                    type="button"
                    className="ge-palette__entry"
                    data-testid="palette-entry"
                    data-spec-id={spec.id}
                    disabled={placing}
                    title={`add a ${spec.id} node to the graph`}
                    onClick={() => void place(spec.id)}
                  >
                    <span className="ge-palette__entry-name">{spec.name}</span>
                    {summary && <span className="ge-palette__entry-doc">{summary}</span>}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
        {groups.length === 0 && (
          <p className="ge-palette__empty" data-testid="palette-empty">
            no nodes match “{query.trim()}”
          </p>
        )}
      </div>

      {needsWiring.length > 0 && (
        <div className="ge-palette__wiring" data-testid="needs-wiring" role="status">
          {needsWiring.map(({ nodeId, inputs }) => (
            <span
              key={nodeId}
              className="ge-palette__wiring-badge"
              data-testid="needs-wiring-badge"
              data-node-id={nodeId}
            >
              {nodeId} needs wiring: {inputs.join(', ')}
            </span>
          ))}
        </div>
      )}
    </aside>
  );
}
