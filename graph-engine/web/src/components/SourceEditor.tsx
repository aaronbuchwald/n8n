import { Suspense, lazy, useCallback, useEffect, useState } from 'react';

import { createSource, fetchSource, fetchSourceTargets, saveSource, type SourceTarget } from '../api';
import { ingestSource, ingestSourceSave, setSourceDirty } from '../store/sync';
import { useSyncSelector } from '../store/useSyncSelector';

// Monaco is heavy; load it as its own chunk only when the source editor opens.
const MonacoEditor = lazy(() => import('../monaco/MonacoEditor'));

// D7's pre-filled template: a commented starting point, not a blank buffer.
const NEW_NODE_TEMPLATE = `@node
def my_node(value: float, factor: float = 1.0) -> float:
    """One line about what this computes."""
    return value * factor
`;

interface EditSourceEditorProps {
  mode?: 'edit';
  /** The node type (spec id, `module.qualname`) whose @node function is edited. */
  specId: string;
  /** How many canvas nodes share this type — the honesty label when > 1. */
  sharedNodeCount: number;
  onClose: () => void; // back to the inspector view
}

interface CreateSourceEditorProps {
  mode: 'create';
  onClose: () => void;
  /** Fired after a successful create with the new type's spec id, so a caller
   * (e.g. the canvas) can place a node of it right away — "author → place →
   * wire" as one flow (D7). Optional: creating in isolation is also valid. */
  onCreated?: (specId: string) => void;
}

type SourceEditorProps = EditSourceEditorProps | CreateSourceEditorProps;

/**
 * View + edit the source of the selected node's `@node` function, expanded
 * inside the node inspector; **or** author a brand-new one (`mode: "create"`,
 * ADR 0011 D7) — dispatches to the two variants below, which share the Monaco
 * shell but differ in what they read/write and what the header shows.
 */
export function SourceEditor(props: SourceEditorProps) {
  if (props.mode === 'create') return <CreateSourceEditor {...props} />;
  return <EditSourceEditor {...props} />;
}

/**
 * Edit an EXISTING `@node` function. The panel is launched from a node but
 * edits the node TYPE's function (several nodes may share it), so the header
 * names the function — not the node id. Saving writes the def back into the
 * REAL .py file on the current branch (`PUT /api/source/{id}`) and
 * re-introspects the module, so signature changes flow into the palette.
 */
