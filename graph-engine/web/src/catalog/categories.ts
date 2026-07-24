// ADR 0017 (node catalog) D2 — the capability taxonomy.
//
// A pure, frontend-only mapping from a node spec to one of five capability
// sections (plus an "Other" fallback), used by the NodeCatalog to group nodes
// by *what the user wants done* rather than by which Python module they came
// from. Deliberately NOT a node-declared field: category is presentation
// vocabulary, not execution semantics (FOR REVIEW 1) — the engine, spec schema
// and bijection are untouched. The resolution order still honours a future
// `spec.category` seam so the field can be promoted additively later with the
// frontend already listening.

/** The stable, kebab-case category ids (also the `data-category` attr values). */
export type CategoryId =
  | 'input-data'
  | 'table'
  | 'math'
  | 'logic'
  | 'render-output'
  | 'other';

export interface CategorySection {
  id: CategoryId;
  /** Human label shown in the section header. */
  label: string;
  /** Unicode glyph (no icon fonts — offline posture, ADR 0003/0014). */
  glyph: string;
}

// The five sections in PIPELINE order (the order data flows through a graph,
// which is also the order a user builds one), with the "Other" fallback last.
// Rendered top-to-bottom in exactly this order; "Other" only when non-empty.
export const CATEGORY_SECTIONS: readonly CategorySection[] = [
  { id: 'input-data', label: 'Input / Data', glyph: '⇥' },
  { id: 'table', label: 'Table', glyph: '▤' },
  { id: 'math', label: 'Math', glyph: '∑' },
  { id: 'logic', label: 'Logic', glyph: '⧉' },
  { id: 'render-output', label: 'Render / Output', glyph: '▣' },
  { id: 'other', label: 'Other', glyph: '·' },
];

const CATEGORY_IDS: ReadonlySet<string> = new Set(CATEGORY_SECTIONS.map((s) => s.id));

function isCategoryId(value: string): value is CategoryId {
  return CATEGORY_IDS.has(value);
}

// Exact-id assignments — the D2 table. Exact ids win over module defaults so a
// pack can carry mixed-capability nodes (calc's `render_summary` is
// Render/Output while the rest of calc is Math). Every `@node` currently in the
// repo is enumerated here.
export const CATEGORY_BY_ID: Readonly<Record<string, CategoryId>> = {
  // Input / Data — bringing values into the graph.
  'sources.read_csv': 'input-data',
  'sources.mock_api': 'input-data',
  'table.read_table': 'input-data', // read_table's capability is *bringing data in*
  'minimal.read_values': 'input-data',
  // Table — operating on tabular data you already have.
  'table.apply_recipe': 'table',
  // Math — compute.
  'calc.total': 'math',
  'calc.average': 'math',
  'calc.median': 'math',
  'calc.minimum': 'math',
  'calc.maximum': 'math',
  'sym.parse_expr': 'math',
  'sym.solve_for': 'math',
  'sym.substitute': 'math',
  'sym.evaluate_numeric': 'math',
  'sym.quantity': 'math',
  'sym.multiply': 'math',
  'sym.typeset_calc': 'math', // primary product is the computed results, not the typeset byproduct
  'sym.handcalc': 'math',
  'minimal.total': 'math',
  'minimal.average': 'math',
  // Logic — select, branch, judge.
  'sym.pick': 'logic',
  // Render / Output — produce a human-readable artifact.
  'sheet.calc_card': 'render-output', // evaluates a calc, but its product is the card
  'table.table_summary': 'render-output',
  'calc.render_summary': 'render-output',
  'sym.describe': 'render-output',
  'sym.latex_to_mathml': 'render-output',
  'sym.join_text': 'render-output',
  'sym.calc_notes': 'render-output',
  'sym.render_math_card': 'render-output',
  'showcase.dashboard': 'render-output',
  'minimal.render_summary': 'render-output',
};

// Pack defaults, applied when an exact id isn't mapped — so an unmapped node
// from a known pack still lands in the right place.
export const CATEGORY_BY_MODULE: Readonly<Record<string, CategoryId>> = {
  sources: 'input-data',
  table: 'table',
  calc: 'math',
  sym: 'math',
  sheet: 'render-output',
};

/** The minimum shape `categoryFor` needs — a subset of `NodeSpec`. */
export interface CategorizableSpec {
  id: string;
  module: string;
  // Forward-compat seam only: no spec declares this today (FOR REVIEW 1). If a
  // future engine serves it (schemas are additive-tolerant), it wins.
  category?: string | null;
}

/**
 * Resolve a spec's capability section in strict precedence order:
 *   1. `spec.category` (forward-compat seam — unset today)
 *   2. exact-id map (`CATEGORY_BY_ID`)
 *   3. module default (`CATEGORY_BY_MODULE`)
 *   4. `other` — notably freshly user-authored nodes, which therefore surface
 *      immediately in a visible section instead of being mis-filed.
 */
export function categoryFor(spec: CategorizableSpec): CategoryId {
  if (spec.category && isCategoryId(spec.category)) return spec.category;
  return CATEGORY_BY_ID[spec.id] ?? CATEGORY_BY_MODULE[spec.module] ?? 'other';
}
