// Derive everything the node inspector shows for one node: where each input
// comes from (edge, literal, widget, default, required) and — once a run has
// happened — the concrete value that flowed through every input and output.
//
// No extra server round-trip is needed: the run response already carries every
// node's outputs, so a wired input's value is simply its upstream source
// node's output for that socket.

import type { SocketValues } from './api';
import type { GraphDoc, NodeSpecs, SpecInput, Widget } from './types';

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
  /**
   * The input's full declaration (static spec entry or derived socket), carried
   * so the inspector can mount its editor regardless of whether a literal is
   * set yet. Null for a spec-less node's edge-only inputs. ADR 0013 D4.
   */
  spec: SpecInput | null;
  /** The bound literal for this input, if the graph carries one (D4 editing). */
  literal: ResolvedValue | null;
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
  // The run predates the current graph (ADR 0008 G1). When stale, don't
  // synthesize a fresh literal as this input's "run value" — that is exactly
  // the mixed-epoch lie the reported bug showed (a just-edited literal rendered
  // as if the last run had computed it). Genuine run outputs still flow through;
  // the caller dims them.
  runIsStale = false,
  // A dynamic node's committed derived input sockets (ADR 0007), merged into the
  // input list exactly as `buildFlow` merges them for the canvas — static spec
  // inputs first, then derived entries in deriver order. Without this the
  // inspector (the only editing surface now, ADR 0013) would omit derived
  // symbols like `C_min`/`F_max`.
  derivedInputs?: SpecInput[],
): InspectedNode | null {
  const gn = graph.nodes.find((n) => n.id === nodeId);
  if (!gn) return null;

  const spec = specs[gn.type] ?? null;
  const bound = gn.inputs ?? {};
  const inEdges = graph.edges.filter((e) => e.target === nodeId);
  const outEdges = graph.edges.filter((e) => e.source === nodeId);
  const nodeRun = runOutputs?.[nodeId] ?? null;

  // Without a spec we still know input names from edges + bound literals. With a
  // spec, fold in the dynamic node's derived sockets after the static inputs.
  const declaredInputs = spec ? [...spec.inputs, ...(derivedInputs ?? [])] : [];
  const inputDecls = spec
    ? declaredInputs.map((i) => ({ name: i.name, type: i.type, meta: i }))
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
      // A literal is the value that flowed into this input during the run — but
      // only if the run still describes the current graph. When stale, the
      // literal shown here is fresher than the run, so it is NOT a run value.
      if (runOutputs && !runIsStale) run = { value: bound[name] };
    } else if (meta?.widget) {
      source = { kind: 'widget', widget: meta.widget, default: meta.default };
    } else if (meta && !meta.required) {
      source = { kind: 'default', value: meta.default };
    } else if (meta) {
      source = { kind: 'required' };
    } else {
      source = { kind: 'unset' };
    }
    const literal = has(bound, name) ? { value: bound[name] } : null;
    return { name, type, source, run, spec: meta, literal };
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
