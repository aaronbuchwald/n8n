// The recipe/table data model for the `table-recipe` editor (ADR 0005 C-D1).
//
// This module knows the SHAPE of recipe v1 and the wire table — never the
// semantics. Nothing here computes rows; the only "logic" is column-NAME
// propagation for the pickers (sanctioned UI metadata: which columns exist at
// each step), mirroring the schema of nodepacks/table/recipe.py one-to-one.

export type CellValue = string | number | boolean | null;

/** The wire table shape between table nodes: `{"columns": [...], "rows": [[...]]}`. */
export interface TableData {
  columns: string[];
  rows: CellValue[][];
}

export const AGG_FNS = ['sum', 'mean', 'median', 'min', 'max', 'count'] as const;
export type AggFn = (typeof AGG_FNS)[number];

export interface SelectOp {
  op: 'select';
  columns: string[];
}
export interface RenameOp {
  op: 'rename';
  columns: Record<string, string>;
}
export interface FilterOp {
  op: 'filter';
  expr: string;
}
export interface DeriveOp {
  op: 'derive';
  name: string;
  expr: string;
}
export interface SortOp {
  op: 'sort';
  by: string[];
  descending?: boolean;
}
export interface AggSpec {
  col: string;
  fn: AggFn;
  as: string;
}
export interface AggregateOp {
  op: 'aggregate';
  group_by: string[];
  aggs: AggSpec[];
}
export interface LimitOp {
  op: 'limit';
  n: number;
}

export type RecipeOp =
  | SelectOp
  | RenameOp
  | FilterOp
  | DeriveOp
  | SortOp
  | AggregateOp
  | LimitOp;

export type OpName = RecipeOp['op'];
export const OP_NAMES: OpName[] = ['select', 'rename', 'filter', 'derive', 'sort', 'aggregate', 'limit'];

export interface Recipe {
  version: 1;
  ops: RecipeOp[];
}

export const EMPTY_RECIPE: Recipe = { version: 1, ops: [] };

// ---- guards ----------------------------------------------------------------

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function isStringArray(v: unknown): v is string[] {
  return Array.isArray(v) && v.every((x) => typeof x === 'string');
}

function isCell(v: unknown): v is CellValue {
  return (
    v === null || typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean'
  );
}

/** True for a well-formed wire table (`{columns, rows}`, cells JSON scalars). */
export function isTableData(v: unknown): v is TableData {
  return (
    isRecord(v) &&
    isStringArray(v.columns) &&
    Array.isArray(v.rows) &&
    v.rows.every((row) => Array.isArray(row) && row.every(isCell))
  );
}

function isAggSpec(v: unknown): v is AggSpec {
  return (
    isRecord(v) &&
    typeof v.col === 'string' &&
    typeof v.as === 'string' &&
    (AGG_FNS as readonly string[]).includes(typeof v.fn === 'string' ? v.fn : '')
  );
}

function isOp(v: unknown): v is RecipeOp {
  if (!isRecord(v) || typeof v.op !== 'string') return false;
  switch (v.op) {
    case 'select':
      return isStringArray(v.columns);
    case 'rename':
      return isRecord(v.columns) && Object.values(v.columns).every((n) => typeof n === 'string');
    case 'filter':
      return typeof v.expr === 'string';
    case 'derive':
      return typeof v.name === 'string' && typeof v.expr === 'string';
    case 'sort':
      return isStringArray(v.by) && (v.descending === undefined || typeof v.descending === 'boolean');
    case 'aggregate':
      return isStringArray(v.group_by) && Array.isArray(v.aggs) && v.aggs.every(isAggSpec);
    case 'limit':
      return typeof v.n === 'number' && Number.isInteger(v.n) && v.n >= 0;
    default:
      return false;
  }
}

export type ParsedRecipe =
  | { kind: 'recipe'; recipe: Recipe }
  // Not a v1 recipe this editor understands (newer version, unknown op, or not
  // a recipe at all): degrade to raw-JSON display/editing (C-D5).
  | { kind: 'foreign'; value: unknown; reason: string };

