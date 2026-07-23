import { useCallback, useEffect, useState } from 'react';

import { exportGraph, fetchLiveGraph, runGraph } from './api';
import { BranchBadge } from './components/BranchBadge';
import { ExportPanel } from './components/ExportPanel';
import { RunResultsPanel } from './components/RunResultsPanel';
import { GraphView, type FocusRequest } from './GraphView';
import {
  clearRun,
  commitLiteral,
  hydrate,
  selectRunIsStale,
  setRun,
  setWriteError,
} from './store/sync';
import { useSyncSelector } from './store/useSyncSelector';
import { WidgetEditingProvider } from './widgets';

// The shell owns only the boot lifecycle + transient action state. Every shared
// value (graph, specs, version, run, staleness) lives in the store (8-S1) and is
// read here via selectors — App no longer holds a copy of any of it, so there is
// no cache to invalidate by hand. `rev`/`runRev`/`reloadSeq` from 8-P0 became
// the store's `rev` + `run.forRev` + seq-gated `ingestGraph`.
type BootState = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready' };

// One action's lifecycle (Run or Export). `error` here is a transport-level
// failure (server unreachable) — engine-level run errors travel inside RunResult.
interface ActionState {
  pending: boolean;
  error: string | null;
}

const IDLE: ActionState = { pending: false, error: null };

