// The inspector's editing mount (ADR 0013 D4). All widget editing moved off the
// node card into the inspector; this slot mounts `editorFor(input.widget)` for
// ONE widget-bearing unwired input, inline and always expanded — no chip, no
// collapse, no capture-phase dismissal (that apparatus was canvas-only). It
// wires `onCommit` to the SAME shell context the card slot used
// (`useWidgetCommit` → the store's stable `commitLiteral`/`commitEquation`
// path), so the commit seam is UNCHANGED — only the mount point moved.

import { Suspense, useEffect, useRef } from 'react';
import type { SpecInput } from '../types';
import './index'; // side-effect: register the built-in editors once
import { useWidgetCommit } from './context';
import { editorFor } from './registry';

interface InspectorWidgetSlotProps {
  input: SpecInput;
  /** The literal bound to this input in the graph, if any. */
  value: unknown;
  /** The graph node id this input belongs to. */
  nodeId: string;
}

export function InspectorWidgetSlot({ input, value, nodeId }: InspectorWidgetSlotProps) {
  const commit = useWidgetCommit();
  const ref = useRef<HTMLDivElement>(null);

  // The one behavior ported from the deleted WidgetSlot's dismissal code: when
  // the panel closes (Escape / pane click / ×) this slot unmounts, and an
  // unmount never fires blur — so a blur-committing editor (text/number/math)
  // would drop its in-progress draft. Blur the focused field on unmount so it
  // settles first. Effect cleanup runs while the DOM is still attached.
  useEffect(
    () => () => {
      const active = document.activeElement;
      if (active instanceof HTMLElement && ref.current?.contains(active)) active.blur();
    },
    [],
  );

  if (!commit || !input.widget) return null;
  const Editor = editorFor(input.widget);

  return (
    <div
      ref={ref}
      className="ge-inspector-widget"
      data-testid="inspector-widget-slot"
      data-input={input.name}
    >
      <Suspense fallback={<span className="ge-socket__state">…</span>}>
        <Editor
          value={value}
          config={input.widget.config ?? {}}
          input={input}
          nodeId={nodeId}
          onCommit={(next) => commit(nodeId, input.name, next)}
        />
      </Suspense>
    </div>
  );
}
