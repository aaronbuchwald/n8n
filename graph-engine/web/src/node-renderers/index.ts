// Renderer registration point + public barrel (ADR 0010 D4).
//
// Importing this module registers the built-in renderer kinds as a side
// effect. The mounting slot (RendererSlot) imports it, and RunResultsPanel
// imports the barrel, so kinds are present before any renderer resolves — no
// app-entry wiring required.
//
// Kind streams extend the vocabulary here, ONE line each (heavy kinds are lazy
// code-split chunks, npm-bundled, zero CDN):
//
//   import { lazyNodeRenderer } from './registry';
//   registerNodeRenderer('html-card', lazyNodeRenderer(() => import('./html-card')));
//
// TODO(ADR 0010 stream 10-K): register the `html-card` kind here (sandbox=""
// srcDoc iframe, declared `height` config) — the first product kind. The
// `dev-json` registration below is a seam-proof only and can be removed once a
// product kind exists.

import { DevJsonRenderer } from './DevJsonRenderer';
import { registerNodeRenderer } from './registry';

// Seam-proof kind: no served spec declares it (packs gain `renderer=` in
// 10-E/10-K), so it never shows in the demo; e2e injects it to prove the slot.
registerNodeRenderer('dev-json', DevJsonRenderer);

// Public API for the shell and downstream kind streams.
export {
  hasRenderer,
  lazyNodeRenderer,
  registerNodeRenderer,
  rendererFor,
  type NodeRenderer,
  type NodeRendererProps,
  type RegisteredRenderer,
} from './registry';
