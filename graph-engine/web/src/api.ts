import type { GraphDoc, GraphOutput, NodeSpecs } from './types';

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

// A structured engine error, per ADR 0002: {code, message, nodeId?}. `nodeId`
// is present when the exception exposes one (e.g. NodeExecutionError).
export interface EngineErrorItem {
  code: string;
  message: string;
  nodeId?: string;
}

// The per-node socket values a run produces. Values are JSON, with a
// {"$repr","$type"} fallback for non-JSON returns (server/serialize.py).
export type SocketValues = Record<string, unknown>;

export interface RunResult {
  outputs: Record<string, SocketValues>;
  order: string[];
  output: GraphOutput | null;
  errors: EngineErrorItem[];
}

export interface ExportResult {
  python: string;
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

/** POST a graph to `path`. Network failure rejects with a readable message. */
async function postGraph(path: string, graph: GraphDoc): Promise<Response> {
  try {
    return await fetch(path, {
      method: 'POST',
      headers: { accept: 'application/json', 'content-type': 'application/json' },
      body: JSON.stringify({ graph }),
    });
  } catch {
    throw new Error(`Could not reach the server at ${path}. Is it running?`);
  }
}

// FastAPI's HTTPException serialises as {detail: ...}; the engine endpoints put
// an EngineErrorItem[] in `detail` for schema/bind failures (ADR 0002).
function errorsFromDetail(body: unknown, fallback: string): EngineErrorItem[] {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail;
    if (Array.isArray(detail) && detail.length > 0) return detail as EngineErrorItem[];
    if (typeof detail === 'string') return [{ code: 'Error', message: detail }];
  }
  return [{ code: 'Error', message: fallback }];
}

/**
 * Execute the current graph (`POST /api/run`). Two failure shapes are folded
 * into the returned `errors` so the caller has one thing to render:
 *  - a runtime NodeExecutionError comes back 200 with a populated `errors`,
 *  - a schema/bind failure comes back 422 with `{detail: EngineErrorItem[]}`.
 * A network failure still rejects (surfaced as a global banner, not a run error).
 */
export async function runGraph(graph: GraphDoc): Promise<RunResult> {
  const res = await postGraph('/api/run', graph);
  const body: unknown = await res.json().catch(() => ({}));
  if (!res.ok) {
    return {
      outputs: {},
      order: [],
      output: graph.output,
      errors: errorsFromDetail(body, `${res.status} ${res.statusText}`),
    };
  }
  return body as RunResult;
}

/** Export the current graph to flat Python (`POST /api/export`). */
export async function exportGraph(graph: GraphDoc): Promise<ExportResult> {
  const res = await postGraph('/api/export', graph);
  const body: unknown = await res.json().catch(() => ({}));
  if (!res.ok) {
    const [first] = errorsFromDetail(body, `${res.status} ${res.statusText}`);
    throw new Error(first.message);
  }
  return body as ExportResult;
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
