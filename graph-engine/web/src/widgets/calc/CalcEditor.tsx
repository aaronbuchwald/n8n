// `kind: "calc"` — the dynamic handcalc equation editor (ADR 0007 D8).
//
// The value is the node's calc literal (Python assignment lines, e.g.
// "margin = C_min - F_max"). While typing, the draft is POSTed (debounced
// ~300ms) to `/api/specs/{spec_id}/derive` — Python is the ONLY parser (D4) —
// and the pending socket set renders as live chips: added symbols highlighted,
// removed symbols struck through ("will unwire" when currently wired). An
// invalid draft shows the server's error inline and is never committed.
//
// Sockets change on COMMIT, not per keystroke (blur / Cmd-Ctrl-Enter): the
// commit rides the calc host seam (host.tsx), which prunes edges into removed
// sockets in the same save and toasts what it unwired. A freshly-added symbol
// is required (amended #5) — the editor offers an optional inline value per
// added symbol; left empty, the save fails loudly with bind's error (no
// silent 0) and the module file stays untouched.

import { useEffect, useMemo, useRef, useState } from 'react';
import type { EngineErrorItem } from '../../api';
import type { WidgetEditorProps } from '../registry';
import { escapeHtml } from '../math/translate';
import { cachedDerive, deriveInputs, type DeriveOutcome } from './derive';
import { useCalcHost } from './host';
import { calcLinesToPreview } from './translate';
import './calc.css';

// KaTeX loads lazily and stays npm-bundled/offline — same pattern as the math
// widget (ADR 0005 B): the calc chunk itself is lazy, and KaTeX splits further.
let KaTeX: typeof import('katex') | null = null;
let katexCssLoaded = false;

const loadKaTeX = async () => {
  if (KaTeX === null) {
    KaTeX = await import('katex');
    if (!katexCssLoaded) {
      // @ts-expect-error - CSS imports work in Vite but TypeScript doesn't know about them
      await import('katex/dist/katex.css');
      katexCssLoaded = true;
    }
  }
  return KaTeX;
};

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

interface DeriveState {
  /** The draft text this outcome belongs to. */
  value: string;
  outcome: DeriveOutcome;
}

interface RenderedLine {
  /** KaTeX HTML, or escaped raw text when `fallback`. */
  html: string;
  fallback: boolean;
}

interface SymbolChip {
  name: string;
  state: 'kept' | 'added' | 'removed';
  wired: boolean;
}

