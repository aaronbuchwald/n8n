// Python-only previews for the table-recipe editor (ADR 0005 C-D4).
//
// The grid NEVER computes. Every preview shown in the editor comes from one
// place: `POST /api/run` — the server executing the graph (with the in-editor
// draft recipe patched onto this widget's node) through the Python interpreter
// in nodepacks/table. This module fetches the live graph, locates the anchor
// node, substitutes the draft recipe literal, runs, and extracts the anchor's
// input/output tables from the per-node socket values. `/api/run` does not
// persist anything, so previews are side-effect-free; commits still ride the
// standard widget path (PUT /api/graph, via onCommit).

import { runGraph, type EngineErrorItem, type RunResult } from '../../api';
import type { GraphDoc, GraphNode } from '../../types';
import { isTableData, type TableData } from './model';

export interface PreviewTables {
  /** The table fed INTO the anchor node (drives the column pickers). */
  input: TableData | null;
  /** The table the anchor node produced — the grid's main content. */
  output: TableData | null;
  /** The graph node the recipe literal was matched to, if any. */
  nodeId: string | null;
  /** Run errors, anchor-node ones first (Python is the validator, A-D5). */
  errors: EngineErrorItem[];
}

export type PreviewResult =
  | { kind: 'ready'; tables: PreviewTables }
  // The server is unreachable, or no graph node carries this widget's literal
  // (e.g. the editor mounted outside the app shell). Not an error state.
  | { kind: 'unavailable'; reason: string };

function deepEqual(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (typeof a !== 'object' || typeof b !== 'object' || a === null || b === null) return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  const ka = Object.keys(a as Record<string, unknown>);
  const kb = Object.keys(b as Record<string, unknown>);
  if (ka.length !== kb.length) return false;
  return ka.every((k) =>
    deepEqual((a as Record<string, unknown>)[k], (b as Record<string, unknown>)[k]),
  );
}

/**
 * Find the graph node this editor instance is editing. The widget props carry
 * no node id (frozen contract), so we match by content: prefer the node whose
 * `inputs[param]` literal deep-equals the committed value; fall back to the
 * unique node carrying the param at all.
 */
export function findAnchorNode(
  graph: GraphDoc,
  param: string,
  committedValue: unknown,
): GraphNode | null {
  const carrying = graph.nodes.filter((n) => param in n.inputs);
  const exact = carrying.filter((n) => deepEqual(n.inputs[param], committedValue));
  if (exact.length === 1) return exact[0];
  if (carrying.length === 1) return carrying[0];
  return null;
}

function firstTable(sockets: Record<string, unknown> | undefined): TableData | null {
  if (!sockets) return null;
  for (const value of Object.values(sockets)) {
    if (isTableData(value)) return value;
  }
  return null;
}

/** The table flowing into `node`'s table-typed input, read from run outputs. */
function inputTableFor(graph: GraphDoc, node: GraphNode, run: RunResult): TableData | null {
  for (const edge of graph.edges) {
    if (edge.target !== node.id) continue;
    const sourceValue = run.outputs[edge.source]?.[edge.sourceOutput];
    if (isTableData(sourceValue)) return sourceValue;
  }
  // The table may also be bound as a literal directly on the node.
  for (const value of Object.values(node.inputs)) {
    if (isTableData(value)) return value;
  }
  return null;
}

async function fetchGraph(): Promise<GraphDoc> {
  const res = await fetch('/api/graph', { headers: { accept: 'application/json' } });
  if (!res.ok) throw new Error(`/api/graph responded ${res.status} ${res.statusText}`);
  return (await res.json()) as GraphDoc;
}

/**
 * Execute the live graph with `draftRecipe` substituted on the anchor node and
 * return the anchor's input/output tables. All computation happens server-side.
 */
export async function fetchPreview(
  param: string,
  committedValue: unknown,
  draftRecipe: unknown,
): Promise<PreviewResult> {
  let graph: GraphDoc;
  try {
    graph = await fetchGraph();
  } catch (error) {
    return {
      kind: 'unavailable',
      reason: error instanceof Error ? error.message : String(error),
    };
  }

  const anchor = findAnchorNode(graph, param, committedValue);
  if (!anchor) {
    return { kind: 'unavailable', reason: `no graph node carries a '${param}' input` };
  }

  const patched: GraphDoc = {
    ...graph,
    nodes: graph.nodes.map((n) =>
      n.id === anchor.id ? { ...n, inputs: { ...n.inputs, [param]: draftRecipe } } : n,
    ),
  };

  let run: RunResult;
  try {
    run = await runGraph(patched);
  } catch (error) {
    return {
      kind: 'unavailable',
      reason: error instanceof Error ? error.message : String(error),
    };
  }

  const mine = run.errors.filter((e) => e.nodeId === anchor.id);
  const rest = run.errors.filter((e) => e.nodeId !== anchor.id);
  return {
    kind: 'ready',
    tables: {
      input: inputTableFor(patched, anchor, run),
      output: firstTable(run.outputs[anchor.id]),
      nodeId: anchor.id,
      errors: [...mine, ...rest],
    },
  };
}