/** Parse the widget literal into a v1 recipe, or classify it as foreign. */
export function parseRecipe(value: unknown): ParsedRecipe {
  if (value === undefined || value === null) return { kind: 'recipe', recipe: EMPTY_RECIPE };
  if (!isRecord(value)) {
    return { kind: 'foreign', value, reason: 'the bound value is not a recipe dict' };
  }
  if (value.version !== 1) {
    return {
      kind: 'foreign',
      value,
      reason: `recipe version ${JSON.stringify(value.version)} — this editor targets version 1`,
    };
  }
  const ops = value.ops;
  if (!Array.isArray(ops)) {
    return { kind: 'foreign', value, reason: "recipe 'ops' is not a list" };
  }
  const parsed: RecipeOp[] = [];
  for (const op of ops) {
    if (!isOp(op)) {
      const name = isRecord(op) && typeof op.op === 'string' ? op.op : JSON.stringify(op);
      return { kind: 'foreign', value, reason: `unrecognised op ${name}` };
    }
    parsed.push(op);
  }
  return { kind: 'recipe', recipe: { version: 1, ops: parsed } };
}

// ---- column-name propagation (pickers only — never data) -------------------

/**
 * The column NAMES available after applying `ops[0..count)` to `input` columns.
 * Null in → null out (unknown source; pickers degrade to free text). This
 * mirrors recipe.py's schema effects but touches no row data.
 */
export function columnsAfter(input: string[] | null, ops: RecipeOp[], count: number): string[] | null {
  if (input === null) return null;
  let cols = [...input];
  for (const op of ops.slice(0, count)) {
    switch (op.op) {
      case 'select':
        cols = [...op.columns];
        break;
      case 'rename':
        cols = cols.map((c) => op.columns[c] ?? c);
        break;
      case 'derive':
        if (!cols.includes(op.name) && op.name) cols = [...cols, op.name];
        break;
      case 'aggregate':
        cols = [...op.group_by, ...op.aggs.map((a) => a.as)];
        break;
      default:
        break; // filter / sort / limit keep the schema
    }
  }
  return cols;
}

// ---- presentation helpers --------------------------------------------------

interface OpMeta {
  label: string;
  hint: string;
  /** A fresh default op, seeded from the columns available at its position. */
  make: (columns: string[] | null) => RecipeOp;
}

export const OP_META: Record<OpName, OpMeta> = {
  select: {
    label: 'Select',
    hint: 'keep only some columns',
    make: (cols) => ({ op: 'select', columns: cols ? [...cols] : [] }),
  },
  rename: {
    label: 'Rename',
    hint: 'rename columns',
    make: () => ({ op: 'rename', columns: {} }),
  },
  filter: {
    label: 'Filter',
    hint: 'keep rows matching an expression',
    make: () => ({ op: 'filter', expr: '' }),
  },
  derive: {
    label: 'Derive',
    hint: 'add a computed column',
    make: () => ({ op: 'derive', name: '', expr: '' }),
  },
  sort: {
    label: 'Sort',
    hint: 'order rows by columns',
    make: (cols) => ({ op: 'sort', by: cols?.length ? [cols[0]] : [] }),
  },
  aggregate: {
    label: 'Aggregate',
    hint: 'group and reduce',
    make: (cols) => ({
      op: 'aggregate',
      group_by: [],
      aggs: cols?.length ? [{ col: cols[0], fn: 'sum', as: `${cols[0]}_sum` }] : [],
    }),
  },
  limit: {
    label: 'Limit',
    hint: 'keep the first N rows',
    make: () => ({ op: 'limit', n: 10 }),
  },
};

/** A one-line summary of an op for the collapsed step card. */
export function opSummary(op: RecipeOp): string {
  switch (op.op) {
    case 'select':
      return op.columns.length ? op.columns.join(', ') : 'no columns';
    case 'rename':
      return Object.entries(op.columns)
        .map(([from, to]) => `${from} → ${to}`)
        .join(', ') || 'no renames';
    case 'filter':
      return op.expr || 'no expression';
    case 'derive':
      return op.name || op.expr ? `${op.name || '?'} = ${op.expr || '?'}` : 'empty';
    case 'sort':
      return op.by.length ? `${op.by.join(', ')} ${op.descending ? '↓' : '↑'}` : 'no columns';
    case 'aggregate': {
      const aggs = op.aggs.map((a) => `${a.fn}(${a.col})`).join(', ') || 'no aggregations';
      return op.group_by.length ? `by ${op.group_by.join(', ')}: ${aggs}` : aggs;
    }
    case 'limit':
      return `first ${op.n} row${op.n === 1 ? '' : 's'}`;
  }
}
