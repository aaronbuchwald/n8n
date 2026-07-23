import type { GraphDoc, GraphOutput, NodeSpec, NodeSpecs } from './types';

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

// --- entry points (ADR 0009) ------------------------------------------------
// The server lists every viewable `@main` entry point; the selected id scopes
// the graph/run/source calls below. `null` = the legacy unscoped routes (a
// server without an entry catalog, or one not yet resolved), which serve the
// default entry.

export type GraphId = string | null;

export interface GraphEntry {
  id: string;
  title: string;
  module: string;
  qualname: string | null;
  path: string | null; // repo-relative authoring-module path
  dir: string | null; // repo-relative run_base_dir
  status: 'ok' | 'error';
  error?: string; // present when status === 'error'
}

export interface GraphsResponse {
  version: string;
  default: string | null; // what --example chose; the UI's initial selection
  entries: GraphEntry[];
}

/** List every viewable entry point (`GET /api/graphs`). */
export async function fetchGraphs(): Promise<GraphsResponse> {
  return getJson<GraphsResponse>('/api/graphs');
}

function graphPath(graphId: GraphId): string {
  return graphId === null ? '/api/graph' : `/api/graphs/${encodeURIComponent(graphId)}/graph`;
}

function runPath(graphId: GraphId): string {
  return graphId === null ? '/api/run' : `/api/graphs/${encodeURIComponent(graphId)}/run`;
}

function sourcePath(specId: string, graphId: GraphId): string {
  const suffix = `/source/${encodeURIComponent(specId)}`;
  return graphId === null
    ? `/api${suffix}`
    : `/api/graphs/${encodeURIComponent(graphId)}${suffix}`;
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
export async function runGraph(graph: GraphDoc, graphId: GraphId = null): Promise<RunResult> {
  const res = await postGraph(runPath(graphId), graph);
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
 * Load the live palette + graph from the server. Fetches `/api/specs` and the
 * (optionally entry-scoped) graph route in parallel; either failing rejects so
 * the UI can show an error state instead of a blank canvas.
 */
export async function fetchLiveGraph(graphId: GraphId = null): Promise<LiveGraph> {
  const [specsRes, graph] = await Promise.all([
    getJson<SpecsResponse>('/api/specs'),
    getJson<GraphDoc>(graphPath(graphId)),
  ]);
  return { version: specsRes.version, specs: specsRes.specs, graph };
}

// --- source-tree editing (stream E / ADR 0004 D2) --------------------------
// The Python module is the source of truth; these calls read and write the
// REAL .py files on the currently checked-out git branch.

export interface WorkspaceModule {
  module: string;
  path: string; // repo-relative path of the edited .py file
}

export interface WorkspaceInfo {
  branch: string | null; // null when detached or not a git checkout
  detached: boolean;
  commit: string | null;
  modules: WorkspaceModule[];
}

export interface SourceInfo {
  specId: string;
  module: string;
  qualname: string;
  path: string;
  startLine: number;
  endLine: number;
  source: string;
}

export interface SaveSourceResult extends SourceInfo {
  spec: NodeSpec; // re-introspected after the module reload
  graphErrors: EngineErrorItem[]; // the served graph may stop binding after an edit
  // The re-projected graph the server now serves after the edit (ADR 0008 G3;
  // "writes return truth"). Phase 1 (8-S1) ingests it from this response, so a
  // source save needs no follow-up GET (Gap G4).
  graph?: GraphDoc;
}

export interface SaveGraphResult {
  graph: GraphDoc; // re-parsed from the rewritten module (the round-trip proof)
}

/** PUT a JSON payload; a non-2xx `{message}` (or `{detail}`) rejects with it. */
async function putJson<T>(path: string, payload: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: 'PUT',
      headers: { accept: 'application/json', 'content-type': 'application/json' },
      body: JSON.stringify(payload),
    });
  } catch {
    throw new Error(`Could not reach the server at ${path}. Is it running?`);
  }
  const body: unknown = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (body && typeof body === 'object' && 'message' in body) {
      const message = (body as { message: unknown }).message;
      if (typeof message === 'string') throw new Error(message);
    }
    const [first] = errorsFromDetail(body, `${path} responded ${res.status} ${res.statusText}`);
    throw new Error(first.message);
  }
  return body as T;
}

/** Current git branch + which module files edits land on (`GET /api/workspace`). */
export async function fetchWorkspace(): Promise<WorkspaceInfo> {
  return getJson<WorkspaceInfo>('/api/workspace');
}

/** The exact source of one @node function (`GET /api/source/{spec_id}`). */
export async function fetchSource(specId: string, graphId: GraphId = null): Promise<SourceInfo> {
  return getJson<SourceInfo>(sourcePath(specId, graphId));
}

/** Write an edited @node def back into its real .py file (`PUT /api/source/{spec_id}`). */
export async function saveSource(
  specId: string,
  source: string,
  graphId: GraphId = null,
): Promise<SaveSourceResult> {
  return putJson<SaveSourceResult>(sourcePath(specId, graphId), { source });
}

/** Rewrite the module's @main wiring from the graph (`PUT /api/graph`). */
export async function saveGraph(graph: GraphDoc, graphId: GraphId = null): Promise<SaveGraphResult> {
  return putJson<SaveGraphResult>(graphPath(graphId), { graph });
}
