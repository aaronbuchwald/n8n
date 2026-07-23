import { useEffect, useRef, useState } from 'react';

import { fetchGraphs, type GraphEntry, type GraphsResponse } from '../api';

interface GraphPickerProps {
  /** The selected entry id (the `?graph=` URL param); null = server default. */
  selectedId: string | null;
  onSelect: (id: string) => void;
}

/**
 * Top-bar dropdown listing every viewable entry point (ADR 0009 D6). Same
 * self-contained pattern as `BranchBadge`: fetches `GET /api/graphs` itself,
 * renders nothing until it resolves, and hides entirely when the catalog has
 * ≤ 1 entry — the single-program experience stays pixel-identical.
 *
 * Deliberately store-less (the ADR 0008 seam): one fetch on mount, no polling,
 * no caching of anything but the listing it renders. Selection is a plain
 * input signal — the picker only reports the chosen id upward; the app moves
 * the `?graph=` key and everything else reacts to it.
 */
export function GraphPicker({ selectedId, onSelect }: GraphPickerProps) {
  const [data, setData] = useState<GraphsResponse | null>(null);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    fetchGraphs()
      .then((response) => {
        if (!cancelled) setData(response);
      })
      .catch(() => {
        // An older server without the catalog — stay hidden, app falls back
        // to the unscoped routes.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Light dismiss: click outside or Escape closes the menu. Escape is consumed
  // (preventDefault) so the app's own Escape cascade never fires through it.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (rootRef.current && event.target instanceof Node && !rootRef.current.contains(event.target)) {
        setOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onPointerDown);
    window.addEventListener('keydown', onKeyDown, true);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      window.removeEventListener('keydown', onKeyDown, true);
    };
  }, [open]);

  // Hidden until the list resolves, and with ≤ 1 entry (ADR 0009 D6).
  if (!data || data.entries.length <= 1) return null;

  const currentId = selectedId ?? data.default;
  const current: GraphEntry | undefined = data.entries.find((e) => e.id === currentId);

  const choose = (entry: GraphEntry) => {
    setOpen(false);
    if (entry.status === 'ok' && entry.id !== currentId) onSelect(entry.id);
  };

  return (
    <div className="ge-picker" ref={rootRef} data-testid="graph-picker">
      <button
        type="button"
        className="ge-picker__button"
        data-testid="graph-picker-button"
        aria-haspopup="listbox"
        aria-expanded={open}
        title={current?.path ?? undefined}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="ge-picker__label">{current?.title ?? currentId ?? 'graphs'}</span>
        <span className="ge-picker__caret" aria-hidden="true">
          ▾
        </span>
      </button>
      {open && (
        <ul className="ge-picker__menu" role="listbox" data-testid="graph-picker-menu">
          {data.entries.map((entry) => (
            <li key={entry.id} role="presentation">
              <button
                type="button"
                role="option"
                aria-selected={entry.id === currentId}
                className={
                  'ge-picker__option' +
                  (entry.id === currentId ? ' ge-picker__option--current' : '') +
                  (entry.status === 'error' ? ' ge-picker__option--error' : '')
                }
                data-testid={`graph-picker-option-${entry.id}`}
                disabled={entry.status === 'error'}
                title={entry.status === 'error' ? entry.error : entry.path ?? undefined}
                onClick={() => choose(entry)}
              >
                <span className="ge-picker__option-title">
                  {entry.title}
                  {entry.status === 'error' && (
                    <span className="ge-picker__option-flag"> · unavailable</span>
                  )}
                </span>
                {entry.path && <span className="ge-picker__option-path">{entry.path}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
