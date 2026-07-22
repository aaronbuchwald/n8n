// The `table-recipe` widget editor (ADR 0005 Part C, stream C-ui).
//
// An Excel-like RECIPE editor: the left rail is the recipe — a reorderable
// list of op steps, each with an inline parameter editor — and the right pane
// is a read-only grid PREVIEW of the anchor node's input/result tables. The
// recipe dict is the product (the bijective literal, C-D1); the grid is only a
// view. Previews are computed exclusively by Python via `/api/run` (C-D4):
// this file contains no op semantics, only op SHAPES and column-name plumbing.
//
// Editing model: every structural edit updates local state immediately and
// commits the whole recipe via `onCommit` on a short debounce (each commit
// PUTs /api/graph through the shell — A-D5). The preview re-runs on the same
// debounce, patching the DRAFT recipe onto the live graph, so what you see is
// always the Python interpreter's answer to the recipe you are writing.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { WidgetEditorProps } from '../registry';
import {
  columnsAfter,
  OP_META,
  OP_NAMES,
  opSummary,
  parseRecipe,
  type Recipe,
  type RecipeOp,
  type TableData,
} from './model';
import { fetchPreview, type PreviewResult } from './preview';
import { OpParams } from './OpParams';
import { TableGrid } from './TableGrid';
import './table.css';

const COMMIT_DEBOUNCE_MS = 500;
const PREVIEW_DEBOUNCE_MS = 350;

type PreviewPane = 'result' | 'input';

interface PreviewState {
  status: 'loading' | 'ready' | 'unavailable';
  input: TableData | null;
  output: TableData | null;
  errors: string[];
  reason: string;
}

const INITIAL_PREVIEW: PreviewState = {
  status: 'loading',
  input: null,
  output: null,
  errors: [],
  reason: '',
};

