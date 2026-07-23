// The default render surface (ADR 0010 D3/D4): today's compact per-socket
// footer, moved verbatim from SpecNode.tsx so RendererSlot can name it as the
// fallback path. A node with no declared renderer (or an unknown kind) shows
// exactly this — byte-identical to the pre-ADR-0010 canvas.

import { previewChip, previewValue } from '../preview';

// A compact per-socket result overlay shown on a node after a run. Structured
// values summarize by shape ("html · 1.2 KB") instead of dumping raw markup;
// click the node to see everything in the inspector.
export function ResultChips({ result }: { result: Record<string, unknown> }) {
  const entries = Object.entries(result);
  if (entries.length === 0) return null;
  return (
    <div className="ge-node__result" data-testid="node-result">
      {entries.map(([socket, value]) => (
        <div className="ge-node__result-row" key={socket}>
          <span className="ge-node__result-socket" title={socket}>
            {socket}
          </span>
          <span className="ge-node__result-value" title={previewValue(value).slice(0, 400)}>
            {previewChip(value)}
          </span>
        </div>
      ))}
    </div>
  );
}
