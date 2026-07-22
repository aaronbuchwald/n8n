// Math widget editor (ADR 0005 B): SymPy expression editing with live KaTeX preview.
// The value is the SymPy expression string (bijective literal); the preview is best-effort,
// with fallback to monospace when conversion/rendering fails. Python is authoritative (A-D5).

import { useEffect, useState } from 'react';
import type { WidgetEditorProps } from '../registry';

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
 * Convert a constrained subset of SymPy syntax to LaTeX (B: the mini-translator).
 * Handles arithmetic, exponents, sqrt, common symbols. Falls back to the raw string
 * if conversion can't complete or rendering throws (A-D5: Python validates, not JS).
 *
 * Examples:
 *  "x**2" → "x^{2}"
 *  "sqrt(x)" → "\sqrt{x}"
 *  "pi" → "\pi"
 *  "x*y" → "x \cdot y"
 *  "a = b + c" → "a = b + c"
 */
function sympyToLatex(expr: string): string {
  try {
    let latex = expr.trim();

    // Replace SymPy function calls: sqrt(x) -> \sqrt{x}
    latex = latex.replace(/sqrt\(([^)]+)\)/g, '\\sqrt{$1}');

    // Replace exponentiation: x**2 -> x^{2}
    // Match base (variable/number/grouped expression) followed by **exponent
    latex = latex.replace(/(\w+|\})\*\*(\{[^}]+\}|\w+)/g, '$1^{$2}');
    latex = latex.replace(/(\))\*\*(\{[^}]+\}|\w+)/g, '$1^{$2}');

    // Replace common Greek letters and constants
    const greekMap: Record<string, string> = {
      pi: '\\pi',
      Pi: '\\Pi',
      alpha: '\\alpha',
      beta: '\\beta',
      gamma: '\\gamma',
      delta: '\\delta',
      epsilon: '\\epsilon',
      zeta: '\\zeta',
      eta: '\\eta',
      theta: '\\theta',
      iota: '\\iota',
      kappa: '\\kappa',
      lambda: '\\lambda',
      mu: '\\mu',
      nu: '\\nu',
      xi: '\\xi',
      omicron: '\\omicron',
      rho: '\\rho',
      sigma: '\\sigma',
      tau: '\\tau',
      upsilon: '\\upsilon',
      phi: '\\phi',
      chi: '\\chi',
      psi: '\\psi',
      omega: '\\omega',
      infinity: '\\infty',
      oo: '\\infty',
    };

    for (const [key, value] of Object.entries(greekMap)) {
      const regex = new RegExp(`\\b${key}\\b`, 'g');
      latex = latex.replace(regex, value);
    }

    // Replace multiplication: x*y -> x \cdot y (but preserve function args like sqrt(x*y))
    // Heuristic: replace * only if not inside parentheses
    let depth = 0;
    let result = '';
    for (let i = 0; i < latex.length; i++) {
      const char = latex[i];
      if (char === '(') depth++;
      else if (char === ')') depth--;
      else if (char === '*' && depth === 0) {
        result += ' \\cdot ';
        continue;
      }
      result += char;
    }
    latex = result;

    return latex;
  } catch {
    // Any error in conversion → return the raw string (fallback)
    return expr;
  }
}

/**
 * Render LaTeX to HTML using KaTeX (if loaded), or fallback to monospace text.
 * Returns HTML string for display; never throws.
 */
async function renderLatex(latex: string): Promise<{ html: string; fallback: boolean }> {
  try {
    const KT = await loadKaTeX();
    const html = KT.renderToString(latex, {
      throwOnError: true,
    });
    return { html, fallback: false };
  } catch {
    // Rendering failed → show the input string in monospace (best-effort fallback)
    return {
      html: `<code style="font-family:monospace;font-size:0.9em;color:#666">${escapeHtml(latex)}</code>`,
      fallback: true,
    };
  }
}

function escapeHtml(text: string): string {
  const map: Record<string, string> = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;',
  };
  return text.replace(/[&<>"']/g, (c) => map[c]);
}

function asString(value: unknown): string {
  if (value === undefined || value === null) return '';
  return typeof value === 'string' ? value : String(value);
}

interface PreviewState {
  html: string;
  fallback: boolean;
}

/**
 * `kind: "math"` — a SymPy expression editor with live KaTeX preview.
 * The value is the expression string (e.g., "x**2 - 5*x + 6"). Editing commits on blur/Enter.
 * Preview converts to LaTeX and renders with KaTeX; fallback to monospace on any error.
 * Config may include `placeholder` (else defaults to the input name).
 */
export function MathEditor({ value, config, input, onCommit }: WidgetEditorProps) {
  const [draft, setDraft] = useState(asString(value));
  const [preview, setPreview] = useState<PreviewState>({ html: '', fallback: false });
  const [previewReady, setPreviewReady] = useState(false);

  useEffect(() => {
    setDraft(asString(value));
  }, [value]);

  // Update preview whenever draft changes (live preview, not debounced for simplicity).
  useEffect(() => {
    const updatePreview = async () => {
      if (draft.trim() === '') {
        setPreview({ html: '', fallback: false });
        return;
      }
      const latex = sympyToLatex(draft);
      const rendered = await renderLatex(latex);
      setPreview(rendered);
      setPreviewReady(true);
    };

    updatePreview();
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
      {previewReady && preview.html && (
        <div
          className="ge-widget-math-preview"
          style={{
            fontSize: '1rem',
            padding: '0.4rem 0.6rem',
            backgroundColor: preview.fallback ? '#f5f5f5' : 'transparent',
            borderRadius: preview.fallback ? '4px' : '0',
            minHeight: '1.5em',
          }}
        >
          <div dangerouslySetInnerHTML={{ __html: preview.html }} />
        </div>
      )}
    </div>
  );
}
