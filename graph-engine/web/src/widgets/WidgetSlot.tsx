// The one editor slot SpecNode mounts (ADR 0005 A-D4). It is the single shared
// merge hazard of Stream A, so ALL widget logic lives here (an owned file):
// SpecNode changes reduce to importing this component and rendering it for a
// non-wired input. Streams B / C-ui only ADD editor files + one registration
// line each; they never touch SpecNode or this slot.
//
// Two modes:
//  * read-only (no commit in context) — reproduces today's exact markup (value
//    chip / widget-kind label / required), so the read-only canvas is unchanged.
//  * editable (a commit is provided) — an input WITH a widget renders
//    `editorFor(input.widget)`, collapsed to a value chip that expands on click.

import { Suspense, useState } from 'react';
import type { SpecInput } from '../types';
import './index'; // side-effect: register the built-in editors once
import { editorFor } from './registry';
import { useWidgetCommit } from './context';

interface WidgetSlotProps {
  input: SpecInput;
  /** The literal bound to this input in the graph, if any. */
  value: unknown;
  /** Whether the graph carries a literal for this input (distinguishes null/absent). */
  hasLiteral: boolean;
  /** The graph node id this input belongs to. */
  nodeId: string;
}

function formatValue(v: unknown): string {
  if (typeof v === 'string') return `"${v}"`;
  const json: string | undefined = JSON.stringify(v);
  return json ?? String(v);
}

/** Today's passive rendering — unchanged when the canvas is read-only. */
function ReadOnlyState({ input, value, hasLiteral }: Omit<WidgetSlotProps, 'nodeId'>) {
  if (hasLiteral) {
    const literal = formatValue(value);
    return (
      <span className="ge-socket__state ge-socket__state--value" title={literal}>
        {literal}
      </span>
    );
  }
  if (input.widget) {
    return <span className="ge-socket__state ge-socket__state--widget">{input.widget.kind}</span>;
  }
  if (input.required) {
    return <span className="ge-socket__state ge-socket__state--required">required</span>;
  }
  return null;
}

export function WidgetSlot({ input, value, hasLiteral, nodeId }: WidgetSlotProps) {
  const commit = useWidgetCommit();
  const [open, setOpen] = useState(false);

  // Read-only, or a non-widget input (list/dict/etc.): today's behavior.
  if (!commit || !input.widget) {
    return <ReadOnlyState input={input} value={value} hasLiteral={hasLiteral} />;
  }

  const Editor = editorFor(input.widget);
  const chip = hasLiteral ? formatValue(value) : input.widget.kind;

  if (!open) {
    return (
      <button
        type="button"
        className="ge-socket__state ge-socket__state--widget ge-widget-chip"
        data-testid="widget-chip"
        title={`Edit ${input.name}`}
        onClick={() => setOpen(true)}
      >
        {chip}
      </button>
    );
  }

  return (
    <span className="ge-widget-slot" data-testid="widget-slot">
      <Suspense fallback={<span className="ge-socket__state">…</span>}>
        <Editor
          value={value}
          config={input.widget.config ?? {}}
          input={input}
          onCommit={(next) => {
            commit(nodeId, input.name, next);
            setOpen(false);
          }}
        />
      </Suspense>
    </span>
  );
}
