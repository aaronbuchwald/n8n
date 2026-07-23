// The math read-only card preview (ADR 0013 D2/D3): typeset the committed SymPy
// literal with KaTeX, using the same mini-translator + honesty rule as the math
// editor's draft preview (ADR 0005 B). A shape the translator can't vouch for,
// or anything KaTeX rejects, falls back to labelled raw text — Python's real
// SymPy `latex()` stays authoritative at run time (A-D5). Block placement.

import { useEffect, useRef, useState } from 'react';
import { renderKatex } from '../katex';
import type { WidgetPreviewProps } from '../registry';
import { escapeHtml, hasUnsupportedShape, sympyToLatex } from './translate';
import './math.css';

interface PreviewState {
  status: 'empty' | 'rendered' | 'fallback';
  html: string;
}

const EMPTY_PREVIEW: PreviewState = { status: 'empty', html: '' };

function asString(value: unknown): string {
  if (value === undefined || value === null) return '';
  return typeof value === 'string' ? value : String(value);
}

export default function MathCardPreview({ value }: WidgetPreviewProps) {
  const [preview, setPreview] = useState<PreviewState>(EMPTY_PREVIEW);
  // Drop out-of-order renders from a superseded value.
  const seq = useRef(0);

  useEffect(() => {
    const current = ++seq.current;
    const trimmed = asString(value).trim();
    if (trimmed === '') {
      setPreview(EMPTY_PREVIEW);
      return;
    }
    if (hasUnsupportedShape(trimmed)) {
      setPreview({ status: 'fallback', html: escapeHtml(trimmed) });
      return;
    }
    void renderKatex(sympyToLatex(trimmed)).then((html) => {
      if (current !== seq.current) return;
      setPreview(html === null ? { status: 'fallback', html: escapeHtml(trimmed) } : { status: 'rendered', html });
    });
  }, [value]);

  if (preview.status === 'empty') return null;
  return (
    <div
      className={`ge-widget-math-preview${preview.status === 'fallback' ? ' mw-fallback' : ''}`}
      data-testid="widget-math-preview"
    >
      {preview.status === 'fallback' && (
        <div className="mw-fallback__cue" data-testid="widget-math-fallback-cue">
          Approximate preview — can&apos;t typeset, showing raw expression
        </div>
      )}
      <div
        className={preview.status === 'fallback' ? 'mw-fallback__code' : undefined}
        dangerouslySetInnerHTML={{ __html: preview.html }}
      />
    </div>
  );
}
