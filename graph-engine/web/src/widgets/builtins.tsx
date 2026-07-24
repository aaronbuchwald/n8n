// Built-in editors for the core widget kinds (ADR 0005 A-D4): number, text,
// checkbox. Small, eager, dependency-free — the reference implementation of the
// frozen editor-props contract. Heavy editors (math, table-recipe) live in
// their own lazy chunks and are added by streams B / C-ui.

import { useEffect, useState } from 'react';
import type { WidgetEditorProps } from './registry';

// Text/number commit on blur or Enter — not per keystroke — because each commit
// PUTs /api/graph (A-D5: the keystroke layer is JS-only UX). Local state tracks
// the in-progress edit and re-syncs if the bound value changes underneath.

function asString(value: unknown): string {
  if (value === undefined || value === null) return '';
  return typeof value === 'string' ? value : String(value);
}

/** `kind: "text"` — a single-line string editor. `config.placeholder`/`maxLength` honored. */
export function TextEditor({ value, config, input, onCommit }: WidgetEditorProps) {
  const [draft, setDraft] = useState(asString(value));
  useEffect(() => setDraft(asString(value)), [value]);

  const commit = () => {
    if (draft !== value) onCommit(draft);
  };
  return (
    <input
      className="ge-widget-input"
      data-testid="widget-editor-text"
      type="text"
      value={draft}
      placeholder={typeof config.placeholder === 'string' ? config.placeholder : input.name}
      maxLength={typeof config.maxLength === 'number' ? config.maxLength : undefined}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') e.currentTarget.blur();
      }}
    />
  );
}

/** `kind: "number"` — an int/float editor; commits a `number` literal (empty -> null). */
export function NumberEditor({ value, config, input, onCommit }: WidgetEditorProps) {
  const [draft, setDraft] = useState(asString(value));
  useEffect(() => setDraft(asString(value)), [value]);

  const isInt =
    input.type === 'int' || input.widget?.subtype === 'int' || config.subtype === 'int';
  const commit = () => {
    const trimmed = draft.trim();
    if (trimmed === '') {
      if (value !== null) onCommit(null);
      return;
    }
    const parsed = Number(trimmed);
    // Guard against NaN/Infinity — neither round-trips (A-D5). Invalid input is
    // left for the node body to reject at run; we just don't commit garbage.
    if (!Number.isFinite(parsed)) return;
    // An int input must never persist a float into the source (Python would
    // only object at the next run): round, and show what actually committed.
    const next = isInt ? Math.round(parsed) : parsed;
    setDraft(asString(next));
    if (next !== value) onCommit(next);
  };
  return (
    <input
      className="ge-widget-input"
      data-testid="widget-editor-number"
      type="number"
      inputMode={isInt ? 'numeric' : 'decimal'}
      step={isInt ? 1 : 'any'}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') e.currentTarget.blur();
      }}
    />
  );
}

/** `kind: "checkbox"` — a boolean toggle; commits immediately (no partial state). */
export function CheckboxEditor({ value, input, onCommit }: WidgetEditorProps) {
  return (
    <input
      className="ge-widget-checkbox"
      data-testid="widget-editor-checkbox"
      type="checkbox"
      aria-label={input.name}
      checked={value === true}
      onChange={(e) => onCommit(e.target.checked)}
    />
  );
}
