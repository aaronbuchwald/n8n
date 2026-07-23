// The React binding to the UI-local layout store (store/layout.ts), the exact
// `useSyncExternalStore` shape as `useSyncSelector`. The selector must return a
// stored reference or a primitive (the store hands out frozen snapshots), so
// component reads stay tear-free without re-allocating on every render.

import { useSyncExternalStore } from 'react';
import { getLayout, subscribeLayout, type LayoutState } from './layout';

export function useLayoutSelector<T>(selector: (s: LayoutState) => T): T {
  return useSyncExternalStore(subscribeLayout, () => selector(getLayout()));
}
