// The `html-card` renderer kind (ADR 0010 D5/D6, stream 10-K) — the first
// product kind. It reads one HTML-string output socket from the node's latest
// run and shows it in a FULLY SANDBOXED iframe:
//
//  * `sandbox=""` — no scripts, no same-origin, no forms, no top-navigation.
//    The value is untrusted node output; it can never touch the host page.
//    Never `dangerouslySetInnerHTML`, here or in any kind, ever.
//  * A scriptless iframe cannot report its content height, so the frame is a
//    declared size and the card scrolls inside it when its content is taller.
//  * The iframe mounts only once a run produced a value (placeholder text
//    before) and is `loading="lazy"` — the D5 canvas-cost ladder.
//
// Config: `{ socket?: string, height?: number }`.
// `socket` defaults to the node's single output (the engine validates the
// declaration against the node's outputs at import time). Non-string values,
// `{"$repr","$type"}` previews and missing sockets degrade to the informative
// result chips. The same component serves both surfaces (`card` and `panel`).

import { ResultChips } from '../ResultChips';
import type { NodeRendererProps } from '../registry';
import type { NodeSpec } from '../../types';

const DEFAULT_HEIGHT = 180;


/** The output socket this card reads: `config.socket`, else the sole output. */
function socketName(config: Record<string, unknown>, spec: NodeSpec): string {
  if (typeof config.socket === 'string') return config.socket;
  if (spec.outputs.length === 1) return spec.outputs[0].name;
  // Several outputs and no `socket` passed engine validation only because a
  // socket named `result` is among them (engine/spec.py, ADR 0010 D1).
  return 'result';
}

/** The declared surface height in px; malformed config falls back to default. */
function declaredHeight(config: Record<string, unknown>): number {
  const height = config.height;
  return typeof height === 'number' && Number.isFinite(height) && height > 0
    ? height
    : DEFAULT_HEIGHT;
}


export default function HtmlCardRenderer({
  spec,
  config,
  result,
  hasError,
  surface,
}: NodeRendererProps) {
  // No run yet (or the run failed upstream): plain-text placeholder — the
  // iframe only exists when there is a value to show.
  if (result === null) {
    return (
      <div
        className="ge-node__result"
        data-testid="html-card-renderer"
        data-renderer-surface={surface}
      >
        <span className="ge-node__result-value">{hasError ? 'run failed' : 'run to render'}</span>
      </div>
    );
  }

  const value = result[socketName(config, spec)];

  // Only a plain string can feed the iframe (D5): anything else — a missing
  // socket, a non-string, a {"$repr","$type"} preview — shows as chips.
  if (typeof value !== 'string') {
    return (
      <div data-testid="html-card-renderer" data-renderer-surface={surface}>
        <ResultChips result={result} />
      </div>
    );
  }

  return (
    <div className="ge-html-card" data-testid="html-card-renderer" data-renderer-surface={surface}>
      <iframe
        className="ge-html-card__frame"
        data-testid="html-card-frame"
        title={`${spec.title} render`}
        // Fully sandboxed: the srcDoc value is untrusted HTML from node output.
        sandbox=""
        loading="lazy"
        srcDoc={value}
        style={{ height: declaredHeight(config) }}
      />
    </div>
  );
}