function EditSourceEditor({ specId, sharedNodeCount, onClose }: EditSourceEditorProps) {
  // The source cache lives in the store now (Gap G5): the path·lines basis is
  // one shared value, so a wiring/source write elsewhere refreshes this label
  // instead of leaving a stale per-view snapshot. The editable draft stays local.
  const info = useSyncSelector((s) => s.sources[specId] ?? null);
  // The selected entry point (ADR 0009): read from the store rather than
  // threaded down as a prop, so App stays a thin shell — the id lives in one
  // place and every scoped read/write (this one included) keys off it.
  const graphId = useSyncSelector((s) => s.graphId);
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
    fetchSource(specId, graphId)
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
  }, [specId, graphId]);

  // Report the unsaved-buffer state to the store; the app's switch-graph guard
  // is the one consumer (ADR 0009 D6). Closing/unmounting this editor clears it
  // — there is nothing left open to lose.
  const dirty = loaded && info !== null && text !== info.source;
  useEffect(() => {
    setSourceDirty(dirty);
    return () => setSourceDirty(false);
  }, [dirty]);

  const onSave = useCallback(async () => {
    setPending(true);
    setError(null);
    setNotice(null);
    try {
      const result = await saveSource(specId, text, graphId);
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
  }, [specId, text, graphId]);

  return (
    <div className="ge-source" data-testid="source-editor" aria-label={`Source of ${specId}`}>
      <div className="ge-source__head">
        <span className="ge-source__title">node definition</span>
        <button
          type="button"
          className="ge-btn ge-btn--ghost"
          data-testid="source-back"
          onClick={onClose}
        >
          ‹ back to instance
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

/**
 * Author a brand-new `@node` function (ADR 0011 D7/HD1, stream 11-W6).
 * Pre-filled with a commented template; the destination line is **always
 * visible before the write happens** — "will be written to `<path>`
 * (change)" — never a silently-chosen default (HD1's key property). "(change)"
 * opens a picker over the modules `GET /api/source-targets` reports eligible
 * (the workspace module + every already-imported pack module inside
 * `allowed_roots`). Submitting calls `POST /api/source`; success ingests the
 * response the same way a source save does, so the next `GET /api/specs` (or
 * any already-open palette re-fetch) shows the new type immediately.
 */
function CreateSourceEditor({ onClose, onCreated }: CreateSourceEditorProps) {
  const [text, setText] = useState(NEW_NODE_TEMPLATE);
  const [targets, setTargets] = useState<SourceTarget[]>([]);
  const [targetModule, setTargetModule] = useState<string | null>(null);
  const [targetsLoaded, setTargetsLoaded] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchSourceTargets()
      .then((list) => {
        if (cancelled) return;
        setTargets(list);
        // list_target_modules() puts the workspace's own module first — the
        // HD1 default destination — so an unset selection just follows it.
        setTargetModule((current) => current ?? list[0]?.module ?? null);
        setTargetsLoaded(true);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const destination = targets.find((t) => t.module === targetModule) ?? null;

  const onCreate = useCallback(async () => {
    setPending(true);
    setError(null);
    setNotice(null);
    try {
      const result = await createSource(text, targetModule ?? undefined);
      // Same shape as a source-save response (spec/source/graph): one ingest
      // path handles both, so the palette's next specs read shows the type.
      ingestSourceSave(result);
      setNotice(
        result.graphErrors.length > 0
          ? `Created ${result.qualname} → written to ${result.path}, but the graph no longer binds: ${result.graphErrors[0].message}`
          : `Created ${result.qualname} → written to ${result.path}`,
      );
      onCreated?.(result.specId);
    } catch (err: unknown) {
      // A rejected create (syntax error, name collision, reload failure): no
      // file was written — surface the reason inline and keep the draft.
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPending(false);
    }
  }, [text, targetModule, onCreated]);

  return (
    <div className="ge-source" data-testid="source-editor" aria-label="Author a new node">
      <div className="ge-source__head">
        <span className="ge-source__title">new @node</span>
        <button
          type="button"
          className="ge-btn ge-btn--ghost"
          data-testid="source-back"
          onClick={onClose}
        >
          ‹ Close
        </button>
      </div>

      {/* HD1's key property: the destination is shown BEFORE the write, never
          a silent auto-placement — always rendered once targets have loaded,
          regardless of whether the user ever opens the picker. */}
      <div className="ge-source__dest" data-testid="source-dest">
        {destination ? (
          <>
            will be written to <code className="ge-source__dest-path">{destination.path}</code>{' '}
            <button
              type="button"
              className="ge-source__dest-change"
              data-testid="source-dest-change"
              onClick={() => setPickerOpen((open) => !open)}
              aria-expanded={pickerOpen}
            >
              (change)
            </button>
          </>
        ) : (
          'resolving destination…'
        )}
      </div>
      {pickerOpen && (
        <ul className="ge-source__dest-picker" data-testid="source-dest-picker">
          {targets.map((target, i) => (
            <li key={target.module}>
              <button
                type="button"
                className="ge-btn ge-btn--ghost ge-source__dest-option"
                data-testid={`source-dest-option-${target.module}`}
                onClick={() => {
                  setTargetModule(target.module);
                  setPickerOpen(false);
                }}
              >
                {target.path}
                {i === 0 && <span className="ge-source__dest-default"> (default)</span>}
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="ge-source__editor" data-testid="source-editor-body">
        <Suspense
          fallback={
            <div className="ge-source__loading" data-testid="source-loading">
              Loading editor…
            </div>
          }
        >
          <MonacoEditor value={text} readOnly={false} onChange={setText} />
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
        <button
          type="button"
          className="ge-btn ge-btn--primary"
          data-testid="source-save-button"
          disabled={!targetsLoaded || pending}
          onClick={onCreate}
        >
          {pending ? 'Creating…' : 'Create node'}
        </button>
      </div>
    </div>
  );
}