export function CalcEditor({ value, config, input, onCommit, nodeId }: WidgetEditorProps) {
  const host = useCalcHost();
  const committed = asString(value);
  const [draft, setDraft] = useState(committed);
  const [derive, setDerive] = useState<DeriveState | null>(null);
  const [preview, setPreview] = useState<RenderedLine[]>([]);
  const [newValues, setNewValues] = useState<Record<string, string>>({});
  const [commitError, setCommitError] = useState<string | null>(null);

  // The freshest draft, for dropping superseded async results.
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setDraft(asString(value));
    setCommitError(null);
  }, [value]);

  // Resolve this editor's node: its spec id drives the derive endpoint. Only a
  // spec with the dynamicInputs marker derives; anything else (a calc widget on
  // a static node, or no host mounted) degrades to a plain multiline commit.
  const graphNode = host && nodeId ? (host.graph.nodes.find((n) => n.id === nodeId) ?? null) : null;
  const spec = host && graphNode ? (host.specs[graphNode.type] ?? null) : null;
  const dynamic = spec?.dynamicInputs?.param === input.name;
  const specId = dynamic && graphNode ? graphNode.type : null;

  // -- debounced derive of the draft (D4: ~300ms, Python authoritative) ------
  useEffect(() => {
    if (!specId) return;
    const text = draft;
    const cached = cachedDerive(specId, text);
    if (cached) {
      setDerive({ value: text, outcome: cached });
      return;
    }
    const timer = window.setTimeout(() => {
      void deriveInputs(specId, text).then((outcome) => {
        if (draftRef.current !== text) return; // superseded by a later draft
        setDerive({ value: text, outcome });
      });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [draft, specId]);

  // -- live typeset preview (reuses the math widget's KaTeX approach) --------
  const previewSeq = useRef(0);
  useEffect(() => {
    const seq = ++previewSeq.current;
    const lines = calcLinesToPreview(draft);
    if (lines.length === 0) {
      setPreview([]);
      return;
    }
    void Promise.all(
      lines.map(async (line): Promise<RenderedLine> => {
        if (line.latex === null) return { html: escapeHtml(line.raw), fallback: true };
        const html = await renderKatex(line.latex);
        return html === null
          ? { html: escapeHtml(line.raw), fallback: true }
          : { html, fallback: false };
      }),
    ).then((rendered) => {
      if (seq !== previewSeq.current) return;
      setPreview(rendered);
    });
  }, [draft]);

  // -- symbol chips: current sockets vs the draft's pending set --------------
  const staticNames = useMemo(() => new Set((spec?.inputs ?? []).map((i) => i.name)), [spec]);
  const wiredSymbols = useMemo(() => {
    if (!host || !nodeId) return new Set<string>();
    const wired = new Set<string>();
    for (const edge of host.graph.edges) {
      if (edge.target === nodeId && !staticNames.has(edge.targetInput)) wired.add(edge.targetInput);
    }
    return wired;
  }, [host, nodeId, staticNames]);

  const currentNames = useMemo(() => {
    const entries = host && nodeId ? (host.derivedByNode.get(nodeId) ?? []) : [];
    // A wired symbol whose socket the committed equation no longer derives
    // (hand-edited source) still deserves a chip — it would be pruned too.
    const names = entries.map((e) => e.name);
    for (const name of wiredSymbols) if (!names.includes(name)) names.push(name);
    return names;
  }, [host, nodeId, wiredSymbols]);

  const draftFresh = derive !== null && derive.value === draft;
  const draftOutcome = draftFresh ? derive.outcome : null;
  const draftNames = draftOutcome?.ok ? draftOutcome.inputs.map((i) => i.name) : null;
  const deriveErrors: EngineErrorItem[] =
    draftOutcome && !draftOutcome.ok ? draftOutcome.errors : [];

  const chips = useMemo((): SymbolChip[] => {
    const shown = draftNames ?? currentNames;
    const out: SymbolChip[] = shown.map((name) => ({
      name,
      state: draftNames === null || currentNames.includes(name) ? 'kept' : 'added',
      wired: wiredSymbols.has(name),
    }));
    if (draftNames !== null) {
      for (const name of currentNames) {
        if (!draftNames.includes(name)) {
          out.push({ name, state: 'removed', wired: wiredSymbols.has(name) });
        }
      }
    }
    return out;
  }, [draftNames, currentNames, wiredSymbols]);

  // -- commit ---------------------------------------------------------------
  const commitDraft = async () => {
    const text = draft;
    if (text === committed) return;
    if (!host || !nodeId || !specId) {
      // No shell seam (e.g. isolated mount): plain literal commit, no pruning.
      onCommit(text);
      return;
    }
    // Ensure the derive verdict is for exactly this text (cache makes a repeat
    // call free); never commit a draft the server rejects.
    const outcome = await deriveInputs(specId, text);
    if (draftRef.current !== text) return;
    setDerive({ value: text, outcome });
    if (!outcome.ok) return; // the inline error is showing; nothing committed
    const names = outcome.inputs.map((i) => i.name);
    const literals: Record<string, number> = {};
    for (const name of names) {
      const raw = (newValues[name] ?? '').trim();
      if (raw === '') continue;
      const num = Number(raw);
      if (!Number.isFinite(num)) {
        setCommitError(`value for '${name}' is not a number`);
        return;
      }
      literals[name] = num;
    }
    setCommitError(null);
    const result = await host.commitEquation({
      nodeId,
      param: input.name,
      value: text,
      derivedNames: names,
      literals,
    });
    if (!result.ok) {
      setCommitError(result.message ?? 'could not save the equation');
    } else {
      setNewValues({});
    }
  };

  const placeholder =
    typeof config.placeholder === 'string' ? config.placeholder : 'name = expression';
  const deriving = specId !== null && !draftFresh;

  return (
    <div
      ref={containerRef}
      className="ge-widget-calc"
      // Commit when focus leaves the editor as a whole — moving between the
      // textarea and a chip's value field must not commit a half-built edit.
      onBlur={(event) => {
        const next = event.relatedTarget;
        if (next instanceof Node && containerRef.current?.contains(next)) return;
        void commitDraft();
      }}
      // On the container, not the textarea: applying with Cmd/Ctrl-Enter must
      // also work while focus is in an added symbol's value field.
      onKeyDown={(event) => {
        if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
          event.preventDefault();
          void commitDraft();
        }
      }}
    >
      <textarea
        className="ge-widget-input ge-calc-input"
        data-testid="widget-editor-calc-input"
        rows={Math.max(2, draft.split('\n').length)}
        value={draft}
        placeholder={placeholder}
        spellCheck={false}
        onChange={(event) => setDraft(event.target.value)}
      />

      {preview.length > 0 && (
        <div className="ge-calc-preview" data-testid="calc-preview">
          {preview.map((line, i) => (
            <div
              key={i}
              className={line.fallback ? 'ge-calc-preview__line ge-calc-preview__line--raw' : 'ge-calc-preview__line'}
              dangerouslySetInnerHTML={{ __html: line.html }}
            />
          ))}
        </div>
      )}

      {deriveErrors.length > 0 && (
        <div className="ge-calc-error" data-testid="calc-derive-error" role="alert">
          {deriveErrors.map((e, i) => (
            <div key={i}>{e.message}</div>
          ))}
        </div>
      )}

      {specId !== null && (
        <div className="ge-calc-sockets" data-testid="calc-sockets">
          <span className="ge-calc-sockets__label">
            sockets{deriving ? ' (deriving…)' : ''}
          </span>
          {chips.length === 0 && !deriving && (
            <span className="ge-calc-sockets__none">none — the equation has no free symbols</span>
          )}
          {chips.map((chip) => (
            <span
              key={chip.name}
              className={`ge-calc-chip ge-calc-chip--${chip.state}`}
              data-testid="calc-symbol-chip"
              data-symbol={chip.name}
              data-state={chip.state}
            >
              {chip.state === 'added' && (
                <span className="ge-calc-chip__mark" aria-hidden="true">
                  +
                </span>
              )}
              <span className="ge-calc-chip__name">{chip.name}</span>
              {chip.wired && chip.state !== 'removed' && (
                <span className="ge-calc-chip__wired">wired</span>
              )}
              {chip.state === 'removed' && (
                <span className="ge-calc-chip__note">
                  {chip.wired ? 'will unwire' : 'removed'}
                </span>
              )}
              {chip.state === 'added' && !chip.wired && (
                <input
                  className="ge-calc-chip__value"
                  data-testid="calc-symbol-value"
                  data-symbol={chip.name}
                  placeholder="value"
                  title={`Optional value for ${chip.name} (leave empty to wire it later — required until then)`}
                  value={newValues[chip.name] ?? ''}
                  onChange={(event) =>
                    setNewValues((prev) => ({ ...prev, [chip.name]: event.target.value }))
                  }
                />
              )}
            </span>
          ))}
        </div>
      )}

      {commitError && (
        <div className="ge-calc-error" data-testid="calc-commit-error" role="alert">
          {commitError}
        </div>
      )}

      <div className="ge-calc-hint">⌘/Ctrl+Enter or click away to apply — sockets update on apply</div>
    </div>
  );
}
