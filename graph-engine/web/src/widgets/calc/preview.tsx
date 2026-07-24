// The calc typeset preview, extracted from CalcEditor (ADR 0013 D3) so ONE
// typesetting pipeline serves two mounts: the editor's live draft preview and
// the read-only card preview. Both feed calc lines through the same
// `calc/translate.ts` → KaTeX path, with the honest raw-text fallback per line.
//
//  * `CalcPreview` renders a text of calc lines — the editor passes its draft;
//  * the default export adapts the widget-preview contract (the committed
//    literal as value) for the card registry (block placement).

import { useEffect, useRef, useState } from 'react';
import { escapeHtml } from '../math/translate';
import { renderKatex } from '../katex';
import type { WidgetPreviewProps } from '../registry';
import { calcLinesToPreview } from './translate';
import './calc.css';

interface RenderedLine {
  /** KaTeX HTML, or escaped raw text when `fallback`. */
  html: string;
  fallback: boolean;
}

function asString(value: unknown): string {
  if (value === undefined || value === null) return '';
  return typeof value === 'string' ? value : String(value);
}

/** Typeset a multi-line calc string; renders nothing when there is no content. */
export function CalcPreview({ text }: { text: string }) {
  const [lines, setLines] = useState<RenderedLine[]>([]);
  // Drop superseded async renders (a slow earlier draft landing after a later).
  const seq = useRef(0);

  useEffect(() => {
    const current = ++seq.current;
    const parsed = calcLinesToPreview(text);
    if (parsed.length === 0) {
      setLines([]);
      return;
    }
    void Promise.all(
      parsed.map(async (line): Promise<RenderedLine> => {
        if (line.latex === null) return { html: escapeHtml(line.raw), fallback: true };
        const html = await renderKatex(line.latex);
        return html === null
          ? { html: escapeHtml(line.raw), fallback: true }
          : { html, fallback: false };
      }),
    ).then((rendered) => {
      if (current === seq.current) setLines(rendered);
    });
  }, [text]);

  if (lines.length === 0) return null;
  return (
    <div className="ge-calc-preview" data-testid="calc-preview">
      {lines.map((line, i) => (
        <div
          key={i}
          className={
            line.fallback ? 'ge-calc-preview__line ge-calc-preview__line--raw' : 'ge-calc-preview__line'
          }
          dangerouslySetInnerHTML={{ __html: line.html }}
        />
      ))}
    </div>
  );
}

/** Card preview (ADR 0013 D2): typeset the committed calc literal, read-only. */
export default function CalcCardPreview({ value }: WidgetPreviewProps) {
  return <CalcPreview text={asString(value)} />;
}
