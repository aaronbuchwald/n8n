// Best-effort calc-line → LaTeX for the live preview (reusing the math
// widget's mini-translator, ADR 0005 B). The calc's value language is Python
// assignment lines (ADR 0007 D3), so this adds exactly two things on top:
// per-line handling and subscript grouping for snake_case symbols
// (`C_min` → `C_{min}`, matching how handcalcs itself typesets them). Same
// honesty rule as the math widget: a line the translator can't vouch for
// falls back to labelled raw text — Python stays authoritative (A-D5).

import { hasUnsupportedShape, sympyToLatex } from '../math/translate';

export interface PreviewLine {
  /** The raw source line (trimmed). */
  raw: string;
  /** LaTeX to render, or null when only the raw fallback can be trusted. */
  latex: string | null;
}

// `name_sub` → `name_{sub}`; only for a single underscore with simple parts —
// anything fancier (double underscores, trailing underscore) is left alone and
// caught by the trust check below.
function groupSubscripts(line: string): string {
  return line.replace(/\b([A-Za-z]+)_([A-Za-z0-9]+)\b/g, '$1_{$2}');
}

/** Shapes the calc preview cannot faithfully typeset (fall back to raw text). */
function calcLineUnsupported(line: string): boolean {
  if (hasUnsupportedShape(line)) return true;
  // Multi-underscore names would mis-group to nested subscripts.
  if (/\b\w*[A-Za-z0-9]_\w*_\w*\b/.test(line)) return true;
  // Comments and strings are not math; keep them readable as raw text.
  if (line.includes('#') || line.includes('"') || line.includes("'")) return true;
  return false;
}

/** Translate a multi-line calc draft to per-line preview entries. */
export function calcLinesToPreview(text: string): PreviewLine[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line !== '')
    .map((raw) =>
      calcLineUnsupported(raw) ? { raw, latex: null } : { raw, latex: sympyToLatex(groupSubscripts(raw)) },
    );
}