function useDebounced(fn: () => void, delayMs: number, deps: unknown[]): void {
  useEffect(() => {
    const handle = window.setTimeout(fn, delayMs);
    return () => window.clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}

// ---- step list -------------------------------------------------------------

interface StepCardProps {
  op: RecipeOp;
  index: number;
  count: number;
  expanded: boolean;
  columns: string[] | null;
  onToggle: () => void;
  onChange: (next: RecipeOp) => void;
  onMove: (delta: -1 | 1) => void;
  onRemove: () => void;
}

function StepCard({
  op,
  index,
  count,
  expanded,
  columns,
  onToggle,
  onChange,
  onMove,
  onRemove,
}: StepCardProps) {
  return (
    <li className={`tr-step${expanded ? ' tr-step--open' : ''}`} data-testid="tr-step">
      <div className="tr-step__head">
        <button type="button" className="tr-step__toggle" onClick={onToggle}>
          <span className="tr-step__index">{index + 1}</span>
          <span className="tr-step__op">{OP_META[op.op].label}</span>
          <span className="tr-step__summary" title={opSummary(op)}>
            {opSummary(op)}
          </span>
        </button>
        <span className="tr-step__actions">
          <button
            type="button"
            className="tr-iconbtn"
            title="Move up"
            disabled={index === 0}
            onClick={() => onMove(-1)}
          >
            ↑
          </button>
          <button
            type="button"
            className="tr-iconbtn"
            title="Move down"
            disabled={index === count - 1}
            onClick={() => onMove(1)}
          >
            ↓
          </button>
          <button
            type="button"
            className="tr-iconbtn tr-iconbtn--danger"
            title="Remove step"
            onClick={onRemove}
          >
            ×
          </button>
        </span>
      </div>
      {expanded && (
        <div className="tr-step__body">
          <OpParams op={op} columns={columns} onChange={onChange} />
        </div>
      )}
    </li>
  );
}

interface AddStepProps {
  onAdd: (op: RecipeOp['op']) => void;
}

function AddStep({ onAdd }: AddStepProps) {
  const [open, setOpen] = useState(false);
  return (
    <div className="tr-add">
      <button
        type="button"
        className="tr-add__btn"
        data-testid="tr-add-step"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        + Add step
      </button>
      {open && (
        <div className="tr-add__menu" role="menu">
          {OP_NAMES.map((name) => (
            <button
              key={name}
              type="button"
              role="menuitem"
              className="tr-add__item"
              onClick={() => {
                setOpen(false);
                onAdd(name);
              }}
            >
              <span className="tr-add__label">{OP_META[name].label}</span>
              <span className="tr-add__hint">{OP_META[name].hint}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ---- foreign / unrecognised recipes (C-D5 degrade path) --------------------

interface ForeignRecipeProps {
  value: unknown;
  reason: string;
  onCommit: (next: unknown) => void;
}

function ForeignRecipe({ value, reason, onCommit }: ForeignRecipeProps) {
  const [draft, setDraft] = useState(() => JSON.stringify(value, null, 2));
  const [parseError, setParseError] = useState<string | null>(null);
  return (
    <div className="tr-editor" data-testid="table-recipe-editor">
      <div className="tr-head">
        <span className="tr-head__title">Table recipe</span>
        <span className="tr-tag tr-tag--warn">unrecognised</span>
      </div>
      <div className="tr-foreign">
        <p className="tr-foreign__note">
          This value isn&apos;t a v1 recipe this editor can edit ({reason}). Edit the raw JSON
          below; Python remains the authority on what it means.
        </p>
        <textarea
          className="tr-foreign__json"
          aria-label="raw recipe JSON"
          value={draft}
          rows={10}
          spellCheck={false}
          onChange={(e) => setDraft(e.target.value)}
        />
        {parseError && <div className="tr-errors">{parseError}</div>}
        <div className="tr-foreign__actions">
          <button
            type="button"
            className="tr-minibtn"
            onClick={() => {
              try {
                onCommit(JSON.parse(draft));
                setParseError(null);
              } catch (error) {
                setParseError(error instanceof Error ? error.message : String(error));
              }
            }}
          >
            Apply JSON
          </button>
          <button
            type="button"
            className="tr-minibtn"
            onClick={() => onCommit({ version: 1, ops: [] })}
          >
            Reset to empty v1 recipe
          </button>
        </div>
      </div>
    </div>
  );
}

// ---- the editor ------------------------------------------------------------

export default function TableRecipeEditor({ value, input, onCommit }: WidgetEditorProps) {
  const parsed = useMemo(() => parseRecipe(value), [value]);

  if (parsed.kind === 'foreign') {
    return <ForeignRecipe value={parsed.value} reason={parsed.reason} onCommit={onCommit} />;
  }
  return (
    <RecipeEditor initial={parsed.recipe} boundValue={value} param={input.name} onCommit={onCommit} />
  );
}

interface RecipeEditorProps {
  initial: Recipe;
  /** The literal currently bound in the graph (anchors the preview node match). */
  boundValue: unknown;
  param: string;
  onCommit: (next: unknown) => void;
}

function RecipeEditor({ initial, boundValue, param, onCommit }: RecipeEditorProps) {
  const [recipe, setRecipe] = useState<Recipe>(initial);
  const [expanded, setExpanded] = useState<number | null>(
    initial.ops.length > 0 ? 0 : null,
  );
  const [pane, setPane] = useState<PreviewPane>('result');
  const [preview, setPreview] = useState<PreviewState>(INITIAL_PREVIEW);
  // Keep the last good result rendered (dimmed) while a broken draft shows its
  // Python error, so the user never loses visual context mid-edit.
  const lastGoodOutput = useRef<TableData | null>(null);
  const committed = useRef<Recipe>(initial);
  const dirty = useRef(false);

  // External resync: if the bound value changes underneath (another editor,
  // a server round-trip) and we have no local edits in flight, adopt it.
  useEffect(() => {
    if (!dirty.current && JSON.stringify(initial) !== JSON.stringify(recipe)) {
      setRecipe(initial);
      committed.current = initial;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial]);

  const update = useCallback((next: Recipe) => {
    dirty.current = true;
    setRecipe(next);
  }, []);

  // Debounced commit of every edit (A-D5: each commit rides PUT /api/graph).
  useDebounced(
    () => {
      if (dirty.current && JSON.stringify(recipe) !== JSON.stringify(committed.current)) {
        committed.current = recipe;
        dirty.current = false;
        onCommit(recipe);
      }
    },
    COMMIT_DEBOUNCE_MS,
    [recipe],
  );

  // Debounced Python preview of the DRAFT recipe (C-D4: the grid never
  // computes; /api/run is side-effect-free, commits go through onCommit only).
  // `previewSeq` drops out-of-order responses from superseded drafts.
  const previewSeq = useRef(0);
  useDebounced(
    () => {
      const seq = ++previewSeq.current;
      setPreview((p) => ({ ...p, status: 'loading' }));
      void fetchPreview(param, boundValue, recipe).then((result: PreviewResult) => {
        if (seq !== previewSeq.current) return;
        if (result.kind === 'unavailable') {
          setPreview({ ...INITIAL_PREVIEW, status: 'unavailable', reason: result.reason });
          return;
        }
        const { input: inputTable, output, errors, nodeId } = result.tables;
        if (output) lastGoodOutput.current = output;
        setPreview({
          status: 'ready',
          input: inputTable,
          output,
          // The anchor node's own errors read as this editor's errors — no
          // node-id prefix; other nodes' failures keep theirs for context.
          errors: errors.map((e) =>
            e.nodeId && e.nodeId !== nodeId ? `${e.nodeId}: ${e.message}` : e.message,
          ),
          reason: '',
        });
      });
    },
    PREVIEW_DEBOUNCE_MS,
    [recipe, param, boundValue],
  );

  const ops = recipe.ops;
  const inputColumns = preview.input?.columns ?? null;

  const setOps = (nextOps: RecipeOp[]) => update({ version: 1, ops: nextOps });

  const addStep = (name: RecipeOp['op']) => {
    const cols = columnsAfter(inputColumns, ops, ops.length);
    setOps([...ops, OP_META[name].make(cols)]);
    setExpanded(ops.length);
  };

  const moveStep = (index: number, delta: -1 | 1) => {
    const next = [...ops];
    const [op] = next.splice(index, 1);
    next.splice(index + delta, 0, op);
    setOps(next);
    setExpanded(index + delta);
  };

  const removeStep = (index: number) => {
    setOps(ops.filter((_, i) => i !== index));
    setExpanded((e) => (e === null || e === index ? null : e > index ? e - 1 : e));
  };

  const shownTable =
    pane === 'input' ? preview.input : (preview.output ?? lastGoodOutput.current);
  const stale = pane === 'result' && !preview.output && lastGoodOutput.current !== null;

  const paneCount = (table: TableData | null): string =>
    table ? `${table.rows.length}×${table.columns.length}` : '';

  return (
    <div className="tr-editor nodrag nowheel nopan" data-testid="table-recipe-editor">
      <div className="tr-head">
        <span className="tr-head__title">Table recipe</span>
        <span className="tr-tag">v1</span>
        <span className="tr-head__sub">
          {ops.length} step{ops.length === 1 ? '' : 's'}
        </span>
      </div>

      <div className="tr-body">
        <div className="tr-steps">
          {ops.length === 0 && (
            <div className="tr-steps__empty">
              No steps yet — the table passes through unchanged. Add a step to start
              transforming it.
            </div>
          )}
          <ol className="tr-steps__list">
            {ops.map((op, i) => (
              <StepCard
                // Index keys: steps have no identity beyond position (the recipe
                // is an ordered list) and reorders re-render the short list fully.
                key={i}
                op={op}
                index={i}
                count={ops.length}
                expanded={expanded === i}
                columns={columnsAfter(inputColumns, ops, i)}
                onToggle={() => setExpanded((e) => (e === i ? null : i))}
                onChange={(next) => setOps(ops.map((o, j) => (j === i ? next : o)))}
                onMove={(delta) => moveStep(i, delta)}
                onRemove={() => removeStep(i)}
              />
            ))}
          </ol>
          <AddStep onAdd={addStep} />
        </div>

        <div className="tr-preview">
          <div className="tr-preview__bar">
            <div className="tr-preview__tabs" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={pane === 'result'}
                className={`tr-preview__tab${pane === 'result' ? ' tr-preview__tab--on' : ''}`}
                onClick={() => setPane('result')}
              >
                Result{preview.output ? ` · ${paneCount(preview.output)}` : ''}
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={pane === 'input'}
                className={`tr-preview__tab${pane === 'input' ? ' tr-preview__tab--on' : ''}`}
                onClick={() => setPane('input')}
              >
                Input{preview.input ? ` · ${paneCount(preview.input)}` : ''}
              </button>
            </div>
            {preview.status === 'loading' && <span className="tr-preview__spin" aria-label="loading" />}
          </div>

          {preview.errors.length > 0 && (
            <div className="tr-errors" data-testid="tr-errors">
              {preview.errors.map((message, i) => (
                <div key={i} className="tr-errors__item">
                  {message}
                </div>
              ))}
            </div>
          )}

          {shownTable ? (
            <div className={`tr-preview__grid${stale ? ' tr-preview__grid--stale' : ''}`}>
              <TableGrid table={shownTable} />
            </div>
          ) : (
            <div className="tr-preview__empty" data-testid="tr-preview-empty">
              <span className="tr-preview__empty-title">
                {preview.status === 'ready' && preview.errors.length > 0
                  ? 'No result'
                  : 'Run to preview'}
              </span>
              <span className="tr-preview__empty-note">
                {preview.status === 'ready' && preview.errors.length > 0
                  ? 'The recipe failed — see the error above.'
                  : preview.status === 'unavailable' && preview.reason
                    ? preview.reason
                    : 'No table output for this node yet.'}
              </span>
            </div>
          )}

          <div className="tr-preview__foot">preview computed in Python · /api/run</div>
        </div>
      </div>
    </div>
  );
}
