"""The recipe interpreter — a closed, versioned op-list over a table (C-D1/D3).

**Recipe schema v1** (the frozen, bijective surface — ADR 0005 Part C):

    {"version": 1, "ops": [{"op": <name>, ...op-specific keys...}, ...]}

**Table shape** between nodes: ``{"columns": [str, ...], "rows": [[cell, ...],
...]}`` — column-ordered, JSON-serialisable, each row a list of cells aligned
positionally to ``columns``.

**v1 op vocabulary (closed)** — one method per op on :class:`StdlibInterpreter`:

* ``select``    -- ``{"op": "select", "columns": [str, ...]}``
* ``rename``    -- ``{"op": "rename", "columns": {old: new, ...}}``
* ``filter``    -- ``{"op": "filter", "expr": str}``
* ``derive``    -- ``{"op": "derive", "name": str, "expr": str}``
* ``sort``      -- ``{"op": "sort", "by": [str, ...], "descending"?: bool}``
* ``aggregate`` -- ``{"op": "aggregate", "group_by": [str, ...],
  "aggs": [{"col": str, "fn": <sum|mean|median|min|max|count>, "as": str}]}``
* ``limit``     -- ``{"op": "limit", "n": int}``

Unknown ``version``, ``op``, or aggregate ``fn`` -> :class:`~table.errors.UserError`
naming exactly what v1 supports (C-D5) — no silent reinterpretation.

**Backend structure (C-D3):** the reference (and only, in v1) backend is
:class:`StdlibInterpreter` — pure ``list``/``dict`` + :mod:`statistics`, no
new dependency. :func:`interpret` dispatches each op by name via
``getattr(interpreter, op_name)`` against an ``interpreter=`` parameter (default
:class:`StdlibInterpreter`); a later ``polars`` backend is a second class
implementing the *same seven method names* over its own native representation
(e.g. converting ``{"columns", "rows"}`` <-> a ``pl.DataFrame`` at its
boundary) and is selected by passing it in — the recipe dict, the op
vocabulary, and the expression grammar are untouched by that swap.
"""

from __future__ import annotations

import statistics
from typing import Any, Callable

from .errors import UserError
from .expr import compile_expr

SUPPORTED_VERSION = 1

# The closed v1 op vocabulary, in the order errors should suggest them.
OPS: tuple[str, ...] = ("select", "rename", "filter", "derive", "sort", "aggregate", "limit")

_AGG_FUNCS: dict[str, Callable[[list], Any]] = {
    "sum": lambda values: sum(values),
    "mean": statistics.fmean,
    "median": statistics.median,
    "min": min,
    "max": max,
    "count": len,
}

Table = dict  # {"columns": list[str], "rows": list[list]} -- documented shape above
Record = dict  # one row as {column: value}, an internal convenience -- never the wire shape


def validate_table_shape(table: Any) -> tuple[list[str], list[list]]:
    """Check ``table`` matches ``{"columns", "rows"}`` and return them.

    Raises :class:`UserError` (not a bug class) since a malformed table is
    user/upstream input, exactly like a malformed recipe.
    """
    if not isinstance(table, dict) or "columns" not in table or "rows" not in table:
        raise UserError("table must be a dict with 'columns' and 'rows' keys")
    columns = table["columns"]
    rows = table["rows"]
    if not isinstance(columns, list) or not all(isinstance(c, str) for c in columns):
        raise UserError("table 'columns' must be a list of strings")
    if len(set(columns)) != len(columns):
        raise UserError(f"table 'columns' has duplicate name(s): {columns}")
    if not isinstance(rows, list) or not all(isinstance(r, list) for r in rows):
        raise UserError("table 'rows' must be a list of lists")
    bad = [i for i, r in enumerate(rows) if len(r) != len(columns)]
    if bad:
        raise UserError(f"table row(s) {bad[:5]} don't match {len(columns)} column(s)")
    return columns, rows


def _to_records(columns: list[str], rows: list[list]) -> list[Record]:
    return [dict(zip(columns, row)) for row in rows]


def _from_records(columns: list[str], records: list[Record]) -> Table:
    return {"columns": list(columns), "rows": [[r.get(c) for c in columns] for r in records]}


