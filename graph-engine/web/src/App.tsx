import { useEffect, useState } from 'react';

import { fetchLiveGraph, type LiveGraph } from './api';
import { GraphView } from './GraphView';

type LoadState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: LiveGraph };

export default function App() {
  const [state, setState] = useState<LoadState>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    setState({ status: 'loading' });
    fetchLiveGraph()
      .then((data) => {
        if (!cancelled) setState({ status: 'ready', data });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setState({ status: 'error', message: err instanceof Error ? err.message : String(err) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const graph = state.status === 'ready' ? state.data.graph : null;
  // Contract version comes from /api/specs (the palette contract), per ADR 0002.
  const version = state.status === 'ready' ? state.data.version : null;

  return (
    <div className="ge-app">
      <header className="ge-topbar">
        <h1 className="ge-topbar__title">graph-engine</h1>
        <span className="ge-topbar__sub">
          live graph · read-only
          {version ? ` · contract v${version}` : ''}
        </span>
        <span className="ge-topbar__out" data-testid="graph-output-label">
          output → {graph?.output ? `${graph.output.node}.${graph.output.socket}` : 'none'}
        </span>
      </header>

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
          <span className="ge-status__hint">
            Check that the API server is running, then reload.
          </span>
        </div>
      )}

      {state.status === 'ready' && <GraphView graph={state.data.graph} specs={state.data.specs} />}
    </div>
  );
}
