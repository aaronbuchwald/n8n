import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { exportGraph, fetchGraphs, fetchLiveGraph, runGraph } from './api';
import { BranchBadge } from './components/BranchBadge';
import { GraphPicker } from './components/GraphPicker';
import { ExportPanel } from './components/ExportPanel';
import { NodeInspector } from './components/NodeInspector';
import { Palette } from './components/Palette';
import { NewNodePanel } from './components/NewNodePanel';
import { RunResultsPanel } from './components/RunResultsPanel';
import { Workbench, type WorkbenchHandle } from './components/workbench/Workbench';
import type { DockTab } from './components/workbench/RightDock';
import { GraphView, type FocusRequest } from './GraphView';
import { inspectNode } from './inspect';
import {
  clearRun,
  commitLiteral,
  hydrate,
  selectRunIsStale,
  setPruneNotice,
  setRun,
  setWriteError,
} from './store/sync';
import { useSyncSelector } from './store/useSyncSelector';
import { useDerivedSync, WidgetEditingProvider } from './widgets';

// The shell owns only the boot lifecycle + transient action state. Every shared
// value (graph, specs, version, run, staleness) lives in the store (8-S1) and is
// read here via selectors — App no longer holds a copy of any of it, so there is
// no cache to invalidate by hand. `rev`/`runRev`/`reloadSeq` from 8-P0 became
// the store's `rev` + `run.forRev` + seq-gated `ingestGraph`.
//
// ADR 0009 layers the entry-point picker onto the same seam: `selection` below
// is the plain URL-driven "input signal" the ADR describes. It never touches
// the canvas directly — changing it re-fetches through the scoped routes and
// calls `hydrate(live, id)`, which is also where the store resets every
// per-entry cache (sources, pending writes, run, write errors). The picker
// itself (GraphPicker) is store-less and self-contained, matching BranchBadge.
type BootState = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready' };

// One action's lifecycle (Run or Export). `error` here is a transport-level
// failure (server unreachable) — engine-level run errors travel inside RunResult.
interface ActionState {
  pending: boolean;
  error: string | null;
}

const IDLE: ActionState = { pending: false, error: null };

/** The `?graph=` entry-point id in the current URL, if any (ADR 0009 D6). */
function graphIdFromUrl(): string | null {
  return new URLSearchParams(window.location.search).get('graph');
}

// The selected entry point. `null` (outer) = the catalog hasn't resolved yet;
// `{ id: null }` = no catalog (legacy server, or a server too old to have one)
// → the unscoped routes, which is also the single-program experience.
type Selection = { id: string | null } | null;

