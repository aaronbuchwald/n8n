// A minimal custom read-only grid (ADR 0005 C-D4 / open confirmation 6).
// Renders a `{columns, rows}` table it was HANDED — header row + scrollable
// body, overflow-safe cells. It owns zero computation and zero editing
// semantics; every cell value was produced by Python via /api/run.

import type { CellValue, TableData } from './model';

const MAX_RENDERED_ROWS = 100;

/** Compact display for a cell, matching Python's `%g`-ish float rendering. */
function formatCell(value: CellValue): string {
  if (value === null) return '';
  if (typeof value === 'number') {
    if (Number.isInteger(value)) return String(value);
    const compact = Number(value.toPrecision(6));
    return String(compact);
  }
  return String(value);
}

interface TableGridProps {
  table: TableData;
}

export function TableGrid({ table }: TableGridProps) {
  const shown = table.rows.slice(0, MAX_RENDERED_ROWS);
  const remaining = table.rows.length - shown.length;
  const numeric = table.columns.map((_, i) =>
    shown.length > 0 && shown.every((row) => typeof row[i] === 'number' || row[i] === null),
  );

  return (
    <div className="tr-grid" data-testid="tr-grid">
      <div className="tr-grid__scroll">
        <table className="tr-grid__table">
          <thead>
            <tr>
              <th className="tr-grid__index-head" aria-label="row number" />
              {table.columns.map((col) => (
                <th key={col} className="tr-grid__head" title={col}>
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((row, r) => (
              // Row order is part of the data (sort/limit); index keys are safe
              // because the grid is read-only and fully re-rendered per table.
              <tr key={r}>
                <td className="tr-grid__index">{r + 1}</td>
                {row.map((cell, c) => {
                  const text = formatCell(cell);
                  return (
                    <td
                      key={c}
                      className={`tr-grid__cell${numeric[c] ? ' tr-grid__cell--num' : ''}${
                        cell === null ? ' tr-grid__cell--null' : ''
                      }`}
                      title={text}
                    >
                      {cell === null ? '∅' : text}
                    </td>
                  );
                })}
              </tr>
            ))}
            {shown.length === 0 && (
              <tr>
                <td className="tr-grid__empty" colSpan={table.columns.length + 1}>
                  no rows
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {remaining > 0 && <div className="tr-grid__more">+{remaining} more row(s)</div>}
    </div>
  );
}
