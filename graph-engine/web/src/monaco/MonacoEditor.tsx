import { useEffect, useRef } from 'react';

import { ensureGeTheme, monaco } from './setup';

interface MonacoEditorProps {
  /** Current source text (controlled from the parent). */
  value: string;
  /** Read-only while the source is still loading. */
  readOnly: boolean;
  /** Fired on every model edit with the full new text. */
  onChange: (value: string) => void;
}

/**
 * Thin React wrapper that mounts a single Monaco editor for the `@node` source.
 * Kept in its own module (imported lazily by SourceEditor via React.lazy) so
 * the heavy Monaco chunk only loads when the source editor opens.
 */
export default function MonacoEditor({ value, readOnly, onChange }: MonacoEditorProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const editorRef = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
  // Keep the latest onChange without re-creating the editor on every render.
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    ensureGeTheme();
    const editor = monaco.editor.create(container, {
      value,
      language: 'python',
      theme: 'ge-dark',
      readOnly,
      automaticLayout: true,
      minimap: { enabled: false },
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
      fontSize: 12,
      lineHeight: 19,
      tabSize: 4,
      insertSpaces: true,
      lineNumbers: 'on',
      renderWhitespace: 'none',
      scrollBeyondLastLine: false,
      smoothScrolling: true,
      padding: { top: 10, bottom: 10 },
      scrollbar: { verticalScrollbarSize: 10, horizontalScrollbarSize: 10 },
    });
    editorRef.current = editor;

    const sub = editor.onDidChangeModelContent(() => {
      onChangeRef.current(editor.getValue());
    });

    return () => {
      sub.dispose();
      editor.dispose();
      editorRef.current = null;
    };
    // Editor is created once; value/readOnly are synced by the effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Sync external value changes (e.g. the pristine source re-set after a save)
  // without clobbering the cursor while the user is typing.
  useEffect(() => {
    const editor = editorRef.current;
    if (editor && editor.getValue() !== value) {
      editor.setValue(value);
    }
  }, [value]);

  useEffect(() => {
    editorRef.current?.updateOptions({ readOnly });
  }, [readOnly]);

  return (
    <div
      ref={containerRef}
      className="ge-source__monaco"
      data-testid="source-monaco"
      role="textbox"
      aria-label="Python source editor"
    />
  );
}
