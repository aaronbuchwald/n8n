// Derive everything the node inspector shows for one node: where each input
// comes from (edge, literal, widget, default, required) and — once a run has
// happened — the concrete value that flowed through every input and output.
//
// No extra server round-trip is needed: the run response already carries every
// node's outputs, so a wired input's value is simply its upstream source
// node's output for that socket.

import type { SocketValues } from './api';
import type { GraphDoc, NodeSpecs, Widget } from './types';

export type InputSource =
  | { kind: 'wired'; from: { node: string; socket: string } }
  | { kind: 'literal'; value: unknown }
  | { kind: 'widget'; widget: Widget; default: unknown }
  | { kind: 'default'; value: unknown }
  | { kind: 'required' }
  | { kind: 'unset' };

/** Wrapper so "no value" is distinguishable from a value of `undefined`/`null`. */
export interface ResolvedValue {
  value: unknown;
}

export interface InspectedInput {
  name: string;
  type: string;
  source: InputSource;
  /** The value this input resolved to in the latest run (null if unknown). */
  run: ResolvedValue | null;
}

export interface InspectedOutput {
  name: string;
  type: string;
  /** The value this output produced in the latest run (null if unknown). */
  run: ResolvedValue | null;
}

export interface InspectedNode {
  id: string;
  title: string;
  typeName: string;
  doc: string;
  isOutput: boolean;
  missingSpec: boolean;
  /** True when a run has happened (even if it failed before this node). */
  hasRun: boolean;
  /** True when the latest run actually reached this node and produced outputs. */
  executed: boolean;
  inputs: InspectedInput[];
  outputs: InspectedOutput[];
}

const has = (obj: Record<string, unknown>, key: string) =>
  Object.prototype.hasOwnProperty.call(obj, key);

export function inspectNode(
  graph: GraphDoc,
  specs: NodeSpecs,
  nodeId: string,
  runOutputs: Record<string, SocketValues> | null,
): InspectedNode | null {
  const gn = graph.nodes.find((n) => n.id === nodeId);
  if (!gn) return null;

  const spec = specs[gn.type] ?? null;
  const bound = gn.inputs ?? {};
  const inEdges = graph.edges.filter((e) => e.target === nodeId);
  const outEdges = graph.edges.filter((e) => e.source === nodeId);
  const nodeRun = runOutputs?.[nodeId] ?? null;

  // Without a spec we still know input names from edges + bound literals.
  const inputDecls = spec
    ? spec.inputs.map((i) => ({ name: i.name, type: i.type, meta: i }))
    : [...new Set([...inEdges.map((e) => e.targetInput), ...Object.keys(bound)])].map((name) => ({
        name,
        type: '?',
        meta: null,
      }));

  const inputs: InspectedInput[] = inputDecls.map(({ name, type, meta }) => {
    const edge = inEdges.find((e) => e.targetInput === name);
    let source: InputSource;
    let run: ResolvedValue | null = null;

    if (edge) {
      source = { kind: 'wired', from: { node: edge.source, socket: edge.sourceOutput } };
      const upstream = runOutputs?.[edge.source];
      if (upstream && has(upstream, edge.sourceOutput)) {
        run = { value: upstream[edge.sourceOutput] };
      }
    } else if (has(bound, name)) {
      source = { kind: 'literal', value: bound[name] };
      if (runOutputs) run = { value: bound[name] };
    } else if (meta?.widget) {
      source = { kind: 'widget', widget: meta.widget, default: meta.default };
    } else if (meta && !meta.required) {
      source = { kind: 'default', value: meta.default };
    } else if (meta) {
      source = { kind: 'required' };
    } else {
      source = { kind: 'unset' };
    }
    return { name, type, source, run };
  });

  // Without a spec, output names come from outgoing edges + run outputs.
  const outputDecls = spec
    ? spec.outputs.map((o) => ({ name: o.name, type: o.type }))
    : [
        ...new Set([...outEdges.map((e) => e.sourceOutput), ...Object.keys(nodeRun ?? {})]),
      ].map((name) => ({ name, type: '?' }));

  const outputs: InspectedOutput[] = outputDecls.map(({ name, type }) => ({
    name,
    type,
    run: nodeRun && has(nodeRun, name) ? { value: nodeRun[name] } : null,
  }));

  return {
    id: gn.id,
    title: spec?.title ?? gn.id,
    typeName: gn.type,
    doc: spec?.doc ?? '',
    isOutput: graph.output?.node === gn.id,
    missingSpec: !spec,
    hasRun: runOutputs !== null,
    executed: nodeRun !== null,
    inputs,
    outputs,
  };
}
