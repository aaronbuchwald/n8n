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
  /** 1-based line number in the authored text. */
  lineno: number;
  /** `calcsheet` dialect only: the entry's display unit / reference ('' = none). */
  unit: string;
  ref: string;
}

function asString(value: unknown): string {
  if (value === undefined || value === null) return '';
  return typeof value === 'string' ? value : String(value);
}

function languageOf(config: Record<string, unknown>): string | undefined {
  return typeof config.language === 'string' ? config.language : undefined;
}

/**
 * Typeset a multi-line calc string; renders nothing when there is no content.
 *
 * In the `calcsheet` dialect each row renders as its **anatomy** (ADR 0018 D4):
 * the typeset expression, its unit as a small chip, and its reference in a
 * muted right-hand gutter — the same three slots the rendered card gives them,
 * so watching `# demand / capacity` jump into the gutter teaches the syntax.
 */
export function CalcPreview({ text, language }: { text: string; language?: string }) {
  const [lines, setLines] = useState<RenderedLine[]>([]);
  // Drop superseded async renders (a slow earlier draft landing after a later).
  const seq = useRef(0);

  useEffect(() => {
    const current = ++seq.current;
    const parsed = calcLinesToPreview(text, language);
    if (parsed.length === 0) {
      setLines([]);
      return;
    }
    void Promise.all(
      parsed.map(async (line): Promise<RenderedLine> => {
        const slots = { lineno: line.lineno, unit: line.unit, ref: line.ref };
        if (line.latex === null) return { html: escapeHtml(line.raw), fallback: true, ...slots };
        const html = await renderKatex(line.latex);
        return html === null
          ? { html: escapeHtml(line.raw), fallback: true, ...slots }
          : { html, fallback: false, ...slots };
      }),
    ).then((rendered) => {
      if (current === seq.current) setLines(rendered);
    });
  }, [text, language]);

  if (lines.length === 0) return null;
  return (
    <div className="ge-calc-preview" data-testid="calc-preview">
      {lines.map((line, i) => (
        <div
          key={i}
          className="ge-calc-preview__row"
          data-testid="calc-preview-row"
          data-line={line.lineno}
          data-fallback={line.fallback ? 'true' : 'false'}
        >
          <span
            className={
              line.fallback
                ? 'ge-calc-preview__line ge-calc-preview__line--raw'
                : 'ge-calc-preview__line'
            }
            dangerouslySetInnerHTML={{ __html: line.html }}
          />
          {line.unit !== '' && (
            <span className="ge-calc-preview__unit" data-testid="calc-preview-unit">
              {line.unit}
            </span>
          )}
          {line.ref !== '' && (
            <span className="ge-calc-preview__ref" data-testid="calc-preview-ref">
              {line.ref}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

/** Card preview (ADR 0013 D2): typeset the committed calc literal, read-only. */
export default function CalcCardPreview({ value, config }: WidgetPreviewProps) {
  return <CalcPreview text={asString(value)} language={languageOf(config)} />;
}
