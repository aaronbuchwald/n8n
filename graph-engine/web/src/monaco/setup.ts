// Monaco, wired for a strictly offline bundle (no CDN — see web/README.md).
//
// Three things make Monaco load entirely from our own dist/ instead of the
// default jsdelivr/unpkg CDN:
//   1. We import the slim `editor.api` (not the `monaco-editor` barrel), so only
//      the editor core is pulled in — no TS/JSON/HTML/CSS languages we don't use.
//   2. `python.contribution` registers the Python Monarch grammar so
//      `language: 'python'` highlights.
//   3. `MonacoEnvironment.getWorker` returns a Vite `?worker` import of the base
//      editor worker, bundled into dist/ as a same-origin chunk. Python-only
//      highlighting needs no language worker, so the base editor worker suffices
//      for every worker label.
import * as monaco from 'monaco-editor/esm/vs/editor/editor.api';
import 'monaco-editor/esm/vs/basic-languages/python/python.contribution';
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker';

declare global {
  interface Window {
    // Vite reads MonacoEnvironment off the global to locate workers.
    MonacoEnvironment?: monaco.Environment;
    // Exposed so the e2e suite can read/round-trip the model faithfully instead
    // of scraping Monaco's virtual-scrolled DOM. Harmless in production.
    monaco?: typeof monaco;
  }
}

window.MonacoEnvironment = {
  getWorker() {
    return new EditorWorker();
  },
};

// Dark theme aligned to the app's --ge-* design tokens (Monaco themes take hex,
// not CSS vars, so the values mirror the tokens in styles.css).
let themeDefined = false;
export function ensureGeTheme(): void {
  if (themeDefined) return;
  monaco.editor.defineTheme('ge-dark', {
    base: 'vs-dark',
    inherit: true,
    rules: [
      { token: '', foreground: 'd6e2f5' },
      { token: 'comment', foreground: '5c6577', fontStyle: 'italic' },
      { token: 'keyword', foreground: '6d9eff' },
      { token: 'string', foreground: '3ecf8e' },
      { token: 'number', foreground: 'e3b262' },
      { token: 'identifier', foreground: 'd6e2f5' },
    ],
    colors: {
      'editor.background': '#0b0e14',
      'editor.foreground': '#d6e2f5',
      'editorLineNumber.foreground': '#3a4356',
      'editorLineNumber.activeForeground': '#8a93a6',
      'editor.selectionBackground': '#6d9eff33',
      'editor.lineHighlightBackground': '#161b2566',
      'editorCursor.foreground': '#6d9eff',
      'editorIndentGuide.background': '#1a2130',
      'editorWidget.background': '#10141c',
      'editorWidget.border': '#2a3140',
    },
  });
  themeDefined = true;
}

window.monaco = monaco;

export { monaco };
