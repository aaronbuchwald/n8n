// ADR 0008 Phase 1 — the ENTIRE React binding to the store. One line of the
// official React primitive (`useSyncExternalStore`): tear-free by contract, and
// the only seam between the store's unit-tested state machine and the tree.
//
// RULE (enforced by React's own dev warning, not by review): `selector` must
// return a STORED reference or a PRIMITIVE — never a freshly-allocated object
// or array. Derived views are precomputed in the store on write (`effective`,
// `selectRunIsStale`, …); selectors here only READ them. A selector that
// allocates on every call trips React's "getSnapshot should be cached" warning
// on first render, so a violation self-announces.

import { useSyncExternalStore } from 'react';
import { getState, subscribe, type SyncState } from './sync';

export function useSyncSelector<T>(selector: (s: SyncState) => T): T {
  return useSyncExternalStore(subscribe, () => selector(getState()));
}
