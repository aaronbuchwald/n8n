"""Capacity check — two CSV arcs meeting at a "does it hold up?" verdict.

* **Arc 1** — read ``forces.csv`` (``name,force``), select the row with the
  **highest** force.
* **Arc 2** — read ``members.csv`` (``name,capacity``), select the member with
  the **lowest** capacity.
* **Combine** — the highest force and lowest capacity feed two independent
  consumers:

  * ``sym.typeset_calc`` (handcalcs) typesets ``margin = C_min - F_max`` with
    the numbers substituted — a **display** concern, values only.
  * :func:`check_capacity` asserts ``force < capacity`` and builds a PASS/FAIL
    verdict — a separate **logic** concern. It does *not* go through SymPy:
    feeding concrete numbers into a symbolic inequality (``Lt(120, 210)``)
    would auto-collapse to ``True`` and lose the "120 < 210" itself, so the
    comparison string is built as plain Python text instead.

    forces.csv  ─> read_table ─> select_extreme(max, "force")    ──┐
                                                                    ├─> pack_values ─> typeset_calc ─> latex_to_mathml ─┐
    members.csv ─> read_table ─> select_extreme(min, "capacity") ──┘                                                   │
                              │                                                                                        │
                              └────────────────────────────────────> check_capacity ────────────┐                     │
                                                                                                  ├─> join_text ─> render_math_card
                              describe(F_max) ──────────────────────────────────────────────────┘

Simple, generic mock data only — no real engineering formulas, just a
highest-vs-lowest comparison.

Run (the ``sym`` extra provides handcalcs/SymPy/latex2mathml)::

    uv run --extra sym python examples/capacity_check/capacity_check.py
"""

from __future__ import annotations

from pathlib import Path

from engine import UserError, main, node
from sym import describe, join_text, latex_to_mathml, render_math_card, typeset_calc
from table import read_table

HERE = Path(__file__).resolve().parent
FORCES_CSV = HERE / "forces.csv"
MEMBERS_CSV = HERE / "members.csv"

# What the graph needs to run — the ADR 0003 declarative descriptor. Versions
# match the `sym` extra in pyproject.toml.
DEPENDENCIES = [
    {"name": "sympy", "version": "1.14.*"},
    {"name": "handcalcs", "version": "1.11.*"},
    {"name": "forallpeople", "version": "2.7.*"},
    {"name": "latex2mathml", "version": "3.81.*"},
]


# -- example-local nodes -----------------------------------------------------


@node(outputs=["name", "value"])
def select_extreme(table: dict, column: str, mode: str = "max") -> dict:
    """Pick the row with the highest/lowest ``column``; return its name + value.

    ``mode`` is ``"max"`` or ``"min"``. Assumes the table has a ``name``
    column to label the selected row with.
    """
    if mode not in ("max", "min"):
        raise UserError(f"mode must be 'max' or 'min', got {mode!r}")
    columns, rows = table["columns"], table["rows"]
    if "name" not in columns or column not in columns:
        raise UserError(f"table must have 'name' and {column!r} columns, got {columns}")
    if not rows:
        raise UserError("table has no rows to select from")

    name_idx, col_idx = columns.index("name"), columns.index(column)
    picker = max if mode == "max" else min
    best = picker(rows, key=lambda row: row[col_idx])
    return {"name": best[name_idx], "value": best[col_idx]}


@node
def pack_values(force: float, capacity: float) -> dict:
    """Bundle the two extremes into handcalcs' ``{symbol: number}`` map.

    Kept as its own node (rather than a literal dict built inline) because a
    composite's tracer only wires *top-level* node arguments — a NodeHandle
    buried inside a hand-written dict literal would not become an edge.
    """
    return {"F_max": force, "C_min": capacity}


@node(outputs=["ok", "text"])
def check_capacity(force: float, capacity: float) -> dict:
    """Check ``force < capacity``; return a plain-text PASS/FAIL verdict.

    Deliberately plain Python, not SymPy: substituting concrete numbers into
    a symbolic ``Lt`` collapses straight to ``True``/``False`` and the
    "120 < 210" comparison itself never renders. Building the string by hand
    keeps both the numbers and the comparison visible.
    """
    ok = force < capacity
    op = "<" if ok else "≥"  # actual relation, not the one we hoped for
    verdict = "PASS" if ok else "FAIL"
    return {"ok": ok, "text": f"{verdict} — {force:g} {op} {capacity:g}"}


# All node types this example defines (for schema snapshots / registries).
NODES = [select_extreme, pack_values, check_capacity]


# -- the graph, as ordinary Python (ADR 0004 straight-line form) -------------


@main
def capacity_check_report(
    forces_path: str = "forces.csv", members_path: str = "members.csv"
) -> str:
    """Read both CSVs, pick the extremes, typeset the margin, and check it."""
    forces = read_table(path=forces_path)
    members = read_table(path=members_path)

    max_force = select_extreme(forces, column="force", mode="max")
    min_capacity = select_extreme(members, column="capacity", mode="min")

    # Display concern: handcalcs typesets the substituted numbers.
    values = pack_values(force=max_force.value, capacity=min_capacity.value)
    steps = typeset_calc(lines="margin = C_min - F_max", values=values)
    mathml = latex_to_mathml(steps.latex)

    # Logic concern: a separate node decides PASS/FAIL.
    verdict = check_capacity(force=max_force.value, capacity=min_capacity.value)

    # Straight-line form (ADR 0004 D7): each call is its own assignment — no
    # nested calls in arguments — so the composite round-trips through the
    # graph⟷source bijection and can be served + edited in the UI.
    f_note = describe(max_force.value, label="F_max")
    c_note = describe(min_capacity.value, label="C_min")
    caption = join_text(f_note, c_note, verdict.text)
    report = render_math_card(title="Capacity check", mathml=mathml, caption=caption)
    return report


def build_graph(forces_csv: Path | str = FORCES_CSV, members_csv: Path | str = MEMBERS_CSV):
    """Trace the composite into a Graph (absolute CSV paths so it runs anywhere)."""
    graph = capacity_check_report.to_graph(
        forces_path=str(forces_csv), members_path=str(members_csv)
    )
    graph.environment = {
        "dependencies": DEPENDENCIES,
        "mounts": [],
        "network": "none",
    }
    return graph


def main_cli() -> None:
    from engine import run, to_python

    graph = build_graph()
    out = graph.output
    print(run(graph).value(out["node"], out["socket"]))
    print("\n----- to_python(graph) -----")
    print(to_python(graph))


if __name__ == "__main__":
    main_cli()
