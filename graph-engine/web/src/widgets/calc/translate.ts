// Best-effort calc-line → LaTeX for the live preview (reusing the math
// widget's mini-translator, ADR 0005 B). The calc's value language is Python
// assignment lines (ADR 0007 D3), so this adds exactly two things on top:
// per-line handling and subscript grouping for snake_case symbols
// (`C_min` → `C_{min}`, matching how handcalcs itself typesets them). Same
// honesty rule as the math widget: a line the translator can't vouch for
// falls back to labelled raw text — Python stays authoritative (A-D5).
//
// Two dialects (ADR 0018 D2), selected by the widget's `config.language`:
//
//  * `python-calc` (the default, `sym.handcalc`) — a line containing `#` or a
//    quote is NOT math and falls back to raw text, unchanged;
//  * `calcsheet` (`sheet.calc_card` / `sheet.calc`) — `#` and a trailing `[unit]` are
//    STRUCTURE, not math: a pre-pass splits each entry into
//    (expression, unit, reference) with the same textual rules as the Python
//    `_entries`/`_UNIT`, and only the expression is typeset. The unit and the
//    reference are rendered as their own slots by the preview (D4).

import { hasUnsupportedShape, sympyToLatex } from '../math/translate';

/** The value language of a calc literal — a widget `config.language` value. */
export type CalcLanguage = 'python-calc' | 'calcsheet';

export interface PreviewLine {
  /** The raw source line (trimmed) — in the `calcsheet` dialect, its expression. */
  raw: string;
  /** LaTeX to render, or null when only the raw fallback can be trusted. */
  latex: string | null;
  /** 1-based line number in the authored text (what Python's errors name). */
  lineno: number;
  /** `calcsheet`: the trailing `[unit]`'s text; '' in every other case. */
  unit: string;
  /** `calcsheet`: the `# reference` text; '' in every other case. */
  ref: string;
}

// `name_sub` → `name_{sub}`; only for a single underscore with simple parts —
// anything fancier (double underscores, trailing underscore) is left alone and
// caught by the trust check below.
function groupSubscripts(line: string): string {
  return line.replace(/\b([A-Za-z]+)_([A-Za-z0-9]+)\b/g, '$1_{$2}');
}

/** Names the subscript pass would mis-group into nested subscripts. */
function hasMultiUnderscoreName(text: string): boolean {
  return /\b\w*[A-Za-z0-9]_\w*_\w*\b/.test(text);
}

/** Shapes the calc preview cannot faithfully typeset (fall back to raw text). */
function calcLineUnsupported(line: string): boolean {
  if (hasUnsupportedShape(line)) return true;
  // Multi-underscore names would mis-group to nested subscripts.
  if (hasMultiUnderscoreName(line)) return true;
  // Comments and strings are not math; keep them readable as raw text.
  if (line.includes('#') || line.includes('"') || line.includes("'")) return true;
  return false;
}

// A trailing `[...]` on a formula expression — its display unit. Mirrors
// `_UNIT` in nodepacks/sheet/__init__.py.
const CALCSHEET_UNIT = /\[([^[\]]*)\]\s*$/;

interface Anatomy {
  expr: string;
  unit: string;
  ref: string;
}

/**
 * Split one `calcsheet` entry into its three fields, mirroring the Python
 * `_entries` (everything after the FIRST `#` is the reference) and `_UNIT` (a
 * trailing bracket on the body is the display unit). Presentation only — this
 * never decides validity; `parse_formulas` (via /derive) and the run do.
 */
function calcsheetAnatomy(line: string): Anatomy {
  const hash = line.indexOf('#');
  const body = (hash === -1 ? line : line.slice(0, hash)).trim();
  const ref = hash === -1 ? '' : line.slice(hash + 1).trim();
  const unitMatch = CALCSHEET_UNIT.exec(body);
  if (unitMatch === null) return { expr: body, unit: '', ref };
  return { expr: body.slice(0, unitMatch.index).trim(), unit: unitMatch[1].trim(), ref };
}

/** Shapes the dialect cannot typeset once `#`/`[unit]` have been split off. */
function calcsheetExprUnsupported(expr: string): boolean {
  if (expr === '') return true;
  if (hasUnsupportedShape(expr)) return true;
  if (hasMultiUnderscoreName(expr)) return true;
  // A surviving bracket means the unit split did not apply; quotes are not math.
  if (/[[\]"']/.test(expr)) return true;
  return false;
}

function calcsheetLines(text: string): PreviewLine[] {
  const out: PreviewLine[] = [];
  text.split('\n').forEach((rawLine, index) => {
    const line = rawLine.trim();
    // Blank lines and whole-line comments are not entries (Python skips them).
    if (line === '' || line.startsWith('#')) return;
    const { expr, unit, ref } = calcsheetAnatomy(line);
    const fallback = calcsheetExprUnsupported(expr);
    out.push({
      raw: expr === '' ? line : expr,
      latex: fallback ? null : sympyToLatex(groupSubscripts(expr)),
      lineno: index + 1,
      unit,
      ref,
    });
  });
  return out;
}

/**
 * Translate a multi-line calc draft to per-line preview entries.
 *
 * `language` selects the dialect; anything other than `calcsheet` (including
 * the absent default) keeps the original `python-calc` behavior byte for byte.
 */
export function calcLinesToPreview(text: string, language?: string): PreviewLine[] {
  if (language === 'calcsheet') return calcsheetLines(text);
  const out: PreviewLine[] = [];
  text.split('\n').forEach((rawLine, index) => {
    const raw = rawLine.trim();
    if (raw === '') return;
    out.push({
      raw,
      latex: calcLineUnsupported(raw) ? null : sympyToLatex(groupSubscripts(raw)),
      lineno: index + 1,
      unit: '',
      ref: '',
    });
  });
  return out;
}
