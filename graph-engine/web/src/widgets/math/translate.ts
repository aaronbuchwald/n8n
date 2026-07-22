// Pure, synchronous SymPy(subset) -> LaTeX text transforms, plus a same-string
// "can this be trusted?" detector (ADR 0005 B; UI review 0005 #4). No KaTeX/DOM
// dependency here, so this is unit-testable without a browser. The server's
// real SymPy `latex()` stays authoritative at run time (A-D5) — this module
// only decides what to show in the live, best-effort preview.

/**
 * Convert a constrained subset of SymPy syntax to LaTeX (B: the mini-translator).
 * Handles arithmetic, exponents, sqrt, common symbols. Falls back to the raw
 * string if conversion can't complete (callers should prefer {@link hasUnsupportedShape}
 * to decide *before* calling this whether the result can be trusted at all).
 *
 * Examples:
 *  "x**2" → "x^{2}"
 *  "sqrt(x)" → "\sqrt{x}"
 *  "pi" → "\pi"
 *  "x*y" → "x \cdot y"
 *  "a = b + c" → "a = b + c"
 */
export function sympyToLatex(expr: string): string {
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
 * Shapes the mini-translator provably mistranslates *without* erroring, so
 * they'd otherwise render confidently-wrong KaTeX (review #4):
 *
 *  - Complex exponent: `x**(y+1)` or `x**sqrt(y)` — the exponent regex only
 *    understands a bare word/number or an already-braced group as the
 *    right-hand side; anything else (a parenthesized group, a function call)
 *    is left unconverted and the literal `**` degrades to `⋅⋅` in the
 *    multiplication pass.
 *  - Chained exponentiation: `2**x**2` — the middle operand is consumed by
 *    the first exponent match, orphaning the second `**` (same `⋅⋅` artifact).
 *  - Nested function calls: `sqrt(sqrt(x))` — the `sqrt(...)` regex captures
 *    up to the *first* `)`, which belongs to the inner call, mangling both.
 *
 * All three are valid SymPy the server renders correctly via real `latex()`;
 * this only decides whether the client-side approximation can be trusted.
 * Deliberately conservative — a false positive just means an honest raw-text
 * fallback instead of clean-but-wrong math, which is the better failure mode.
 */
export function hasUnsupportedShape(expr: string): boolean {
  const trimmed = expr.trim();
  if (trimmed === '') return false;

  // `**` followed by `(` (grouped exponent) or `name(` (call as exponent).
  if (/\*\*\s*([A-Za-z_]\w*\(|\()/.test(trimmed)) return true;

  // `**` ... `**` with only a single bare token between them (a chain).
  if (/\*\*\s*[A-Za-z0-9_.]+\s*\*\*/.test(trimmed)) return true;

  // `name(...name(` — a call opened again before the outer call's first `)`.
  if (/[A-Za-z_]\w*\(([^()]*[A-Za-z_]\w*\()/.test(trimmed)) return true;

  return false;
}

export function escapeHtml(text: string): string {
  const map: Record<string, string> = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;',
  };
  return text.replace(/[&<>"']/g, (c) => map[c]);
}
