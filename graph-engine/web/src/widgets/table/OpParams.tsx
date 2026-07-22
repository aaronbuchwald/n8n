// Inline parameter editors, one per recipe op (ADR 0005 C-D1 vocabulary).
// Pure form controls over the op dicts in model.ts — column pickers are fed
// the column NAMES available at the step's position (from the Python-run
// preview); expressions are plain text in the constrained grammar, validated
// authoritatively by Python at run (A-D5). Nothing here computes table data.

import { useEffect, useState } from 'react';
import {
  AGG_FNS,
  type AggFn,
  type AggregateOp,
  type DeriveOp,
  type FilterOp,
  type LimitOp,
  type RecipeOp,
  type RenameOp,
  type SelectOp,
  type SortOp,
} from './model';

interface OpEditorProps<O extends RecipeOp> {
  op: O;
  /** Columns available AT this step (null = unknown; pickers degrade to text). */
  columns: string[] | null;
  onChange: (next: O) => void;
}

// ---- shared controls -------------------------------------------------------

interface ColumnChipsProps {
  /** Known column names at this step (null = unknown source). */
  columns: string[] | null;
  /** The currently chosen names, in order (order is data for select/sort). */
  chosen: string[];
  onChange: (next: string[]) => void;
  label: string;
}

/**
 * Multi-select as toggle chips. Click order builds the list (order matters for
 * select/sort). Chosen names not present in the known set stay visible, marked
 * unknown, so a stale recipe is editable rather than broken.
 */
function ColumnChips({ columns, chosen, onChange, label }: ColumnChipsProps) {
  const known = columns ?? [];
  const unknownChosen = chosen.filter((c) => !known.includes(c));
  const all = [...known, ...unknownChosen];

  if (all.length === 0) {
    // No known columns and nothing chosen: free-text entry (comma-separated).
    return (
      <input
        className="tr-input"
        aria-label={label}
        placeholder="column, column, …"
        defaultValue={chosen.join(', ')}
        onBlur={(e) =>
          onChange(
            e.target.value
              .split(',')
              .map((s) => s.trim())
              .filter(Boolean),
          )
        }
      />
    );
  }

  return (
    <div className="tr-chips" role="group" aria-label={label}>
      {all.map((col) => {
        const active = chosen.includes(col);
        const unknown = !known.includes(col);
        return (
          <button
            key={col}
            type="button"
            className={`tr-chip${active ? ' tr-chip--on' : ''}${unknown ? ' tr-chip--unknown' : ''}`}
            title={unknown ? `${col} (not in the current table)` : col}
            aria-pressed={active}
            onClick={() =>
              onChange(active ? chosen.filter((c) => c !== col) : [...chosen, col])
            }
          >
            {col}
          </button>
        );
      })}
    </div>
  );
}

interface ColumnSelectProps {
  columns: string[] | null;
  value: string;
  onChange: (next: string) => void;
  label: string;
}

/** Single-column dropdown; an unknown current value stays selectable. */
function ColumnSelect({ columns, value, onChange, label }: ColumnSelectProps) {
  const known = columns ?? [];
  const options = known.includes(value) || !value ? known : [value, ...known];
  if (options.length === 0) {
    return (
      <input
        className="tr-input"
        aria-label={label}
        placeholder="column"
        defaultValue={value}
        onBlur={(e) => onChange(e.target.value.trim())}
      />
    );
  }
  return (
    <select
      className="tr-select"
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      {!value && <option value="">column…</option>}
      {options.map((col) => (
        <option key={col} value={col}>
          {known.includes(col) ? col : `${col} (unknown)`}
        </option>
      ))}
    </select>
  );
}

interface TextFieldProps {
  value: string;
  onChange: (next: string) => void;
  placeholder: string;
  label: string;
  mono?: boolean;
  grow?: boolean;
}

