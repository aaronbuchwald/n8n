import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  exportGraph,
  fetchLiveGraph,
  runGraph,
  type LiveGraph,
  type RunResult,
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

  // `quiet` refreshes in place (no loading flash) — used after a source save
  // so the open editor panel isn't unmounted mid-edit.
  const reload = useCallback(async (opts?: { quiet?: boolean }) => {
    if (!opts?.quiet) setState({ status: 'loading' });
    try {
      const data = await fetchLiveGraph();
      setState({ status: 'ready', data });
    } catch (err: unknown) {
      setState({ status: 'error', message: err instanceof Error ? err.message : String(err) });
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const onSourceSaved = useCallback(() => {
    void reload({ quiet: true });
  }, [reload]);

  // A widget commit persisted: refresh the served graph WITHOUT a loading flash
  // (GraphView folds the new literals onto the canvas in place). A commit that
  // failed surfaces the message; the banner self-dismisses.
  const onWidgetSaved = useCallback(() => {
    setWidgetError(null);
    void reload({ quiet: true });
  }, [reload]);
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
    } catch (err: unknown) {
      // Transport failure (server down): clear stale results, show the banner.
      setRun(null);
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

  // The node an engine run error points at (marked on the canvas).
  const errorNodeId = run?.errors.find((e) => e.nodeId)?.nodeId ?? null;

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

      {(runState.error || exportState.error || widgetError) && (
        <div className="ge-actionbar-error" data-testid="action-error" role="alert">
          {runState.error ?? exportState.error ?? widgetError}
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
