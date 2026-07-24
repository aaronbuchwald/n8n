// Math widget editor (ADR 0005 B): SymPy expression editing with live KaTeX preview.
// The value is the SymPy expression string (bijective literal); the preview is best-effort,
// with fallback to monospace when conversion/rendering fails. Python is authoritative (A-D5).

import { useEffect, useRef, useState } from 'react';
import type { WidgetEditorProps } from '../registry';
import { escapeHtml, hasUnsupportedShape, sympyToLatex } from './translate';
import './math.css';

// Lazy-load KaTeX for code-splitting (B-D4: heavy editors are lazy chunks).
// KaTeX is bundled locally (npm offline), not via CDN.
let KaTeX: typeof import('katex') | null = null;
let katexCSS: boolean = false;

const loadKaTeX = async () => {
  if (KaTeX === null) {
    KaTeX = await import('katex');
    // Ensure KaTeX CSS is loaded once (bundled by Vite inline).
    if (!katexCSS) {
      // @ts-expect-error - CSS imports work in Vite but TypeScript doesn't know about them
      await import('katex/dist/katex.css');
      katexCSS = true;
    }
  }
  return KaTeX;
};

/**
 * Render LaTeX to HTML using KaTeX. Returns `null` (never throws) if KaTeX
 * itself rejects the LaTeX — the caller falls back to the raw expression.
 */
async function renderKatex(latex: string): Promise<string | null> {
  try {
    const KT = await loadKaTeX();
    return KT.renderToString(latex, { throwOnError: true });
  } catch {
    return null;
  }
}

function asString(value: unknown): string {
  if (value === undefined || value === null) return '';
  return typeof value === 'string' ? value : String(value);
}

interface PreviewState {
  status: 'empty' | 'rendered' | 'fallback';
  html: string;
}

const EMPTY_PREVIEW: PreviewState = { status: 'empty', html: '' };

// Raw-text fallback: monospace, with an explicit cue rendered alongside it
// (see JSX below) rather than a KaTeX render we can't vouch for (review #4).
const buildFallback = (raw: string): PreviewState => ({ status: 'fallback', html: escapeHtml(raw) });

/**
 * `kind: "math"` — a SymPy expression editor with live KaTeX preview.
 * The value is the expression string (e.g., "x**2 - 5*x + 6"). Editing commits on blur/Enter.
 * Preview converts to LaTeX and renders with KaTeX; shapes the mini-translator can't faithfully
 * handle (review #4), and anything KaTeX itself rejects, fall back to a labelled raw-text preview.
 */
export function MathEditor({ value, config, input, onCommit }: WidgetEditorProps) {
  const [draft, setDraft] = useState(asString(value));
  const [preview, setPreview] = useState<PreviewState>(EMPTY_PREVIEW);

  useEffect(() => {
    setDraft(asString(value));
  }, [value]);

  // `previewSeq` drops out-of-order responses from superseded drafts — the
  // same guard the table-recipe editor uses (review #10: without it, a slow
  // render for an earlier draft can land after a faster later one and show
  // stale math under the current input).
  const previewSeq = useRef(0);

  // Update preview whenever draft changes (live preview, not debounced for simplicity).
  useEffect(() => {
    const seq = ++previewSeq.current;
    const trimmed = draft.trim();

    if (trimmed === '') {
      setPreview(EMPTY_PREVIEW);
      return;
    }

    if (hasUnsupportedShape(trimmed)) {
      // Known-untranslatable shape: don't even attempt the mini translator —
      // admitting uncertainty beats a clean-but-wrong render. The server's
      // real SymPy `latex()` stays authoritative at run time (A-D5).
      setPreview(buildFallback(trimmed));
      return;
    }

    const latex = sympyToLatex(trimmed);
    void renderKatex(latex).then((html) => {
      if (seq !== previewSeq.current) return; // superseded by a later draft
      setPreview(html === null ? buildFallback(trimmed) : { status: 'rendered', html });
    });
  }, [draft]);

  const commit = () => {
    if (draft !== value) onCommit(draft);
  };

  const placeholder =
    typeof config.placeholder === 'string' ? config.placeholder : input.name;

  return (
    <div className="ge-widget-math" style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
      <input
        className="ge-widget-input"
        data-testid="widget-editor-math-input"
        type="text"
        value={draft}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') e.currentTarget.blur();
        }}
        style={{
          fontFamily: 'monospace',
          fontSize: '0.9em',
          padding: '0.4rem 0.6rem',
        }}
      />
      {preview.status !== 'empty' && (
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
      )}
    </div>
  );
}