/** A controlled-ish text field that pushes changes up as you type. */
function TextField({ value, onChange, placeholder, label, mono, grow }: TextFieldProps) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  return (
    <input
      className={`tr-input${mono ? ' tr-input--mono' : ''}${grow ? ' tr-input--grow' : ''}`}
      aria-label={label}
      placeholder={placeholder}
      value={draft}
      onChange={(e) => {
        setDraft(e.target.value);
        onChange(e.target.value);
      }}
    />
  );
}

const EXPR_HINT = 'columns · + - * / % ** · == != < <= > >= · and or not · abs round min max';

// ---- per-op editors --------------------------------------------------------

function SelectParams({ op, columns, onChange }: OpEditorProps<SelectOp>) {
  return (
    <div className="tr-params">
      <span className="tr-params__label">keep</span>
      <ColumnChips
        columns={columns}
        chosen={op.columns}
        onChange={(next) => onChange({ ...op, columns: next })}
        label="columns to keep"
      />
    </div>
  );
}

function RenameParams({ op, columns, onChange }: OpEditorProps<RenameOp>) {
  const entries = Object.entries(op.columns);
  const setEntries = (next: Array<[string, string]>) =>
    onChange({ ...op, columns: Object.fromEntries(next) });
  return (
    <div className="tr-params tr-params--stack">
      {entries.map(([from, to], i) => (
        <div key={i} className="tr-row">
          <ColumnSelect
            columns={columns}
            value={from}
            onChange={(next) => setEntries(entries.map((e, j) => (j === i ? [next, e[1]] : e)))}
            label={`rename source ${i + 1}`}
          />
          <span className="tr-row__arrow">→</span>
          <TextField
            value={to}
            onChange={(next) => setEntries(entries.map((e, j) => (j === i ? [e[0], next] : e)))}
            placeholder="new name"
            label={`rename target ${i + 1}`}
            grow
          />
          <button
            type="button"
            className="tr-iconbtn"
            title="Remove rename"
            onClick={() => setEntries(entries.filter((_, j) => j !== i))}
          >
            ×
          </button>
        </div>
      ))}
      <button
        type="button"
        className="tr-minibtn"
        onClick={() => setEntries([...entries, ['', '']])}
      >
        + rename
      </button>
    </div>
  );
}

function FilterParams({ op, onChange }: OpEditorProps<FilterOp>) {
  return (
    <div className="tr-params tr-params--stack">
      <div className="tr-row">
        <span className="tr-params__label">where</span>
        <TextField
          value={op.expr}
          onChange={(next) => onChange({ ...op, expr: next })}
          placeholder="amount > 100 and region == 'north'"
          label="filter expression"
          mono
          grow
        />
      </div>
      <div className="tr-params__hint">{EXPR_HINT}</div>
    </div>
  );
}

function DeriveParams({ op, onChange }: OpEditorProps<DeriveOp>) {
  // Stacked rows: the rail is narrow and the expression needs the full width.
  return (
    <div className="tr-params tr-params--stack">
      <div className="tr-row">
        <span className="tr-params__label">name</span>
        <TextField
          value={op.name}
          onChange={(next) => onChange({ ...op, name: next })}
          placeholder="new_column"
          label="derived column name"
          mono
          grow
        />
      </div>
      <div className="tr-row">
        <span className="tr-params__label tr-params__label--eq">=</span>
        <TextField
          value={op.expr}
          onChange={(next) => onChange({ ...op, expr: next })}
          placeholder="round(amount * 1.2, 2)"
          label="derive expression"
          mono
          grow
        />
      </div>
      <div className="tr-params__hint">{EXPR_HINT}</div>
    </div>
  );
}

function SortParams({ op, columns, onChange }: OpEditorProps<SortOp>) {
  return (
    <div className="tr-params tr-params--stack">
      <div className="tr-row">
        <span className="tr-params__label">by</span>
        <ColumnChips
          columns={columns}
          chosen={op.by}
          onChange={(next) => onChange({ ...op, by: next })}
          label="sort columns"
        />
      </div>
      <label className="tr-check">
        <input
          type="checkbox"
          checked={op.descending === true}
          onChange={(e) =>
            onChange(
              // Keep the literal minimal: omit `descending` when it's the default.
              e.target.checked ? { ...op, descending: true } : { op: 'sort', by: op.by },
            )
          }
        />
        descending
      </label>
    </div>
  );
}

