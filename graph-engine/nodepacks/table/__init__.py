"""``table`` — Excel-like tabular operations, pure stdlib (ADR 0005 Part C).

Three nodes:

* :func:`read_table` — CSV (path or inline text) -> ``{'columns', 'rows'}``.
* :func:`apply_recipe` — a versioned, closed op-list ("recipe") -> a new
  table. The recipe is a plain ``dict`` value (a widget UI for it is a later
  stream, C-ui — see ADR 0005 Part A/C); it is exactly what round-trips
  through the ADR 0004 composite as an ordinary dict literal.
* :func:`table_summary` — render a table as a small, self-contained HTML card
  (inline CSS, no CDN assets) — the same pattern as ``calc.render_summary``.

The op vocabulary, the ``filter``/``derive`` expression grammar, and the
interpreter structure are documented in :mod:`table.recipe` and
:mod:`table.expr`; :mod:`table.errors` defines the local :class:`UserError`
this pack raises for every bad-input case (unknown op/version/function/column,
unsafe expression syntax, malformed table/recipe shape).

Like every pack, each function here is an ordinary Python callable first and a
node second — ``@node`` only registers it by its ``module.qualname`` id
(``table.read_table``, ``table.apply_recipe``, ``table.table_summary``). Pure
standard library: no runtime dependency, in v1 or ever for this pack's own
code (a future ``polars`` backend, per ADR 0005 C-D3, would be a *second*
interpreter class living in :mod:`table.recipe`, not a change to this module).
"""

from __future__ import annotations

import csv
import html
import io

from engine import Widget, node

from .errors import UserError
from .recipe import StdlibInterpreter, interpret, validate_table_shape

_MAX_PREVIEW_ROWS = 20


def _parse_cell(cell: str) -> object:
    """Parse one CSV cell as ``float`` when possible, else keep it as ``str``."""
    try:
        return float(cell)
    except ValueError:
        return cell


@node
def read_table(path: str = "table.csv", text: str = "") -> dict:
    """Read a CSV into a table: ``{'columns': [...], 'rows': [[...]]}``.

    When ``text`` is non-empty it is parsed directly as CSV content (``path``
    is ignored); otherwise the file at ``path`` is read. Cells are parsed as
    ``float`` when possible, else kept as ``str`` (the per-cell rule
    ``sources.read_csv`` applies to one column, generalised here to every
    column). Column order follows the header row; every data row must have as
    many cells as there are columns.
    """
    if text:
        rows = list(csv.reader(io.StringIO(text)))
    else:
        with open(path, newline="", encoding="utf-8") as handle:
            rows = list(csv.reader(handle))

    if not rows:
        raise UserError("CSV has no header row")
    columns = rows[0]
    if not columns or any(not c for c in columns):
        raise UserError(f"CSV header row has empty column name(s): {columns}")
    if len(set(columns)) != len(columns):
        raise UserError(f"CSV header row has duplicate column name(s): {columns}")

    data_rows = []
    for i, row in enumerate(rows[1:], start=1):
        if len(row) != len(columns):
            raise UserError(f"CSV row {i} has {len(row)} cell(s), expected {len(columns)}")
        data_rows.append([_parse_cell(cell) for cell in row])

    return {"columns": columns, "rows": data_rows}


@node(widgets={"recipe": Widget("table-recipe")})
def apply_recipe(table: dict, recipe: dict = None) -> dict:
    """Apply a versioned op-list ``recipe`` to ``table``; returns a new table.

    ``recipe`` is ``{'version': 1, 'ops': [...]}`` (schema: :mod:`table.recipe`,
    ADR 0005 Part C). Ops run in order, each a pure table -> table step:
    ``select``, ``rename``, ``filter``, ``derive``, ``sort``, ``aggregate``
    (``group_by`` + ``aggs``), ``limit``. ``filter``/``derive`` expressions use
    the constrained grammar in :mod:`table.expr` (``ast``-whitelisted: column
    names, literals, arithmetic/comparison/boolean operators, and
    ``{abs, round, min, max}``). Unknown version, op, aggregate function, or
    column -> :class:`UserError` naming what v1 supports.
    """
    recipe = recipe if recipe is not None else {"version": 1, "ops": []}
    return interpret(table, recipe, interpreter=StdlibInterpreter())


def _fmt_cell(value: object) -> str:
    if isinstance(value, float):
        return html.escape(f"{value:g}")
    return html.escape(str(value))


@node
def table_summary(table: dict, title: str = "Table") -> str:
    """Render ``table`` as a small, self-contained HTML card (inline CSS).

    Shows the column headers and up to the first rows (with a "+N more
    row(s)" note when truncated), plus a row/column count line. ``title`` and
    every cell are HTML-escaped, so the card is safe to embed even when
    upstream data is untrusted — no external or CDN assets.
    """
    columns, rows = validate_table_shape(table)
    shown = rows[:_MAX_PREVIEW_ROWS]
    remaining = len(rows) - len(shown)

    head = "".join(
        f'<th style="text-align:left;padding:.25rem .5rem;'
        f'border-bottom:1px solid #ddd">{html.escape(c)}</th>'
        for c in columns
    )
    body = "".join(
        "<tr>"
        + "".join(
            f'<td style="padding:.25rem .5rem;border-bottom:1px solid #eee">{_fmt_cell(v)}</td>'
            for v in row
        )
        + "</tr>"
        for row in shown
    )
    note = (
        f'<p style="margin:.5rem 0 0;color:#666;font-size:.8rem">+{remaining} more row(s)</p>'
        if remaining > 0
        else ""
    )

    return (
        '<div style="font-family:system-ui,-apple-system,sans-serif;'
        "max-width:36rem;padding:1rem;border:1px solid #ddd;border-radius:8px;"
        'box-shadow:0 1px 3px rgba(0,0,0,.08)">'
        f'<h1 style="font-size:1rem;margin:0 0 .5rem">{html.escape(title)}</h1>'
        '<p style="margin:0 0 .5rem;color:#666;font-size:.8rem">'
        f"{len(rows)} row(s) &middot; {len(columns)} column(s)</p>"
        '<table style="border-collapse:collapse;width:100%;font-size:.85rem">'
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
        f"{note}"
        "</div>"
    )


NODES = [read_table, apply_recipe, table_summary]

__all__ = [
    "read_table",
    "apply_recipe",
    "table_summary",
    "NODES",
    "UserError",
]
