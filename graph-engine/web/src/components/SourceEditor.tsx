import { useCallback, useEffect, useState } from 'react';

import { fetchSource, saveSource, type SourceInfo } from '../api';

interface SourceEditorProps {
  /** The node type (spec id, `module.qualname`) whose @node function is edited. */
  specId: string;
  /** How many canvas nodes share this type — the honesty label when > 1. */
  sharedNodeCount: number;
  onSaved: () => void; // refresh specs/graph after a successful write
  onClose: () => void; // back to the inspector view
}

/**
 * View + edit the source of the selected node's `@node` function, expanded
 * inside the node inspector. The panel is launched from a node but edits the
 * node TYPE's function (several nodes may share it), so the header names the
 * function — not the node id. Saving writes the def back into the REAL .py
 * file on the current branch (`PUT /api/source/{id}`) and re-introspects the
 * module, so signature changes flow into the palette. A plain monospace
 * textarea by design (no editor dependency for now).
 */
export function SourceEditor({ specId, sharedNodeCount, onSaved, onClose }: SourceEditorProps) {
  const [info, setInfo] = useState<SourceInfo | null>(null);
  const [text, setText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
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
      // A rejected save (syntax error, wrong function, reload failure): the
      // file on disk is untouched — surface the reason inline and keep editing.
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPending(false);
    }
  }, [specId, text, onSaved]);

  return (
    <div className="ge-source" data-testid="source-editor" aria-label={`Source of ${specId}`}>
      <div className="ge-source__head">
        <span className="ge-source__title">@node source</span>
        <button
          type="button"
          className="ge-btn ge-btn--ghost"
          data-testid="source-back"
          onClick={onClose}
        >
          ‹ Inspector
        </button>
      </div>

      {/* The function this panel edits — the node's TYPE, shared by every node
          of that type, so it is labelled by function, not by node id. */}
      <div className="ge-source__fn" data-testid="source-fn-label" title={specId}>
        {specId}
      </div>
      {info && (
        <div className="ge-source__file" data-testid="source-file-label">
          {info.path} · lines {info.startLine}–{info.endLine}
        </div>
      )}
      {sharedNodeCount > 1 && (
        <div className="ge-source__shared" data-testid="source-shared-note">
          Shared function — saving affects all {sharedNodeCount} nodes of this type.
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
        <span className="ge-source__sub">writes to the real .py on this branch</span>
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
    </div>
  );
}
