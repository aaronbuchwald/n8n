import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  exportGraph,
  fetchLiveGraph,
  runGraph,
  type LiveGraph,
  type RunResult,
  type SaveGraphResult,
} from './api';
import { BranchBadge } from './components/BranchBadge';
import { ExportPanel } from './components/ExportPanel';
import { RunResultsPanel } from './components/RunResultsPanel';
import { GraphView, type FocusRequest } from './GraphView';
import { makeGraphCommitter, WidgetEditingProvider } from './widgets';

type LoadState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: LiveGraph };

// One action's lifecycle (Run or Export). `error` here is a transport-level
// failure (server unreachable) — engine-level run errors travel inside RunResult.
interface ActionState {
  pending: boolean;
  error: string | null;
}

const IDLE: ActionState = { pending: false, error: null };

export default function App() {
  const [state, setState] = useState<LoadState>({ status: 'loading' });
  const [run, setRun] = useState<RunResult | null>(null);
  // A monotone revision of the authoritative graph — bumps on every user edit
  // (source save or widget commit). `run` is stamped with the revision it
  // executed against (`runRev`); when they diverge the run's values predate the
  // edit and every surface that shows them renders honestly stale (ADR 0008 G1).
  const [rev, setRev] = useState(0);
  const [runRev, setRunRev] = useState<number | null>(null);
  // A *quiet* reload (after a source save) that fails must not tear the live
  // workspace down into a full-screen error (ADR 0008 G7) — it surfaces here as
  // a banner instead, over a canvas that still shows the just-saved state.
  const [reloadError, setReloadError] = useState<string | null>(null);
  const [runState, setRunState] = useState<ActionState>(IDLE);
  const [python, setPython] = useState<string | null>(null);
  const [exportState, setExportState] = useState<ActionState>(IDLE);
  // A failed widget commit surfaces here as a transient banner (A-D5: PUT
  // /api/graph rejected). Auto-clears so it never lingers over the canvas.
  const [widgetError, setWidgetError] = useState<string | null>(null);
  // The inspected node. Owned here (not in GraphView) so run-results rows can
  // select it and the Escape handler below can close it.
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  // Whether the inspector is expanded into the selected node's source editor.
  // Owned here so a selection change resets it and Escape can step it closed.
  const [editingSource, setEditingSource] = useState(false);
  const [focusRequest, setFocusRequest] = useState<FocusRequest | null>(null);

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

  // Guards every reload against the last one it issued: two overlapping quiet
  // reloads (rapid edits) can resolve out of order, and without this the older
  // response would overwrite the newer graph and stick a stale canvas (G2).
  const reloadSeq = useRef(0);

  // `quiet` refreshes in place (no loading flash) — used after a source save
  // so the open editor panel isn't unmounted mid-edit.
  const reload = useCallback(async (opts?: { quiet?: boolean }) => {
    const seq = ++reloadSeq.current;
    if (!opts?.quiet) setState({ status: 'loading' });
    try {
      const data = await fetchLiveGraph();
      if (seq !== reloadSeq.current) return; // a newer reload superseded this one
      setState({ status: 'ready', data });
      setReloadError(null);
    } catch (err: unknown) {
      if (seq !== reloadSeq.current) return;
      const message = err instanceof Error ? err.message : String(err);
      // A quiet reload runs AFTER a write the server already accepted — failing
      // to re-fetch is a transient read error, not a reason to unmount the
      // workspace (G7). Loud (boot) reloads still show the full error state.
      if (opts?.quiet) setReloadError(message);
      else setState({ status: 'error', message });
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  // A source save rewrote the .py: bump the revision so the last run's values
  // read as stale immediately (G1), then quietly re-fetch the re-projected graph
  // the server now serves (G3) without unmounting the open editor.
  const onSourceSaved = useCallback(() => {
    setRev((r) => r + 1);
    void reload({ quiet: true });
  }, [reload]);

  // A widget commit persisted: the PUT response already carries the authoritative
  // re-served graph, so patch it straight onto `state.data` (GraphView folds the
  // new literals onto the canvas in place) — no post-commit reload (G4). Bump the
  // revision so run-derived values read as stale until the next run (G1). A
  // failed commit surfaces the message; the banner self-dismisses.
  const onWidgetSaved = useCallback((result: SaveGraphResult) => {
    setWidgetError(null);
    setRev((r) => r + 1);
    setState((prev) =>
      prev.status === 'ready'
        ? { status: 'ready', data: { ...prev.data, graph: result.graph } }
        : prev,
    );
  }, []);
  const onWidgetError = useCallback((error: Error) => {
    setWidgetError(error.message);
  }, []);

  useEffect(() => {
    if (!widgetError) return;
    const timer = window.setTimeout(() => setWidgetError(null), 6000);
    return () => window.clearTimeout(timer);
  }, [widgetError]);

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
        setRun(null);
      } else {
        return;
      }
      event.preventDefault();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [selectedNodeId, editingSource, python, run]);

  const graph = state.status === 'ready' ? state.data.graph : null;

  // The commit seam (A-D5): mounted only when a graph is loaded, so editors are
  // live on the ready canvas and read-only otherwise. Recreated when the graph
  // identity changes so a commit always diffs against the freshest served graph.
  const commit = useMemo(
    () => (graph ? makeGraphCommitter(graph, onWidgetSaved, onWidgetError) : null),
    [graph, onWidgetSaved, onWidgetError],
  );
  // Contract version comes from /api/specs (the palette contract), per ADR 0002.
  const version = state.status === 'ready' ? state.data.version : null;

  const onRun = useCallback(async () => {
    if (!graph) return;
    setRunState({ pending: true, error: null });
    try {
      const result = await runGraph(graph);
      setRun(result);
      setRunRev(rev); // stamp the run with the graph revision it executed against
    } catch (err: unknown) {
      // Transport failure (server down): clear stale results, show the banner.
      setRun(null);
      setRunState({ pending: false, error: err instanceof Error ? err.message : String(err) });
      return;
    }
    setRunState(IDLE);
  }, [graph, rev]);

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

  // The node an engine run error points at (marked on the canvas).
  const errorNodeId = run?.errors.find((e) => e.nodeId)?.nodeId ?? null;

  // The current run's values predate the latest edit: every surface that shows
  // them (canvas result chips, run-results value lines) renders them dimmed and
  // the banner below offers a one-click re-run (ADR 0008 G1; keep-dimmed over
  // setRun(null) — confirmation 1 — so context survives the edit and never lies).
  const runIsStale = run !== null && runRev !== rev;

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
            disabled={state.status !== 'ready' || runState.pending}
            onClick={onRun}
          >
            {runState.pending ? 'Running…' : 'Run'}
          </button>
          <button
            type="button"
            className="ge-btn"
            data-testid="export-button"
            disabled={state.status !== 'ready' || exportState.pending}
            onClick={onExport}
          >
            {exportState.pending ? 'Exporting…' : 'Export Python'}
          </button>
        </div>

        <span className="ge-topbar__out" data-testid="graph-output-label">
          output → {graph?.output ? `${graph.output.node}.${graph.output.socket}` : 'none'}
        </span>
      </header>

      {(runState.error || exportState.error || widgetError || reloadError) && (
        <div className="ge-actionbar-error" data-testid="action-error" role="alert">
          {runState.error ?? exportState.error ?? widgetError ?? reloadError}
        </div>
      )}

      {runIsStale && (
        <div className="ge-run-stale" data-testid="run-stale-banner" role="status">
          <span className="ge-run-stale__text">results from before your edit</span>
          <button
            type="button"
            className="ge-btn ge-btn--primary ge-run-stale__rerun"
            data-testid="run-stale-rerun"
            disabled={state.status !== 'ready' || runState.pending}
            onClick={onRun}
          >
            {runState.pending ? 'Running…' : 'Run again'}
          </button>
        </div>
      )}

      {state.status === 'loading' && (
        <div className="ge-status" data-testid="app-loading">
          <span className="ge-status__spinner" aria-hidden="true" />
          Loading graph from the server…
        </div>
      )}

      {state.status === 'error' && (
        <div className="ge-status ge-status--error" data-testid="app-error" role="alert">
          <strong className="ge-status__title">Couldn’t load the graph</strong>
          <span className="ge-status__detail">{state.message}</span>
          <span className="ge-status__hint">Check that the API server is running, then reload.</span>
        </div>
      )}

      {state.status === 'ready' && (
        <div className="ge-main">
          <div className="ge-workspace">
            <WidgetEditingProvider value={commit}>
              <GraphView
                graph={state.data.graph}
                specs={state.data.specs}
                runOutputs={run?.outputs ?? null}
                runIsStale={runIsStale}
                errorNodeId={errorNodeId}
                selectedNodeId={selectedNodeId}
                onSelectNode={selectNode}
                focusRequest={focusRequest}
                editingSource={editingSource}
                onEditSourceChange={setEditingSource}
                onSourceSaved={onSourceSaved}
              />
            </WidgetEditingProvider>
            {run && (
              <RunResultsPanel
                run={run}
                graph={state.data.graph}
                specs={state.data.specs}
                runIsStale={runIsStale}
                onFocusNode={onFocusNode}
                onClose={() => setRun(null)}
              />
            )}
          </div>
          {python !== null && <ExportPanel python={python} onClose={() => setPython(null)} />}
        </div>
      )}
    </div>
  );
}
