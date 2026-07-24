// One lazy, offline KaTeX loader shared by every typeset surface (the math/calc
// editors and their read-only card previews — ADR 0013 D2/D3). KaTeX is
// npm-bundled and code-split: the first typeset surface to mount pulls the
// chunk, later ones reuse it. No CDN, ever. Python's real SymPy `latex()` stays
// authoritative at run time (A-D5); this only feeds the best-effort preview.

let KaTeX: typeof import('katex') | null = null;
let cssLoaded = false;

export const loadKaTeX = async (): Promise<typeof import('katex')> => {
  if (KaTeX === null) {
    KaTeX = await import('katex');
    if (!cssLoaded) {
      // @ts-expect-error - CSS imports work in Vite but TypeScript doesn't know about them
      await import('katex/dist/katex.css');
      cssLoaded = true;
    }
  }
  return KaTeX;
};

/**
 * Render LaTeX to an HTML string via KaTeX. Returns `null` (never throws) when
 * KaTeX rejects the input, so callers fall back to honest raw text / chips.
 *
 * `trust: false` is PINNED last, after the caller's `options`, so it can never
 * be overridden. Every surface fed by this loader is read-only (the card
 * previews, ADR 0013 D2/D3) or an inert draft preview, and the calc/math
 * translators forward unrecognized LaTeX verbatim — so an equation carrying
 * `\href`/`\url`/`\includegraphics` must never become a live `<a>`/asset
 * ("link out of a formula"). This matches the `latex` renderer's posture and
 * keeps the previews inert: a click just selects the node, never navigates.
 */
export const renderKatex = async (
  latex: string,
  options?: import('katex').KatexOptions,
): Promise<string | null> => {
  try {
    const KT = await loadKaTeX();
    return KT.renderToString(latex, { throwOnError: true, ...options, trust: false });
  } catch {
    return null;
  }
};