class StdlibInterpreter:
    """The v1 reference interpreter: pure stdlib, one method per op.

    Each method has the signature ``(columns, records, op) -> (columns,
    records)`` where ``records`` is ``list[dict[str, Any]]`` — an internal
    convenience derived from the wire table shape, never persisted and never
    part of the bijective surface (the recipe dict is).
    """

    def select(self, columns: list[str], records: list[Record], op: dict) -> tuple[list[str], list[Record]]:
        wanted = op.get("columns")
        if not isinstance(wanted, list) or not wanted or not all(isinstance(c, str) for c in wanted):
            raise UserError("select requires a non-empty list of column names in 'columns'")
        missing = [c for c in wanted if c not in columns]
        if missing:
            raise UserError(f"select: unknown column(s) {missing}; available: {columns}")
        return list(wanted), [{c: r[c] for c in wanted} for r in records]

    def rename(self, columns: list[str], records: list[Record], op: dict) -> tuple[list[str], list[Record]]:
        mapping = op.get("columns")
        if not isinstance(mapping, dict) or not mapping:
            raise UserError("rename requires a non-empty {old: new} mapping in 'columns'")
        missing = [c for c in mapping if c not in columns]
        if missing:
            raise UserError(f"rename: unknown column(s) {missing}; available: {columns}")
        untouched = [c for c in columns if c not in mapping]
        collisions = set(mapping.values()) & set(untouched)
        if collisions:
            raise UserError(f"rename: target name(s) {sorted(collisions)} collide with existing columns")
        new_columns = [mapping.get(c, c) for c in columns]
        new_records = [{mapping.get(c, c): v for c, v in r.items()} for r in records]
        return new_columns, new_records

    def filter(self, columns: list[str], records: list[Record], op: dict) -> tuple[list[str], list[Record]]:
        compiled = compile_expr(op.get("expr"), columns)
        return columns, [r for r in records if bool(compiled(r))]

    def derive(self, columns: list[str], records: list[Record], op: dict) -> tuple[list[str], list[Record]]:
        name = op.get("name")
        if not isinstance(name, str) or not name:
            raise UserError("derive requires a non-empty 'name'")
        compiled = compile_expr(op.get("expr"), columns)
        new_columns = columns if name in columns else [*columns, name]
        new_records = []
        for r in records:
            r = dict(r)
            r[name] = compiled(r)
            new_records.append(r)
        return new_columns, new_records

    def sort(self, columns: list[str], records: list[Record], op: dict) -> tuple[list[str], list[Record]]:
        by = op.get("by")
        if not isinstance(by, list) or not by or not all(isinstance(c, str) for c in by):
            raise UserError("sort requires a non-empty list of column names in 'by'")
        missing = [c for c in by if c not in columns]
        if missing:
            raise UserError(f"sort: unknown column(s) {missing}; available: {columns}")
        descending = op.get("descending", False)
        if not isinstance(descending, bool):
            raise UserError("sort: 'descending' must be a bool")
        try:
            ordered = sorted(records, key=lambda r: tuple(r[c] for c in by), reverse=descending)
        except TypeError as exc:
            raise UserError(f"sort: values in {by} aren't consistently comparable: {exc}") from exc
        return columns, ordered

    def aggregate(self, columns: list[str], records: list[Record], op: dict) -> tuple[list[str], list[Record]]:
        group_by = op.get("group_by", [])
        if not isinstance(group_by, list) or not all(isinstance(c, str) for c in group_by):
            raise UserError("aggregate requires 'group_by' to be a list of column names (possibly empty)")
        missing = [c for c in group_by if c not in columns]
        if missing:
            raise UserError(f"aggregate: unknown group_by column(s) {missing}; available: {columns}")
        aggs = op.get("aggs")
        if not isinstance(aggs, list) or not aggs:
            raise UserError("aggregate requires a non-empty 'aggs' list")
        for agg in aggs:
            if not isinstance(agg, dict):
                raise UserError(f"aggregate: each agg must be a dict, got {agg!r}")
            fn = agg.get("fn")
            if fn not in _AGG_FUNCS:
                raise UserError(f"aggregate: unknown fn {fn!r}; supported: {sorted(_AGG_FUNCS)}")
            col = agg.get("col")
            if col not in columns:
                raise UserError(f"aggregate: unknown column {col!r}; available: {columns}")
            if not isinstance(agg.get("as"), str) or not agg["as"]:
                raise UserError("aggregate: each agg needs a non-empty 'as' output name")

        groups: dict[tuple, list[Record]] = {}
        order: list[tuple] = []
        for r in records:
            key = tuple(r[c] for c in group_by)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(r)
        if not order and not group_by:
            # No group_by and no rows: still emit one aggregate row over an
            # empty group so aggregate([]) -> one row of empty-safe reductions
            # doesn't silently vanish -- but sum/count are defined on [], the
            # rest (mean/median/min/max) aren't, so surface that plainly.
            order = [()]
            groups[()] = []

        new_columns = [*group_by, *(agg["as"] for agg in aggs)]
        new_records = []
        for key in order:
            group = groups[key]
            row: Record = dict(zip(group_by, key))
            for agg in aggs:
                values = [g[agg["col"]] for g in group]
                fn = _AGG_FUNCS[agg["fn"]]
                try:
                    row[agg["as"]] = fn(values)
                except (statistics.StatisticsError, ValueError) as exc:
                    raise UserError(
                        f"aggregate: fn {agg['fn']!r} on column {agg['col']!r} failed "
                        f"for an empty group: {exc}"
                    ) from exc
            new_records.append(row)
        return new_columns, new_records

    def limit(self, columns: list[str], records: list[Record], op: dict) -> tuple[list[str], list[Record]]:
        n = op.get("n")
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            raise UserError("limit requires a non-negative integer 'n'")
        return columns, records[:n]


def interpret(table: Table, recipe: dict, *, interpreter: "StdlibInterpreter | None" = None) -> Table:
    """Apply ``recipe`` ({'version': 1, 'ops': [...]}) to ``table``.

    Runs each op in order against ``interpreter`` (default
    :class:`StdlibInterpreter`); returns a new table, never mutates the input.
    """
    interpreter = interpreter if interpreter is not None else StdlibInterpreter()

    if not isinstance(recipe, dict):
        raise UserError("recipe must be a dict: {'version': 1, 'ops': [...]}")
    version = recipe.get("version")
    if version != SUPPORTED_VERSION:
        raise UserError(
            f"unsupported recipe version {version!r}; this interpreter supports version {SUPPORTED_VERSION}"
        )
    ops = recipe.get("ops")
    if not isinstance(ops, list):
        raise UserError("recipe 'ops' must be a list")

    columns, rows = validate_table_shape(table)
    records = _to_records(columns, rows)

    for index, op in enumerate(ops):
        if not isinstance(op, dict) or "op" not in op:
            raise UserError(f"ops[{index}] must be a dict with an 'op' key")
        name = op["op"]
        if name not in OPS:
            raise UserError(f"unknown op {name!r} at ops[{index}]; supported ops: {list(OPS)}")
        method = getattr(interpreter, name)
        try:
            columns, records = method(columns, records, op)
        except UserError as exc:
            raise UserError(f"ops[{index}] ({name}): {exc}") from exc

    return _from_records(columns, records)
