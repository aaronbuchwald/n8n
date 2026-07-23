// The card's ONLY widget mount (ADR 0013 D2/D3). Read-only by construction: it
// takes no commit and mounts no editor — all editing moved to the inspector
// (D1/D4). It renders `previewFor(input.widget)` for the slot it sits in
// (inline in the socket row, or block in the card's preview strip), with the
// value-chip fallback (moved here from the deleted WidgetSlot) for any kind
// that registered no preview.
//
// `slot` selects which placement this mount serves, so each widget-bearing
// input renders exactly once: inline kinds (+ the fallback) in the socket row,
// block kinds (typeset math/calc) in the strip. A mismatched mount renders
// nothing.

import { Suspense } from 'react';
import type { ReactNode } from 'react';
import type { SpecInput } from '../types';
import './index'; // side-effect: register the built-in previews/editors once
import { previewFor, type PreviewPlacement } from './registry';

interface WidgetPreviewProps {
  input: SpecInput;
  /** The literal bound to this input in the graph, if any. */
  value: unknown;
  /** Whether the graph carries a literal for this input (null/absent apart). */
  hasLiteral: boolean;
  /** Which card slot this mount serves: the socket row or the block strip. */
  slot: PreviewPlacement;
}

function formatValue(v: unknown): string {
  if (typeof v === 'string') return `"${v}"`;
  const json: string | undefined = JSON.stringify(v);
  return json ?? String(v);
}

/** Today's passive value chip — the fallback for an unregistered widget kind. */
function readOnlyState({
  input,
  value,
  hasLiteral,
}: Omit<WidgetPreviewProps, 'slot'>): ReactNode {
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

export function WidgetPreview({ input, value, hasLiteral, slot }: WidgetPreviewProps) {
  const registered = previewFor(input.widget);
  const placement: PreviewPlacement = registered?.placement ?? 'inline';
  // Only render in the slot this preview belongs to (block previews live in the
  // strip; inline previews + the fallback live in the socket row).
  if (placement !== slot) return null;

  const kind = input.widget?.kind;

  if (!registered) {
    const state = readOnlyState({ input, value, hasLiteral });
    if (state === null) return null;
    return (
      <span className="ge-widget-preview" data-testid="widget-preview" data-kind={kind} data-input={input.name}>
        {state}
      </span>
    );
  }

  const Preview = registered.component;
  const wrapperClass =
    slot === 'block' ? 'ge-widget-preview ge-widget-preview--block' : 'ge-widget-preview';
  const content = (
    <Suspense fallback={<span className="ge-socket__state">…</span>}>
      <Preview value={value} config={input.widget?.config ?? {}} input={input} />
    </Suspense>
  );
  return slot === 'block' ? (
    <div className={wrapperClass} data-testid="widget-preview" data-kind={kind} data-input={input.name}>
      {content}
    </div>
  ) : (
    <span className={wrapperClass} data-testid="widget-preview" data-kind={kind} data-input={input.name}>
      {content}
    </span>
  );
}
