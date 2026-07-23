// The table-recipe read-only card preview (ADR 0013 D2/D7): a compact inline
// summary — `recipe · N steps` with the op names in applied order
// (`filter → derive → aggregate`), read straight from the committed recipe
// literal. A malformed/foreign value degrades to a plain value chip. Inline
// placement; no grid, no Python round-trip (the editor owns the live preview).

import type { WidgetPreviewProps } from '../registry';
import { parseRecipe } from './model';
import './table.css';

function chipText(count: number, chain: string): string {
  const steps = `recipe · ${count} step${count === 1 ? '' : 's'}`;
  return chain ? `${steps} · ${chain}` : steps;
}

export default function RecipeCardPreview({ value }: WidgetPreviewProps) {
  const parsed = parseRecipe(value);
  if (parsed.kind === 'foreign') {
    // Not a v1 recipe this shell understands: show the raw value, honestly.
    const raw = typeof value === 'string' ? value : JSON.stringify(value) ?? String(value);
    return (
      <span className="ge-socket__state ge-socket__state--value ge-recipe-preview" data-testid="recipe-preview" title={raw}>
        {raw}
      </span>
    );
  }
  const ops = parsed.recipe.ops;
  const chain = ops.map((op) => op.op).join(' → ');
  const text = chipText(ops.length, chain);
  return (
    <span className="ge-socket__state ge-socket__state--value ge-recipe-preview" data-testid="recipe-preview" title={text}>
      {text}
    </span>
  );
}
