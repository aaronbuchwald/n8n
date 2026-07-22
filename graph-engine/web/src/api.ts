import type { GraphDoc, NodeSpecs } from './types';

// The engine over HTTP (ADR 0002). In dev/preview these are same-origin `/api/*`
// paths that Vite proxies to the FastAPI server (see vite.config.ts).
export interface SpecsResponse {
  version: string;
  specs: NodeSpecs;
}

export interface LiveGraph {
  version: string;
  specs: NodeSpecs;
  graph: GraphDoc;
}

async function getJson<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { headers: { accept: 'application/json' } });
  } catch {
    // Network failure (server down, connection refused) — fetch rejects.
    throw new Error(`Could not reach the server at ${path}. Is it running?`);
  }
  if (!res.ok) {
    throw new Error(`${path} responded ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

/**
 * Load the live palette + sample graph from the server. Fetches `/api/specs`
 * and `/api/graph` in parallel; either failing rejects so the UI can show an
 * error state instead of a blank canvas.
 */
export async function fetchLiveGraph(): Promise<LiveGraph> {
  const [specsRes, graph] = await Promise.all([
    getJson<SpecsResponse>('/api/specs'),
    getJson<GraphDoc>('/api/graph'),
  ]);
  return { version: specsRes.version, specs: specsRes.specs, graph };
}
