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
 */
export const renderKatex = async (
  latex: string,
  options?: import('katex').KatexOptions,
): Promise<string | null> => {
  try {
    const KT = await loadKaTeX();
    return KT.renderToString(latex, { throwOnError: true, ...options });
  } catch {
    return null;
  }
};