export default function App() {
  const [boot, setBoot] = useState<BootState>({ status: 'loading' });
  const [selection, setSelection] = useState<Selection>(null);
  const [runState, setRunState] = useState<ActionState>(IDLE);
  const [python, setPython] = useState<string | null>(null);
  const [exportState, setExportState] = useState<ActionState>(IDLE);
  // The inspected node. Owned here (not in GraphView) so run-results rows can
  // select it and the Escape handler below can close it.
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  // Whether the inspector is expanded into the selected node's source editor.
  const [editingSource, setEditingSource] = useState(false);
  // Whether the "New node" authoring panel is open (ADR 0011 D7, stream 11-W6).
  // Stand-in trigger until the palette (11-W5) grows its own "New node" entry.
  const [creatingSource, setCreatingSource] = useState(false);
  const [focusRequest, setFocusRequest] = useState<FocusRequest | null>(null);
  // Imperative handle to the workbench shell — the "Reset layout" affordance
  // snaps every region back to defaults without a reload (ADR 0014 D5).
  const workbenchRef = useRef<WorkbenchHandle>(null);

  // --- store reads (selectors return stored refs or primitives) ---------------
  const graph = useSyncSelector((s) => s.effective.graph);
  const specs = useSyncSelector((s) => s.specs);
  const version = useSyncSelector((s) => s.version);
  const run = useSyncSelector((s) => s.run);
  const runIsStale = useSyncSelector(selectRunIsStale);
  // The committed derived sockets per dynamic node (ADR 0007), needed to inspect
  // a node's derived inputs now that the inspector is composed here (not inside
  // the canvas) and mounted into the right dock (ADR 0014 D1).
  const derivedByNode = useSyncSelector((s) => s.derivedByNode);
  // A failed widget commit lands here (the queue, being hookless, writes it to
  // the store). Auto-clears so it never lingers over the canvas.
  const writeError = useSyncSelector((s) => s.writeError);
  // The one volatile surface a graph switch must confirm-discard (D6): an
  // open source-editor buffer with unsaved changes. SourceEditor is the writer.
  const sourceDirty = useSyncSelector((s) => s.sourceDirty);
  // What an equation commit disconnected (ADR 0007 D8 prune-with-toast):
  // "F_max removed from equation — unwired from max_force". Transient.
  const pruneNotice = useSyncSelector((s) => s.pruneNotice);

  // Keep the store's derived-socket cache warm for every committed dynamic-node
  // literal (ADR 0007); the canvas renders derived sockets from the store.
  useDerivedSync();

  const graphId = selection?.id ?? null;

  // Resolve the entry-point selection once at boot: the URL's `?graph=` wins
  // when it names a KNOWN entry; otherwise `null` — the legacy unscoped
  // routes, not the catalog's default id. Those unscoped routes already alias
  // the default entry server-side (ADR 0009 D4), and D4 keeps them specifically
  // "so the current web bundle and tests keep working" — so a plain `/` with no
  // `?graph=` must stay on them rather than silently becoming
  // `/api/graphs/<default>/...`. Only an explicit pick (or a deep link) moves
  // the app onto a scoped id; GraphPicker labels the button from its own
  // `data.default` even while this stays `null`, so the UI still shows the
  // right name. A failed catalog fetch (no catalog, or an older server) is the
  // same `null` case — the single-program experience, pixel-identical to
  // before this ADR.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      let id: string | null = null;
      try {
        const graphs = await fetchGraphs();
        const urlId = graphIdFromUrl();
        id = urlId !== null && graphs.entries.some((e) => e.id === urlId) ? urlId : null;
      } catch {
        id = null;
      }
      if (!cancelled) setSelection({ id });
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // (Re)load whenever the selection resolves or the selected id changes — the
  // id is the key everything is fetched under (the ADR 0008 seam). `hydrate`
  // resets every per-entry store cache when the id actually changed.
  useEffect(() => {
    if (selection === null) return;
    let cancelled = false;
    setBoot({ status: 'loading' });
    fetchLiveGraph(selection.id)
      .then((live) => {
        if (cancelled) return;
        hydrate(live, selection.id);
        setBoot({ status: 'ready' });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setBoot({ status: 'error', message: err instanceof Error ? err.message : String(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [selection]);

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

  useEffect(() => {
    if (!pruneNotice) return;
    const timer = window.setTimeout(() => setPruneNotice(null), 8000);
    return () => window.clearTimeout(timer);
  }, [pruneNotice]);

  // Swap to another entry point: move the `?graph=` key (the store reacts via
  // the reload effect above) and reset the UI-local surfaces the store doesn't
  // own — the export dock and the transient run/export action banners. The
  // store's own per-entry state (run results, sources, pending writes) is
  // cleared by `hydrate` once the new entry's graph lands, not here.
  const switchGraph = useCallback((id: string | null, opts?: { pushUrl?: boolean }) => {
    setPython(null);
    setExportState(IDLE);
    setRunState(IDLE);
    setSelectedNodeId(null);
    setEditingSource(false);
    if (opts?.pushUrl !== false) {
      const url = new URL(window.location.href);
      if (id === null) url.searchParams.delete('graph');
      else url.searchParams.set('graph', id);
      window.history.pushState({}, '', url);
    }
    setSelection({ id });
  }, []);

  const onPickGraph = useCallback(
    (id: string) => {
      if (id === graphId) return;
      if (sourceDirty && !window.confirm('Discard the unsaved source edit and switch graphs?')) {
        return;
      }
      switchGraph(id);
    },
    [graphId, sourceDirty, switchGraph],
  );

  // Back/forward re-applies the URL's selection (deep links stay live) —
  // including back to a param-less URL, which means `null` (the unscoped
  // routes), consistent with the boot resolution above.
  useEffect(() => {
    const onPopState = () => switchGraph(graphIdFromUrl(), { pushUrl: false });
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, [switchGraph]);

  // Escape dismisses the topmost open surface, one per press: the source
  // editor (back to the inspector), then the inspector, then the export dock,
  // then run results. Escape typed INSIDE the source editor is deliberately
  // inert so a stray press can't discard an unsaved body edit. Widget editors
  // now live in the inspector (ADR 0013 D4); Escape closes the inspector and
  // the slot's unmount blurs the focused field so a blur-committing draft
  // settles first.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented) return;
      if (event.target instanceof Element && event.target.closest('.ge-source')) {
        return;
      }
      if (selectedNodeId && editingSource) {
        setEditingSource(false);
      } else if (selectedNodeId) {
        setSelectedNodeId(null);
      } else if (creatingSource) {
        setCreatingSource(false);
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
  }, [selectedNodeId, editingSource, creatingSource, python, run]);

  const onRun = useCallback(async () => {
    if (!graph) return;
    setRunState({ pending: true, error: null });
    try {
      const result = await runGraph(graph, graphId);
      setRun(result); // stamped with the current rev inside the store (epoch)
    } catch (err: unknown) {
      // Transport failure (server down): clear stale results, show the banner.
      clearRun();
      setRunState({ pending: false, error: err instanceof Error ? err.message : String(err) });
      return;
    }
    setRunState(IDLE);
  }, [graph, graphId]);

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

  // The inspected node, composed HERE now (ADR 0013 = the one editing surface,
  // ADR 0014 = it lives in the right dock, not floating over the canvas). Folds
  // in the store's committed derived inputs exactly as the canvas' buildFlow
  // does, so derived symbols (C_min/F_max) are inspectable.
  const runOutputs = run?.outputs ?? null;
  const inspected = useMemo(
    () =>
      graph && selectedNodeId
        ? inspectNode(
            graph,
            specs,
            selectedNodeId,
            runOutputs,
            runIsStale,
            derivedByNode.get(selectedNodeId),
          )
        : null,
    [graph, specs, selectedNodeId, runOutputs, runIsStale, derivedByNode],
  );
  // Several nodes may share one @node function; the source editor says so.
  const sharedNodeCount = useMemo(
    () => (graph && inspected ? graph.nodes.filter((n) => n.type === inspected.typeName).length : 0),
    [graph, inspected],
  );

  // The right-dock tab registry (ADR 0014 D3). W1 mounts only the Inspector tab;
  // W3 pushes Export and New-node entries onto this same array. Closing the tab
  // deselects the node (D3: "Closing the tab = deselect").
  const dockTabs = useMemo<DockTab[]>(() => {
    const tabs: DockTab[] = [];
    if (inspected) {
      tabs.push({
        id: 'inspector',
        kind: 'inspector',
        label: 'Inspector',
        onClose: () => selectNode(null),
        content: (
          <NodeInspector
            node={inspected}
            sharedNodeCount={sharedNodeCount}
            editingSource={editingSource}
            onEditSource={setEditingSource}
            onClose={() => selectNode(null)}
          />
        ),
      });
    }
    return tabs;
  }, [inspected, sharedNodeCount, editingSource, selectNode]);

  return (
    <div className="ge-app">
      <header className="ge-topbar">
        <h1 className="ge-topbar__title">graph-engine</h1>
        <span className="ge-topbar__sub">
          live graph{version ? ` · contract v${version}` : ''}
        </span>
        <GraphPicker selectedId={graphId} onSelect={onPickGraph} />
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
          {/* Stand-in entry point for authoring a new @node (ADR 0011 D7); the
              palette header (11-W5) grows its own trigger once it lands. */}
          <button
            type="button"
            className="ge-btn"
            data-testid="new-node-button"
            disabled={!ready}
            onClick={() => setCreatingSource(true)}
          >
            + New node
          </button>
          {/* Reset the workbench layout to defaults without a reload — also the
              escape hatch for a corrupt saved layout (ADR 0014 D5). */}
          <button
            type="button"
            className="ge-btn ge-btn--ghost"
            data-testid="reset-layout"
            disabled={!ready}
            title="Reset the panel layout to defaults"
            onClick={() => workbenchRef.current?.reset()}
          >
            Reset layout
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

      {pruneNotice && (
        <div className="ge-toast" data-testid="calc-toast" role="status">
          {pruneNotice}
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
          {/* The VS Code-style workbench (ADR 0014 W1): resizable/collapsible
              regions around the canvas. The commit seam (A-D5) wraps the whole
              shell so BOTH the canvas widgets and the now-docked inspector's
              widget slot resolve the store's stable `commitLiteral`.
              The Palette (11-W5), GraphView, RunResults, and the inspector are
              passed in as layout-ignorant slots (D6). Export and New-node stay
              today's right columns — W3 relocates them into the dock. */}
          <WidgetEditingProvider value={commitLiteral}>
            <Workbench
              ref={workbenchRef}
              palette={<Palette />}
              canvas={
                <GraphView
                  key={graphId ?? '(default)'}
                  selectedNodeId={selectedNodeId}
                  onSelectNode={selectNode}
                  focusRequest={focusRequest}
                />
              }
              bottom={
                run && graph ? (
                  <RunResultsPanel
                    run={run}
                    graph={graph}
                    specs={specs}
                    runIsStale={runIsStale}
                    onFocusNode={onFocusNode}
                    onClose={clearRun}
                  />
                ) : null
              }
              bottomBadge={run ? run.order.length : undefined}
              dockTabs={dockTabs}
            />
          </WidgetEditingProvider>
          {python !== null && <ExportPanel python={python} onClose={() => setPython(null)} />}
          {creatingSource && <NewNodePanel onClose={() => setCreatingSource(false)} />}
        </div>
      )}
    </div>
  );
}
