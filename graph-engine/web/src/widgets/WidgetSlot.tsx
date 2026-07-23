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

import { Suspense, useEffect, useRef, useState } from 'react';
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
  const slotRef = useRef<HTMLSpanElement>(null);

  // Dismissal: click-outside and Escape, alongside the explicit Done button.
  // A debounced editor (table 500ms, math on-change) can be typed in freely and
  // only settles on dismiss — onCommit itself NEVER closes (that was the
  // mid-edit collapse bug).
  //
  // Both listeners are CAPTURE-phase on the document: ReactFlow's pane
  // (d3-zoom) stops pointer events before they bubble back up to the document,
  // so a bubble-phase listener never sees canvas clicks — capture runs first,
  // on the way down. Escape gets the same treatment so it works regardless of
  // which element inside the editor holds focus.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (slotRef.current && !slotRef.current.contains(event.target as Node)) {
        // Settle first: blur a focused field inside the slot so blur-committing
        // editors (text/number) commit their draft before the editor unmounts
        // (unmounting alone never fires blur).
        const active = document.activeElement;
        if (active instanceof HTMLElement && slotRef.current.contains(active)) {
          active.blur();
        }
        setOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      // Escape cancels: close WITHOUT settling, leaving the last committed
      // value in place. Stop it here so nothing above reinterprets the key.
      event.stopPropagation();
      setOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown, true);
    document.addEventListener('keydown', onKeyDown, true);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown, true);
      document.removeEventListener('keydown', onKeyDown, true);
    };
  }, [open]);

  // Read-only, or a non-widget input (list/dict/etc.): today's behavior. Kept
  // byte-identical to the pre-edit markup so read-only assertions still hold.
  if (!commit || !input.widget) {
    return <ReadOnlyState input={input} value={value} hasLiteral={hasLiteral} />;
  }

  const Editor = editorFor(input.widget);
  const chip = hasLiteral ? formatValue(value) : input.widget.kind;

  if (!open) {
    return (
      <button
        type="button"
        // `nodrag` keeps a press on the chip from starting a node drag (which
        // would also select the node).
        className="ge-socket__state ge-socket__state--widget ge-widget-chip nodrag"
        data-testid="widget-chip"
        title={`Edit ${input.name}`}
        // A kind-chip (no literal yet) otherwise reads like a value ("precision
        // number") — dash the border and italicize so it reads as a placeholder.
        style={
          hasLiteral
            ? undefined
            : { border: '1px dashed var(--ge-node-border-strong)', fontStyle: 'italic' }
        }
        onClick={(event) => {
          // Opening the editor must not ALSO select the node and slide the
          // inspector over the canvas — ReactFlow's node click handler sits
          // above this button.
          event.stopPropagation();
          setOpen(true);
        }}
      >
        {chip}
        {/* The static "this is editable" cue; hover styling alone isn't discoverable. */}
        <span aria-hidden="true" style={{ marginLeft: 4, opacity: 0.6, fontStyle: 'normal' }}>
          ✎
        </span>
      </button>
    );
  }

  // `nodrag`/`nowheel`/`nopan` stop ReactFlow from stealing pointer/scroll while
  // editing inside the node card.
  return (
    <span
      ref={slotRef}
      className="ge-widget-slot nodrag nowheel nopan"
      data-testid="widget-slot"
      // Clicks inside the open editor (fields, Done) must not bubble into
      // ReactFlow's node click handler and select/inspect the node.
      onClick={(event) => event.stopPropagation()}
    >
      <span className="ge-widget-slot__bar">
        <span className="ge-widget-slot__label" title={input.name}>
          {input.name}
        </span>
        <button
          type="button"
          className="ge-widget-slot__done"
          data-testid="widget-done"
          title="Done editing"
          aria-label={`Done editing ${input.name}`}
          onClick={() => setOpen(false)}
        >
          Done
        </button>
      </span>
      <Suspense fallback={<span className="ge-socket__state">…</span>}>
        <Editor
          value={value}
          config={input.widget.config ?? {}}
          input={input}
          nodeId={nodeId}
          // onCommit persists the literal but leaves the editor OPEN — the user
          // dismisses via Done / click-outside / toggling the chip.
          onCommit={(next) => commit(nodeId, input.name, next)}
        />
      </Suspense>
    </span>
  );
}
