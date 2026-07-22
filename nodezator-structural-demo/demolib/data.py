"""Data nodes: read a CSV with named columns, pick a row, unpack it.

Each public function here becomes one Nodezator node. The signatures are
deliberately simple (str / int / dict) so the app renders clean input widgets
from the type hints + defaults.

Do NOT add ``from __future__ import annotations`` to this module: Nodezator
reads ``unpack_member``'s return annotation as a *real* Python object (a list
of dicts describing the output sockets). The future import would turn it into
a string and break multi-output detection.
"""

import csv
from pathlib import Path

# The numeric columns we coerce to float on read. Everything else stays a str.
_NUMERIC_COLUMNS = ("force_kN", "width_mm", "thickness_mm", "fy_MPa")


def read_members_csv(path: str = "members.csv") -> list:
    """Read a CSV with named columns into a list of row dicts.

    The header row supplies the column names; every data row becomes a dict
    keyed by those names. Numeric columns are coerced to ``float`` so the
    downstream math nodes receive numbers, not strings.
    """
    csv_path = Path(path)
    rows = []

    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)  # named columns come from the header row
        for raw in reader:
            row = dict(raw)
            for column in _NUMERIC_COLUMNS:
                if column in row and row[column] not in (None, ""):
                    row[column] = float(row[column])
            rows.append(row)

    return rows


def select_member(rows: list, index: int = 0) -> dict:
    """Select a single row from the list produced by ``read_members_csv``.

    ``index`` is clamped into range so an out-of-bounds widget value can never
    crash the graph — it just picks the nearest valid row.
    """
    if not rows:
        raise ValueError("no rows to select from — did read_members_csv find the file?")

    clamped = max(0, min(index, len(rows) - 1))
    return dict(rows[clamped])


# A list-of-dicts return annotation tells Nodezator this node has MULTIPLE named
# output sockets. The function then returns a dict keyed by those same names.
def unpack_member(
    member: dict,
) -> [
    {"name": "name"},
    {"name": "force_kN"},
    {"name": "width_mm"},
    {"name": "thickness_mm"},
    {"name": "fy_MPa"},
]:
    """Explode one member row into individual scalar output sockets.

    This turns a single dict socket into five clean scalar sockets, so the math
    nodes downstream can each take a plain ``float`` (and render a numeric
    widget when left unconnected).
    """
    return {
        "name": str(member["name"]),
        "force_kN": float(member["force_kN"]),
        "width_mm": float(member["width_mm"]),
        "thickness_mm": float(member["thickness_mm"]),
        "fy_MPa": float(member["fy_MPa"]),
    }
