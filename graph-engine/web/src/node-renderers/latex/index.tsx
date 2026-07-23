// The `latex` renderer kind (ADR 0013 D5, FOR REVIEW 1 — signed off). It reads
// one LaTeX-STRING output socket from the node's latest run and typesets it with
// KaTeX in the host DOM — the deliberate, reviewed deviation from ADR 0010 D5's
// iframe-for-HTML rule: KaTeX parses LaTeX text and emits its OWN markup, so no
// upstream value string is ever interpolated into HTML. `trust: false` (default)
// refuses `\href`/`\includegraphics`-class commands; `throwOnError: true` falls
// back to the informative result chips; a non-string socket does too. Before the
// first run it shows the standard placeholder.
//
// FROZEN contract with the Python stream: the kind name is exactly `"latex"` and
// it reads the socket `config.socket` (default `"latex"`). handcalc declares
// `Renderer("latex", socket="latex")`. Lazy code-split chunk, npm-bundled, no CDN.

import { useEffect, useState } from 'react';
import { ResultChips } from '../ResultChips';
import type { NodeRendererProps } from '../registry';

const DEFAULT_SOCKET = 'latex';

/** Typeset LaTeX to an HTML string; null when KaTeX rejects it (→ chips). */
async function renderLatex(latex: string): Promise<string | null> {
  try {
    const KT = await import('katex');
    // @ts-expect-error - CSS imports work in Vite but TypeScript doesn't know about them
    await import('katex/dist/katex.css');
    return KT.renderToString(latex, {
      throwOnError: true,
      trust: false,
      displayMode: true,
    });
  } catch {
    return null;
  }
}

export default function LatexRenderer({ config, result, hasError, surface }: NodeRendererProps) {
  const socket = typeof config.socket === 'string' ? config.socket : DEFAULT_SOCKET;
  const value = result ? result[socket] : undefined;
  const latex = typeof value === 'string' ? value : null;

  const [html, setHtml] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (latex === null) {
      setHtml(null);
      setFailed(false);
      return;
    }
    let live = true;
    void renderLatex(latex).then((out) => {
      if (!live) return;
      if (out === null) setFailed(true);
      else {
        setHtml(out);
        setFailed(false);
      }
    });
    return () => {
      live = false;
    };
  }, [latex]);

  // No run yet (or it failed upstream): plain-text placeholder, no typesetting.
  if (result === null) {
    return (
      <div className="ge-node__result" data-testid="latex-renderer" data-renderer-surface={surface}>
        <span className="ge-node__result-value">{hasError ? 'run failed' : 'run to render'}</span>
      </div>
    );
  }

  // A non-string socket, or LaTeX KaTeX can't parse: honest chips fallback.
  if (latex === null || failed) {
    return (
      <div data-testid="latex-renderer" data-renderer-surface={surface}>
        <ResultChips result={result} />
      </div>
    );
  }

  // KaTeX still loading its chunk: a brief placeholder, never the raw string.
  if (html === null) {
    return (
      <div className="ge-node__result" data-testid="latex-renderer" data-renderer-surface={surface}>
        <span className="ge-node__result-value">…</span>
      </div>
    );
  }

  return (
    <div className="ge-latex-card" data-testid="latex-renderer" data-renderer-surface={surface}>
      {/* KaTeX-generated markup (not upstream HTML) — the reviewed host-DOM
          posture, matching the calc/math draft-preview precedent. */}
      <div
        className="ge-latex-card__body"
        data-testid="latex-card-body"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  );
}