export default function App() {
  const [boot, setBoot] = useState<BootState>({ status: 'loading' });
  const [runState, setRunState] = useState<ActionState>(IDLE);
  const [python, setPython] = useState<string | null>(null);
  const [exportState, setExportState] = useState<ActionState>(IDLE);
  // The inspected node. Owned here (not in GraphView) so run-results rows can
  // select it and the Escape handler below can close it.
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  // Whether the inspector is expanded into the selected node's source editor.
  const [editingSource, setEditingSource] = useState(false);
  const [focusRequest, setFocusRequest] = useState<FocusRequest | null>(null);

  // --- store reads (selectors return stored refs or primitives) ---------------
  const graph = useSyncSelector((s) => s.effective.graph);
  const specs = useSyncSelector((s) => s.specs);
  const version = useSyncSelector((s) => s.version);
  const run = useSyncSelector((s) => s.run);
  const runIsStale = useSyncSelector(selectRunIsStale);
  // A failed widget commit lands here (the queue, being hookless, writes it to
  // the store). Auto-clears so it never lingers over the canvas.
  const writeError = useSyncSelector((s) => s.writeError);

  // Boot: one authoritative load → hydrate the store. There is no more quiet
  // reload (writes return truth and are ingested from their responses), so the
  // seq-guarded reload race (G2) and the quiet-reload-unmounts-workspace bug
  // (G7) are gone by construction.
  useEffect(() => {
    let cancelled = false;
    fetchLiveGraph()
      .then((live) => {
        if (cancelled) return;
        hydrate(live);
        setBoot({ status: 'ready' });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setBoot({ status: 'error', message: err instanceof Error ? err.message : String(err) });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Selecting a node (or clearing the selection) always lands on the inspector
  // view first — the source editor is scoped to the node that opened it.
  const selectNode = useCallback((nodeId: string | null) => {
    setSelectedNodeId(nodeId);
    setEditingSource(false);
  }, []);

  // A run-results row was clicked: open the inspector for that node and ask
  // the canvas to centre it.
  const onFocusNode = useCallback(
    (nodeId: string) => {
      selectNode(nodeId);
      setFocusRequest({ nodeId, token: Date.now() });
    },
    [selectNode],
  );

  useEffect(() => {
    if (!writeError) return;
    const timer = window.setTimeout(() => setWriteError(null), 6000);
    return () => window.clearTimeout(timer);
  }, [writeError]);

  // Escape dismisses the topmost open surface, one per press: the source
  // editor (back to the inspector), then the inspector, then the export dock,
  // then run results. Widget editors handle their own keys (the slot is
  // skipped here), and Escape typed INSIDE the source editor is deliberately
  // inert so a stray press can't discard an unsaved body edit.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented) return;
      if (
        event.target instanceof Element &&
        event.target.closest('[data-testid="widget-slot"], .ge-source')
      ) {
        return;
      }
      if (selectedNodeId && editingSource) {
        setEditingSource(false);
      } else if (selectedNodeId) {
        setSelectedNodeId(null);
      } else if (python !== null) {
        setPython(null);
      } else if (run) {
        clearRun();
      } else {
        return;
      }
      event.preventDefault();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [selectedNodeId, editingSource, python, run]);

  const onRun = useCallback(async () => {
    if (!graph) return;
    setRunState({ pending: true, error: null });
    try {
      const result = await runGraph(graph);
      setRun(result); // stamped with the current rev inside the store (epoch)
    } catch (err: unknown) {
      // Transport failure (server down): clear stale results, show the banner.
      clearRun();
      setRunState({ pending: false, error: err instanceof Error ? err.message : String(err) });
      return;
    }
    setRunState(IDLE);
  }, [graph]);

  const onExport = useCallback(async () => {
    if (!graph) return;
    setExportState({ pending: true, error: null });
    try {
      const result = await exportGraph(graph);
      setPython(result.python);
    } catch (err: unknown) {
      setPython(null);
      setExportState({ pending: false, error: err instanceof Error ? err.message : String(err) });
      return;
    }
    setExportState(IDLE);
  }, [graph]);

  const ready = boot.status === 'ready' && graph !== null;

  return (
    <div className="ge-app">
      <header className="ge-topbar">
        <h1 className="ge-topbar__title">graph-engine</h1>
        <span className="ge-topbar__sub">
          live graph{version ? ` · contract v${version}` : ''}
        </span>
        <BranchBadge />

        <div className="ge-toolbar">
          <button
            type="button"
            className="ge-btn ge-btn--primary"
            data-testid="run-button"
            disabled={!ready || runState.pending}
            onClick={onRun}
          >
            {runState.pending ? 'Running…' : 'Run'}
          </button>
          <button
            type="button"
            className="ge-btn"
            data-testid="export-button"
            disabled={!ready || exportState.pending}
            onClick={onExport}
          >
            {exportState.pending ? 'Exporting…' : 'Export Python'}
          </button>
        </div>

        <span className="ge-topbar__out" data-testid="graph-output-label">
          output → {graph?.output ? `${graph.output.node}.${graph.output.socket}` : 'none'}
        </span>
      </header>

      {(runState.error || exportState.error || writeError) && (
        <div className="ge-actionbar-error" data-testid="action-error" role="alert">
          {runState.error ?? exportState.error ?? writeError}
        </div>
      )}

      {runIsStale && (
        <div className="ge-run-stale" data-testid="run-stale-banner" role="status">
          <span className="ge-run-stale__text">results from before your edit</span>
          <button
            type="button"
            className="ge-btn ge-btn--primary ge-run-stale__rerun"
            data-testid="run-stale-rerun"
            disabled={!ready || runState.pending}
            onClick={onRun}
          >
            {runState.pending ? 'Running…' : 'Run again'}
          </button>
        </div>
      )}

      {boot.status === 'loading' && (
        <div className="ge-status" data-testid="app-loading">
          <span className="ge-status__spinner" aria-hidden="true" />
          Loading graph from the server…
        </div>
      )}

      {boot.status === 'error' && (
        <div className="ge-status ge-status--error" data-testid="app-error" role="alert">
          <strong className="ge-status__title">Couldn’t load the graph</strong>
          <span className="ge-status__detail">{boot.message}</span>
          <span className="ge-status__hint">Check that the API server is running, then reload.</span>
        </div>
      )}

      {ready && (
        <div className="ge-main">
          <div className="ge-workspace">
            {/* The commit seam (A-D5): the store's stable `commitLiteral` — a
                module function, so no context churn re-renders every chip (R2).
                Absence of a provider is still read-only (WidgetSlot). */}
            <WidgetEditingProvider value={commitLiteral}>
              <GraphView
                selectedNodeId={selectedNodeId}
                onSelectNode={selectNode}
                focusRequest={focusRequest}
                editingSource={editingSource}
                onEditSourceChange={setEditingSource}
              />
            </WidgetEditingProvider>
            {run && graph && (
              <RunResultsPanel
                run={run}
                graph={graph}
                specs={specs}
                runIsStale={runIsStale}
                onFocusNode={onFocusNode}
                onClose={clearRun}
              />
            )}
          </div>
          {python !== null && <ExportPanel python={python} onClose={() => setPython(null)} />}
        </div>
      )}
    </div>
  );
}
