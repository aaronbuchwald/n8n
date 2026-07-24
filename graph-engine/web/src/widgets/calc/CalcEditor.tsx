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
// commit is the store's `commitEquation` action (8-S1 reconciliation — one
// mutation funnel, one single-flight write queue), which prunes edges into
// removed sockets in the same save and toasts what it unwired. A freshly-added
// symbol is required (amended #5) — the editor offers an optional inline value
// per added symbol; a rejected save surfaces the server's error inline and the
// module file stays untouched.
//
// The DRAFT preview (text, debounced derive verdict, KaTeX lines) is
// deliberately component-local: transient single-component UI state, never
// graph state — only the commit mutates the graph, through the store.

import { useEffect, useMemo, useRef, useState } from 'react';
import type { EngineErrorItem } from '../../api';
import { commitEquation } from '../../store/sync';
import { useSyncSelector } from '../../store/useSyncSelector';
import type { WidgetEditorProps } from '../registry';
import { cachedDerive, deriveInputs, type DeriveOutcome } from './derive';
import { CalcPreview } from './preview';
import './calc.css';

function asString(value: unknown): string {
  if (value === undefined || value === null) return '';
  return typeof value === 'string' ? value : String(value);
}

interface DeriveState {
  /** The draft text this outcome belongs to. */
  value: string;
  outcome: DeriveOutcome;
}

interface SymbolChip {
  name: string;
  state: 'kept' | 'added' | 'removed';
  wired: boolean;
}

const NO_WIRED: ReadonlySet<string> = new Set<string>();

export function CalcEditor({ value, config, input, onCommit, nodeId }: WidgetEditorProps) {
  // The store is the shell seam (was the CalcHost context): the effective
  // graph (authoritative ⊕ overlay), the palette, and the committed derived
  // sockets are all stored refs, safe under useSyncSelector.
  const graph = useSyncSelector((s) => s.effective.graph);
  const specs = useSyncSelector((s) => s.specs);
  const derivedByNode = useSyncSelector((s) => s.derivedByNode);

  const committed = asString(value);
  const [draft, setDraft] = useState(committed);
  const [derive, setDerive] = useState<DeriveState | null>(null);
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
  // a static node, or an editor mounted with no store hydrated) degrades to a
  // plain multiline commit.
  const graphNode = graph && nodeId ? (graph.nodes.find((n) => n.id === nodeId) ?? null) : null;
  const spec = graphNode ? (specs[graphNode.type] ?? null) : null;
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

  // -- symbol chips: current sockets vs the draft's pending set --------------
  const staticNames = useMemo(() => new Set((spec?.inputs ?? []).map((i) => i.name)), [spec]);
  const wiredSymbols = useMemo(() => {
    if (!graph || !nodeId) return NO_WIRED;
    const wired = new Set<string>();
    for (const edge of graph.edges) {
      if (edge.target === nodeId && !staticNames.has(edge.targetInput)) wired.add(edge.targetInput);
    }
    return wired;
  }, [graph, nodeId, staticNames]);

  const currentNames = useMemo(() => {
    const entries = nodeId ? (derivedByNode.get(nodeId) ?? []) : [];
    // A wired symbol whose socket the committed equation no longer derives
    // (hand-edited source) still deserves a chip — it would be pruned too.
    const names = entries.map((e) => e.name);
    for (const name of wiredSymbols) if (!names.includes(name)) names.push(name);
    return names;
  }, [derivedByNode, nodeId, wiredSymbols]);

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
    if (!nodeId || !specId) {
      // No dynamic seam (e.g. isolated mount, static node): plain literal
      // commit through the standard widget path, no pruning.
      onCommit(text);
      return;
    }
    // Ensure the derive verdict is for exactly this text (cache makes a repeat
    // call free); never commit a draft the server rejects.
    const outcome = await deriveInputs(specId, text);
    if (draftRef.current !== text) return;
    setDerive({ value: text, outcome });
    if (!outcome.ok) return; // the inline error is showing; nothing committed
    const literals: Record<string, number> = {};
    for (const entry of outcome.inputs) {
      const raw = (newValues[entry.name] ?? '').trim();
      if (raw === '') continue;
      const num = Number(raw);
      if (!Number.isFinite(num)) {
        setCommitError(`value for '${entry.name}' is not a number`);
        return;
      }
      literals[entry.name] = num;
    }
    setCommitError(null);
    const result = await commitEquation({
      nodeId,
      param: input.name,
      value: text,
      derivedInputs: outcome.inputs,
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

      <CalcPreview text={draft} />


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
