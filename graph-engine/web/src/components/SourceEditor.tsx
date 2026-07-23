import { Suspense, lazy, useCallback, useEffect, useState } from 'react';

import { fetchSource, saveSource } from '../api';
import { ingestSource, ingestSourceSave } from '../store/sync';
import { useSyncSelector } from '../store/useSyncSelector';

// Monaco is heavy; load it as its own chunk only when the source editor opens.
const MonacoEditor = lazy(() => import('../monaco/MonacoEditor'));

interface SourceEditorProps {
  /** The node type (spec id, `module.qualname`) whose @node function is edited. */
  specId: string;
  /** How many canvas nodes share this type — the honesty label when > 1. */
  sharedNodeCount: number;
  onClose: () => void; // back to the inspector view
}

/**
 * View + edit the source of the selected node's `@node` function, expanded
 * inside the node inspector. The panel is launched from a node but edits the
 * node TYPE's function (several nodes may share it), so the header names the
 * function — not the node id. Saving writes the def back into the REAL .py
 * file on the current branch (`PUT /api/source/{id}`) and re-introspects the
 * module, so signature changes flow into the palette. The body is a Monaco
 * editor with Python highlighting, fully bundled offline (see monaco/setup.ts).
 */
export function SourceEditor({ specId, sharedNodeCount, onClose }: SourceEditorProps) {
  // The source cache lives in the store now (Gap G5): the path·lines basis is
  // one shared value, so a wiring/source write elsewhere refreshes this label
  // instead of leaving a stale per-view snapshot. The editable draft stays local.
  const info = useSyncSelector((s) => s.sources[specId] ?? null);
  const [text, setText] = useState('');
  const [loaded, setLoaded] = useState(false); // has this editor seeded its draft?
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoaded(false);
    setText('');
    setError(null);
    setNotice(null);
    // Always fetch the authoritative source on open, then seed the draft from it
    // and cache it in the store for every other view.
    fetchSource(specId)
      .then((data) => {
        if (cancelled) return;
        ingestSource(data);
        setText(data.source);
        setLoaded(true);
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
      // The response carries the re-introspected spec, the fresh source AND the
      // re-projected graph — ingest all three from the one write, no reload
      // (Gaps G1/G3/G4); rev bumps so run views read stale and a signature
      // change re-lays-out the card (G6).
      ingestSourceSave(result);
      setText(result.source);
      setNotice(
        result.graphErrors.length > 0
          ? `Saved to ${result.path}, but the graph no longer binds: ${result.graphErrors[0].message}`
          : `Saved to ${result.path}`,
      );
    } catch (err: unknown) {
      // A rejected save (syntax error, wrong function, reload failure): the
      // file on disk is untouched — surface the reason inline and keep editing.
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPending(false);
    }
  }, [specId, text]);

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

      <div className="ge-source__editor" data-testid="source-editor-body">
        <Suspense
          fallback={
            <div className="ge-source__loading" data-testid="source-loading">
              Loading editor…
            </div>
          }
        >
          <MonacoEditor value={text} readOnly={!loaded} onChange={setText} />
        </Suspense>
      </div>

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
          disabled={!loaded || pending}
          onClick={onSave}
        >
          {pending ? 'Saving…' : 'Save to file'}
        </button>
      </div>
    </div>
  );
}
