// Keeps the store's `derived` cache warm for every COMMITTED dynamic-node
// literal (ADR 0007 D4/D8, reconciled onto the 8-S1 store). Replaces the old
// `useDerivedInputs` fetch-and-cache-and-render hook: this hook only FETCHES —
// each result lands in the store via `ingestDerived`, the store precomputes
// `derivedByNode` from it, and the canvas renders derived sockets from that
// stored view. There is no module-local render state (rule 3).
//
// Most keys are already present when this runs: `commitEquation` ingests the
// editor's own derive outcome in the same action. What this covers is the
// rest — nodes committed before this session (boot/hydrate), hand-edited
// sources, and entry switches. Nodes whose derivation fails are simply never
// ingested: the canvas renders the static spec, keeping existing wires on
// screen (a derive failure never drops sockets).

import { useEffect } from 'react';
import { derivedKeyOf, dynamicLiteralOf, ingestDerived } from '../../store/sync';
import { useSyncSelector } from '../../store/useSyncSelector';
import { cachedDerive, deriveInputs } from './derive';

export function useDerivedSync(): void {
  const graph = useSyncSelector((s) => s.effective.graph);
  const specs = useSyncSelector((s) => s.specs);
  const derived = useSyncSelector((s) => s.derived);

  useEffect(() => {
    if (!graph) return;
    let cancelled = false;
    for (const node of graph.nodes) {
      const literal = dynamicLiteralOf(node, specs[node.type]);
      if (literal === null) continue;
      if (derivedKeyOf(node.type, literal) in derived) continue;
      const settled = cachedDerive(node.type, literal);
      if (settled) {
        // A settled failure stays out of the store (static spec renders) and is
        // not refetched — the transport cached the server's verdict.
        if (settled.ok) ingestDerived(node.type, literal, settled.inputs);
        continue;
      }
      void deriveInputs(node.type, literal).then((outcome) => {
        // `ingestDerived`'s key is (specId, literal), so a stale response can
        // never mislabel a newer literal; `cancelled` only avoids ingesting
        // after unmount.
        if (!cancelled && outcome.ok) ingestDerived(node.type, literal, outcome.inputs);
      });
    }
    return () => {
      cancelled = true;
    };
  }, [graph, specs, derived]);
}
