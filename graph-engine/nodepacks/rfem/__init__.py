"""``rfem`` — nodes that know the shape of an RFEM export.

``sources`` and ``table`` are deliberately generic: they read a file and hand
back a plain value, knowing nothing about what the numbers mean. This pack is
where the *RFEM-shaped* knowledge lives — that a "design loads, members,
start/end" export has a ``Stab``/``Knoten``/``x_m`` locator, that its fourth
column names the extremum type each row reports, that its force columns are in
kN. Keeping that here is what lets ``sources`` stay generic.

Two nodes, deliberately split::

    export.csv ─> read_extrema ──table──> governing_force ──record──> …

* :func:`read_extrema` — the export CSV as a table.
* :func:`governing_force` — the one row that governs, as a value-with-provenance
  record.

**Why two nodes and not one.** Reading the export and *choosing* a row are
different jobs with different lifetimes. The reading is fixed by the file
format; the selection is an engineering decision that will change — a different
component, a member filter, a per-support envelope. With the split, swapping
the selection is a new node on the same wire; fused, every such change would be
a rewrite of the reader too.

**The table shape is ``table``'s, not a second one.** :func:`read_extrema`
returns ``{'columns': [...], 'rows': [[...]]}`` and gets there by calling
:func:`table.read_table`, so the export lands in exactly the shape every
``table`` op already consumes — an inline ``table.apply_recipe`` between the
two nodes below needs no adapter. (It carries one extra key, ``source``; the
shape validator ignores unknown keys, and the provenance is worth more on the
wire than a bare pair of lists.)

Pure standard library.
"""

from __future__ import annotations

from pathlib import Path

from engine import UserError, node
from table import read_table

# The export's own column names, after `xlsx_to_csv.py` flattens the workbook's
# two-row German header into one. `Extremum` is named by the converter: the
# workbook leaves that column's header blank in BOTH header rows, even though it
# is the column that says which extremum each row reports.
MEMBER = "Stab"
NODE = "Knoten"
POSITION = "x_m"
EXTREMUM = "Extremum"
LOAD_CASE = "Lastfall"

# Extremum type -> the column carrying that component's force. Only the three
# force components are here because only they exist in the export: it has `N`,
# `Vy` and `Vz` columns and NO moment columns, despite reporting `MT`/`My`/`Mz`
# extremum rows (those rows carry the forces accompanying a moment extremum).
FORCE_COLUMNS = {"N": "N_kN", "Vy": "Vy_kN", "Vz": "Vz_kN"}

# The unit of every force column — the workbook's own header spans them with
# "Kräfte [kN]", and the converter carries it into the `_kN` column suffixes.
FORCE_UNIT = "kN"

REQUIRED_COLUMNS = (MEMBER, NODE, POSITION, EXTREMUM, LOAD_CASE, *FORCE_COLUMNS.values())


@node
def read_extrema(path: str = "export.csv") -> dict:
    """Read an RFEM member design-loads export into a table.

    ``path`` is the CSV produced from the workbook by the example's
    ``xlsx_to_csv.py``. Returns ``{'columns', 'rows', 'source'}`` — the
    ``table`` pack's shape (cells parsed as ``float`` where possible, else kept
    as ``str``) plus the export's file name, so a row selected downstream can
    still say which file it came from. Only the **name** is carried, not the
    full path: the record ends up in a written artifact, and a machine-specific
    absolute path there would be noise, not provenance.

    Raises :class:`engine.UserError` when the CSV is missing a column this pack
    needs — a generic CSV read would happily succeed and fail much later.
    """
    table = read_table(path=path)
    missing = [c for c in REQUIRED_COLUMNS if c not in table["columns"]]
    if missing:
        raise UserError(
            f"{path!r} is not an RFEM member extrema export: no column(s) "
            f"{', '.join(repr(c) for c in missing)}; it has: "
            f"{', '.join(repr(c) for c in table['columns'])}"
        )
    table["source"] = Path(path).name
    return table


def _cell(value: object) -> str:
    """A locator cell as text: ``10103.0`` -> ``'10103'``, ``6.15…`` -> ``'6.15'``.

    Only for the human-readable ``ref``. The record keeps every value exactly as
    read, so nothing downstream depends on this formatting.
    """
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


