// The React binding to the UI-local catalog store (store/catalog.ts), the exact
// `useSyncExternalStore` shape as `useLayout`/`useSyncSelector`. The selector
// must return a stored reference or a primitive (the store hands out frozen
// snapshots), so component reads stay tear-free without re-allocating on every
// render.

import { useSyncExternalStore } from 'react';
import { getCatalog, subscribeCatalog, type CatalogState } from './catalog';

export function useCatalogSelector<T>(selector: (s: CatalogState) => T): T {
  return useSyncExternalStore(subscribeCatalog, () => selector(getCatalog()));
}
