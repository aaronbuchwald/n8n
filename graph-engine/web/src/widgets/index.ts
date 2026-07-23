// Widget registration point + public barrel (ADR 0005 A-D4).
//
// Importing this module registers the built-in editors as a side effect. The
// mounting slot (WidgetSlot) imports it, so built-ins are present before any
// editor renders — no app-entry wiring required.
//
// Streams B / C-ui extend the vocabulary here, ONE line each (their editors are
// lazy code-split chunks, npm-bundled, zero CDN):
//
//   import { lazyEditor } from './registry';
//   registerWidget('math', lazyEditor(() => import('./math')));
//   registerWidget('table-recipe', lazyEditor(() => import('./table')));

import { CheckboxEditor, NumberEditor, TextEditor } from './builtins';
import { lazyEditor, registerWidget } from './registry';

// Core kinds (A-D6: flat names). These mirror engine/spec.py's type-derived
// widgets, so every str/int/float/bool input has a working editor out of the box.
registerWidget('text', TextEditor);
registerWidget('number', NumberEditor);
registerWidget('checkbox', CheckboxEditor);
registerWidget('table-recipe', lazyEditor(() => import('./table/TableRecipeEditor')));

// Stream B: math widget (ADR 0005 B) — SymPy expressions with KaTeX preview.
registerWidget('math', lazyEditor(() => import('./math/MathEditor').then(m => ({ default: m.MathEditor }))));

// Stream W: calc widget (ADR 0007 D8) — handcalc equations whose free symbols
// derive the node's input sockets (server-authoritative, via /derive). Store-
// reconciled: commits go through the store's `commitEquation`, derived sockets
// render from `state.derivedByNode` — no host context, no parallel committer.
registerWidget('calc', lazyEditor(() => import('./calc/CalcEditor').then(m => ({ default: m.CalcEditor }))));

// Public API for the shell and downstream streams.
export {
  editorFor,
  hasEditor,
  lazyEditor,
  registerWidget,
  type RegisteredEditor,
  type WidgetEditor,
  type WidgetEditorProps,
} from './registry';
export { useWidgetCommit, WidgetEditingProvider, type CommitInput } from './context';
// The committed-derivation fetcher (ADR 0007, store-reconciled): the shell
// mounts it once so every dynamic node's committed literal has its derived
// sockets in the store. Eager-imported here — it is a tiny hook module; the
// heavy calc editor stays a lazy chunk above.
export { useDerivedSync } from './calc/useDerivedSync';