@node
def governing_force(table: dict, component: str = "Vz") -> dict:
    """The governing row of an RFEM export, as a value-with-provenance record.

    Two steps, in this order:

    1. **Filter** to the rows whose ``Extremum`` column equals ``component``.
    2. Of those, take the row with the largest **absolute** value in that
       component's force column.

    **Why the filter is not optional.** RFEM has already done the extremum
    search — an ``Extremum = Vz`` row *is* its answer for "the largest Vz here",
    per member end and load case. Taking its answer is the owner's explicit
    choice over re-deriving one from every row in the file. The other rows are
    not competing candidates at all: they carry the Vz that merely *accompanies*
    some other component's extremum. (On this particular file the two scans
    happen to return the same number. That is a coincidence of the data, not a
    reason to drop the filter — see the tests, which pin the filter on a table
    where the two answers differ.)

    The return is the ``{'value', 'unit', 'ref'}`` envelope ``sheet``'s calc
    nodes unwrap into a given's row, so the card cites where its number came
    from without anything in between having to know what a card wants:

    * ``value`` — the **magnitude**, ``|Vz|``. A support reaction's sign is a
      statement about direction in the model's axes; a bearing check consumes
      how much force presses on the support. The signed number is kept beside
      it as ``signed`` rather than thrown away.
    * ``unit`` — ``kN``, the export's own force unit.
    * ``ref`` — the source row: ``RFEM <member>/<node> @ <x> m · <load case>``.

    Everything else in the record (``component``, ``signed``, ``member``,
    ``node``, ``position``, ``load_case``, ``source``) is provenance the
    unwrapper ignores by design — a richer source is never a breaking change.
    """
    columns = table.get("columns") if isinstance(table, dict) else None
    rows = table.get("rows") if isinstance(table, dict) else None
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise UserError(
            "the 'table' input must be an RFEM extrema table (wire it from "
            f"rfem.read_extrema), got {type(table).__name__}"
        )
    if component not in FORCE_COLUMNS:
        raise UserError(
            f"unknown component {component!r}; this export carries forces only: "
            f"{', '.join(sorted(FORCE_COLUMNS))} (it has no moment columns, even "
            f"though it reports MT/My/Mz extremum rows)"
        )
    force_column = FORCE_COLUMNS[component]
    missing = [c for c in (EXTREMUM, force_column) if c not in columns]
    if missing:
        raise UserError(
            f"table has no column(s) {', '.join(repr(c) for c in missing)}; "
            f"it has: {', '.join(repr(c) for c in columns)}"
        )

    index = {name: i for i, name in enumerate(columns)}
    extremum_at = index[EXTREMUM]
    force_at = index[force_column]

    candidates = [row for row in rows if row[extremum_at] == component]
    if not candidates:
        seen = sorted({str(row[extremum_at]) for row in rows})
        raise UserError(
            f"no row has Extremum == {component!r}; the table reports: "
            f"{', '.join(seen) or '(nothing)'}"
        )

    def magnitude(row: list) -> float:
        value = row[force_at]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise UserError(
                f"column {force_column!r} holds {value!r} "
                f"({type(value).__name__}), which is not a force"
            )
        return abs(float(value))

    governing = max(candidates, key=magnitude)
    signed = float(governing[force_at])

    def at(name: str) -> object:
        return governing[index[name]] if name in index else None

    ref = (
        f"RFEM {_cell(at(MEMBER))}/{_cell(at(NODE))} "
        f"@ {_cell(at(POSITION))} m · {_cell(at(LOAD_CASE))}"
    )
    return {
        # The envelope `sheet._given` reads.
        "value": abs(signed),
        "unit": FORCE_UNIT,
        "ref": ref,
        # Provenance beside it — ignored by the unwrapper, read by humans.
        "component": component,
        "signed": signed,
        "member": at(MEMBER),
        "node": at(NODE),
        "position": at(POSITION),
        "load_case": at(LOAD_CASE),
        "source": table.get("source", ""),
    }


NODES = [read_extrema, governing_force]

__all__ = [
    "read_extrema",
    "governing_force",
    "FORCE_COLUMNS",
    "FORCE_UNIT",
    "REQUIRED_COLUMNS",
    "NODES",
]
