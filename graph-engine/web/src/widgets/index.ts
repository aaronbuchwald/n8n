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
import { registerWidget, lazyEditor } from './registry';

// Core kinds (A-D6: flat names). These mirror engine/spec.py's type-derived
// widgets, so every str/int/float/bool input has a working editor out of the box.
registerWidget('text', TextEditor);
registerWidget('number', NumberEditor);
registerWidget('checkbox', CheckboxEditor);

// Stream B: math widget (ADR 0005 B) — SymPy expressions with KaTeX preview.
registerWidget('math', lazyEditor(() => import('./math/MathEditor').then(m => ({ default: m.MathEditor }))));

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
export {
  makeGraphCommitter,
  useWidgetCommit,
  WidgetEditingProvider,
  type CommitInput,
} from './context';
