import { useCallback, useEffect, useState } from 'react';

import { fetchSource, saveSource, type SourceInfo } from '../api';
import type { NodeSpecs } from '../types';

interface SourceEditorProps {
  specs: NodeSpecs;
  onSaved: () => void; // refresh specs/graph after a successful write
  onClose: () => void;
}

/**
 * View + edit the source of a `@node` function. Saving writes the def back
 * into the REAL .py file on the current branch (`PUT /api/source/{id}`) and
 * re-introspects the module, so signature changes flow into the palette.
 * A plain monospace textarea by design (no editor dependency for now).
 */
export function SourceEditor({ specs, onSaved, onClose }: SourceEditorProps) {
  const specIds = Object.keys(specs).sort();
  const [specId, setSpecId] = useState<string>(specIds[0] ?? '');
  const [info, setInfo] = useState<SourceInfo | null>(null);
  const [text, setText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (!specId) return;
    let cancelled = false;
    setInfo(null);
    setError(null);
    setNotice(null);
    fetchSource(specId)
      .then((data) => {
        if (cancelled) return;
        setInfo(data);
        setText(data.source);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [specId]);

  const onSave = useCallback(async () => {
    setPending(true);
    setError(null);
    setNotice(null);
    try {
      const result = await saveSource(specId, text);
      setInfo(result);
      setText(result.source);
      setNotice(
        result.graphErrors.length > 0
          ? `Saved to ${result.path}, but the graph no longer binds: ${result.graphErrors[0].message}`
          : `Saved to ${result.path}`,
      );
      onSaved();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPending(false);
    }
  }, [specId, text, onSaved]);

  return (
    <aside className="ge-source" data-testid="source-editor" aria-label="Node source editor">
      <div className="ge-source__head">
        <span className="ge-source__title">edit @node source</span>
        <span className="ge-source__sub">writes to the real .py on this branch</span>
        <button type="button" className="ge-btn ge-btn--ghost" onClick={onClose}>
          Close
        </button>
      </div>

      <label className="ge-source__field">
        <span className="ge-source__label">node type</span>
        <select
          className="ge-source__select"
          data-testid="source-spec-select"
          value={specId}
          onChange={(event) => setSpecId(event.target.value)}
        >
          {specIds.map((id) => (
            <option key={id} value={id}>
              {id}
            </option>
          ))}
        </select>
      </label>

      {info && (
        <div className="ge-source__file" data-testid="source-file-label">
          {info.path} · lines {info.startLine}–{info.endLine}
        </div>
      )}

      <textarea
        className="ge-source__text"
        data-testid="source-textarea"
        spellCheck={false}
        value={text}
        disabled={info === null}
        onChange={(event) => setText(event.target.value)}
      />

      {error && (
        <div className="ge-source__error" data-testid="source-error" role="alert">
          {error}
        </div>
      )}
      {notice && !error && (
        <div className="ge-source__notice" data-testid="source-notice">
          {notice}
        </div>
      )}

      <div className="ge-source__actions">
        <button
          type="button"
          className="ge-btn ge-btn--primary"
          data-testid="source-save-button"
          disabled={info === null || pending}
          onClick={onSave}
        >
          {pending ? 'Saving…' : 'Save to file'}
        </button>
      </div>
    </aside>
  );
}
