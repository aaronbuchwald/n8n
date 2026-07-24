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
import { DevJsonRenderer } from './DevJsonRenderer';
import { lazyNodeRenderer, registerNodeRenderer } from './registry';

// `html-card` (ADR 0010 D5/D6, stream 10-K): the node's HTML-string output in
// a sandbox="" srcDoc iframe at the declared `height` — the first product
// kind. Lazy code-split chunk: npm-bundled, zero CDN.
registerNodeRenderer('html-card', lazyNodeRenderer(() => import('./html-card')));

// `latex` (ADR 0013 D5): typeset a LaTeX-string socket with KaTeX in the host
// DOM — the handcalcs output for the `handcalc` node. Frozen kind name/socket
// `"latex"`; the Python stream declares `Renderer("latex", socket="latex")`.
// Lazy code-split chunk: npm-bundled, zero CDN.
registerNodeRenderer('latex', lazyNodeRenderer(() => import('./latex')));

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
