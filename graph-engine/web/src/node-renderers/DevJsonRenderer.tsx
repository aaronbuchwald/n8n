// Seam-proof renderer, NOT a product kind. Registered as `dev-json` so the
// RendererSlot mount path is exercisable (and e2e-testable) before 10-K ships
// `html-card` — no served spec declares it, so it never appears in the demo.
// It renders the node's socket values as plain text (never markup — config and
// values are text per ADR 0010 D4; untrusted HTML belongs in a sandboxed
// iframe, which is 10-K's job).

import { previewValue } from '../preview';
import type { NodeRendererProps } from './registry';

export function DevJsonRenderer({ nodeId, result, hasError, surface }: NodeRendererProps) {
  return (
    <div
      className="ge-node__result"
      data-testid="dev-json-renderer"
      data-renderer-surface={surface}
      data-renderer-node={nodeId}
    >
      {result === null ? (
        <span className="ge-node__result-value">{hasError ? 'run failed' : 'run to render'}</span>
      ) : (
        Object.entries(result).map(([socket, value]) => (
          <div className="ge-node__result-row" key={socket}>
            <span className="ge-node__result-socket" title={socket}>
              {socket}
            </span>
            <span className="ge-node__result-value">{previewValue(value)}</span>
          </div>
        ))
      )}
    </div>
  );
}