function AggregateParams({ op, columns, onChange }: OpEditorProps<AggregateOp>) {
  const setAgg = (i: number, next: Partial<AggregateOp['aggs'][number]>) =>
    onChange({ ...op, aggs: op.aggs.map((a, j) => (j === i ? { ...a, ...next } : a)) });
  return (
    <div className="tr-params tr-params--stack">
      <div className="tr-row">
        <span className="tr-params__label">group by</span>
        <ColumnChips
          columns={columns}
          chosen={op.group_by}
          onChange={(next) => onChange({ ...op, group_by: next })}
          label="group by columns"
        />
      </div>
      {op.aggs.map((agg, i) => (
        // Two lines per aggregation: fn(col) on top, output name below — the
        // rail is too narrow for all four controls on one line.
        <div key={i} className="tr-agg">
          <div className="tr-row">
            <select
              className="tr-select tr-select--fn"
              aria-label={`aggregation function ${i + 1}`}
              value={agg.fn}
              onChange={(e) => {
                const fn = e.target.value;
                if ((AGG_FNS as readonly string[]).includes(fn)) setAgg(i, { fn: fn as AggFn });
              }}
            >
              {AGG_FNS.map((fn) => (
                <option key={fn} value={fn}>
                  {fn}
                </option>
              ))}
            </select>
            <ColumnSelect
              columns={columns}
              value={agg.col}
              onChange={(next) => setAgg(i, { col: next })}
              label={`aggregation column ${i + 1}`}
            />
            <button
              type="button"
              className="tr-iconbtn tr-agg__remove"
              title="Remove aggregation"
              onClick={() => onChange({ ...op, aggs: op.aggs.filter((_, j) => j !== i) })}
            >
              ×
            </button>
          </div>
          <div className="tr-row">
            <span className="tr-row__arrow">as</span>
            <TextField
              value={agg.as}
              onChange={(next) => setAgg(i, { as: next })}
              placeholder="output name"
              label={`aggregation output ${i + 1}`}
              mono
              grow
            />
          </div>
        </div>
      ))}
      <button
        type="button"
        className="tr-minibtn"
        onClick={() => {
          const col = columns?.[0] ?? '';
          onChange({
            ...op,
            aggs: [...op.aggs, { col, fn: 'sum', as: col ? `${col}_sum` : '' }],
          });
        }}
      >
        + aggregation
      </button>
    </div>
  );
}

function LimitParams({ op, onChange }: OpEditorProps<LimitOp>) {
  return (
    <div className="tr-params">
      <span className="tr-params__label">first</span>
      <input
        className="tr-input tr-input--n"
        aria-label="row limit"
        type="number"
        min={0}
        step={1}
        value={op.n}
        onChange={(e) => {
          const n = Number(e.target.value);
          if (Number.isInteger(n) && n >= 0) onChange({ ...op, n });
        }}
      />
      <span className="tr-params__label">rows</span>
    </div>
  );
}

export interface OpParamsProps {
  op: RecipeOp;
  columns: string[] | null;
  onChange: (next: RecipeOp) => void;
}

/** Dispatch to the editor for `op.op` (exhaustive over the closed v1 vocab). */
export function OpParams({ op, columns, onChange }: OpParamsProps) {
  switch (op.op) {
    case 'select':
      return <SelectParams op={op} columns={columns} onChange={onChange} />;
    case 'rename':
      return <RenameParams op={op} columns={columns} onChange={onChange} />;
    case 'filter':
      return <FilterParams op={op} columns={columns} onChange={onChange} />;
    case 'derive':
      return <DeriveParams op={op} columns={columns} onChange={onChange} />;
    case 'sort':
      return <SortParams op={op} columns={columns} onChange={onChange} />;
    case 'aggregate':
      return <AggregateParams op={op} columns={columns} onChange={onChange} />;
    case 'limit':
      return <LimitParams op={op} columns={columns} onChange={onChange} />;
  }
}
