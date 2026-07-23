// Per-node derived sockets for the COMMITTED graph (ADR 0007 D4/D8). The
// derived socket list is computed state — never stored — so the canvas asks
// the server for it per dynamic-node instance, keyed (and cached) by
// `(specId, committed literal)`. The shell merges the result into each node's
// rendered input list; the sockets therefore update exactly when a commit
// changes the literal (never per keystroke — the editor's draft preview is a
// separate, uncommitted derive call).

import { useEffect, useMemo, useState } from 'react';
import type { GraphDoc, NodeSpecs, SpecInput } from '../../types';
import { cachedDerive, deriveInputs } from './derive';

interface DeriveRequest {
  nodeId: string;
  specId: string;
  value: string;
}

/** The committed deriving-literal of every dynamic node in `graph`. */
function collectRequests(graph: GraphDoc | null, specs: NodeSpecs | null): DeriveRequest[] {
  if (!graph || !specs) return [];
  const out: DeriveRequest[] = [];
  for (const node of graph.nodes) {
    const spec = specs[node.type];
    const param = spec?.dynamicInputs?.param;
    if (!param) continue;
    const literal = Object.prototype.hasOwnProperty.call(node.inputs, param)
      ? node.inputs[param]
      : spec.inputs.find((i) => i.name === param)?.default;
    // The deriving param is a literal by construction (ADR 0007 D2); anything
    // non-string would 422 at derive, so skip it and render the static spec.
    if (typeof literal !== 'string') continue;
    out.push({ nodeId: node.id, specId: node.type, value: literal });
  }
  return out;
}

/**
 * Map of graph-node id → derived input entries for its committed equation.
 * Nodes whose derivation failed (or hasn't resolved yet) are absent — the
 * canvas then renders the static spec, keeping existing wires on screen
 * (ADR 0007 honesty analysis: a derive failure never drops sockets).
 */
export function useDerivedInputs(
  graph: GraphDoc | null,
  specs: NodeSpecs | null,
): ReadonlyMap<string, SpecInput[]> {
  // Bumped when an uncached derivation settles, to re-read the cache below.
  const [settledCount, setSettledCount] = useState(0);

  const requests = useMemo(() => collectRequests(graph, specs), [graph, specs]);

  useEffect(() => {
    let cancelled = false;
    for (const req of requests) {
      if (cachedDerive(req.specId, req.value)) continue;
      void deriveInputs(req.specId, req.value).then(() => {
        if (!cancelled) setSettledCount((n) => n + 1);
      });
    }
    return () => {
      cancelled = true;
    };
  }, [requests]);

  return useMemo(() => {
    const map = new Map<string, SpecInput[]>();
    for (const req of requests) {
      const outcome = cachedDerive(req.specId, req.value);
      if (outcome?.ok) map.set(req.nodeId, outcome.inputs);
    }
    return map;
    // settledCount is the cache-refresh signal, not data — see the effect above.
  }, [requests, settledCount]);
}
