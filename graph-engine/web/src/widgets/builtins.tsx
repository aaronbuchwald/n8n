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

/**
 * `kind: "text"` — a string editor. `config.placeholder`/`maxLength` honored.
 *
 * Single-line by default; a `<textarea>` when the value is multi-line (ADR 0018
 * D2 tier 1). Promotion is either **declared** (`Widget("text", multiline=True)`)
 * or **by content**: a committed value containing a newline cannot even be
 * *displayed* in a single-line `<input>`, let alone edited, so it promotes
 * itself. Content promotion reads the COMMITTED value only — never the draft —
 * so the editor can never change shape mid-edit.
 */
export function TextEditor({ value, config, input, onCommit }: WidgetEditorProps) {
  const committed = asString(value);
  const [draft, setDraft] = useState(committed);
  useEffect(() => setDraft(asString(value)), [value]);

  const commit = () => {
    if (draft !== value) onCommit(draft);
  };
  const placeholder = typeof config.placeholder === 'string' ? config.placeholder : input.name;
  const maxLength = typeof config.maxLength === 'number' ? config.maxLength : undefined;

  if (config.multiline === true || committed.includes('\n')) {
    return (
      <textarea
        className="ge-widget-input ge-widget-textarea"
        data-testid="widget-editor-text-multiline"
        rows={Math.max(2, draft.split('\n').length)}
        value={draft}
        placeholder={placeholder}
        maxLength={maxLength}
        spellCheck={false}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        // D5: in a multi-line editor Enter is a NEWLINE and never commits;
        // ⌘/Ctrl+Enter and focus leaving the field are the two commit gestures
        // — verbatim the calc editor's model.
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            commit();
          }
        }}
      />
    );
  }

  return (
    <input
      className="ge-widget-input"
      data-testid="widget-editor-text"
      type="text"
      value={draft}
      placeholder={placeholder}
      maxLength={maxLength}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      // Single-line: Enter has no other meaning here, so it keeps committing.
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
