// The fallback editor (ADR 0005 A-D4/A-D6). Used when a widget's `kind` has no
// registered editor — an unknown/newer kind degrades to a basic editor chosen
// by the input's Python type, rather than failing. This IS the versioning story
// for the open `kind` vocabulary.

import { CheckboxEditor, NumberEditor, TextEditor } from './builtins';
import type { WidgetEditorProps } from './registry';

export function DefaultEditor(props: WidgetEditorProps) {
  switch (props.input.type) {
    case 'int':
    case 'float':
      return <NumberEditor {...props} />;
    case 'bool':
      return <CheckboxEditor {...props} />;
    default:
      return <TextEditor {...props} />;
  }
}
