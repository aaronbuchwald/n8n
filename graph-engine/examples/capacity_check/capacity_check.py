"""Capacity check — two CSV arcs meeting at a "does it hold up?" verdict.

* **Arc 1** — read ``forces.csv`` (``name,force``), select the row with the
  **highest** force.
* **Arc 2** — read ``members.csv`` (``name,capacity``), select the member with
  the **lowest** capacity.
* **Combine** — the highest force and lowest capacity feed a single
  ``sym.handcalc`` node whose ``lines`` field holds **both** the equation and
  the assertion that judges it (ADR 0016):

  * ``margin = C_min - F_max`` — the equation. Its free symbols (``C_min``,
    ``F_max``) are the node's input sockets, derived from the equation itself
    (ADR 0007) and wired straight from the two extremes — no ``pack_values``
    bundling node in between.
  * ``check = margin > 0`` — the assertion, written as one more calc line.
    handcalcs typesets the substituted comparison natively, so the card's math
    block *is* the verdict: ``check = margin > 0 = 90.000 > 0 = True``. The
    judgment lives once, in the user-visible calc text — nothing re-derives
    ``force < capacity`` on the side.

  :func:`check_verdict` then reads ``check`` back out of the calc's own
  ``results`` dict and **raises on false** — a presentation/assertion node that
  performs no comparison of its own. On a passing run it is a no-op; on a
  failing run the raise reddens the node and stops the run. The caption is
  ``calc_notes`` only: the ``check = margin > 0 = … = True`` line inside the
  card is the visible pass/fail, so no separate PASS/FAIL text is joined on.

Dataflow, edge by edge — node ids are the ``@main`` variable names (ADR 0004
D3), ``x.y`` is output socket ``y`` of node ``x``::

    forces.csv  ─> forces (read_table) ──table──> max_force (select_extreme, max "force")
    members.csv ─> members (read_table) ─table──> min_capacity (select_extreme, min "capacity")

    max_force.value ────┬─> steps (handcalc)  "margin = C_min - F_max ⏎ check = margin > 0"
    min_capacity.value ─┘            │
                         ┌───────────┼───────────────┐
                   steps.latex   steps.results    steps.results
                         │            │                │
                      mathml        notes         verdict (check_verdict) — raises on False → red
                         │            │
                         └────────────┴──> report (render_math_card)   caption = notes

Each extreme's ``value`` socket **fans out** to ``steps``; ``steps`` then fans
out three ways — ``latex`` to the math block, ``results`` to the caption notes
*and* to the verdict. ``verdict`` is a leaf side-assertion: its ``ok`` output
feeds nothing, it exists only to redden the run when ``check`` is false. The
math block and the notes re-join on the card, closing the diamond.

Simple, generic mock data only — no real engineering formulas, just a
highest-vs-lowest comparison.

Run (the ``sym`` extra provides handcalcs/SymPy/latex2mathml)::

    uv run --extra sym python examples/capacity_check/capacity_check.py
"""

from __future__ import annotations

from pathlib import Path

from engine import UserError, main, node
from sym import calc_notes, handcalc, latex_to_mathml, render_math_card
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


@node(outputs=["ok"])
def check_verdict(results: dict, check: str = "check") -> dict:
    """Read the calc's own boolean result and fail the run if it is False.

    Presentation/assertion over `handcalc`'s results — it performs NO
    comparison of its own (the comparison lives in the calc line
    `check = margin > 0`). A False result raises, so the run renders this
    node red; a missing key raises too, so renaming the calc symbol without
    updating this param fails loudly instead of yielding a stale verdict.
    """
    if check not in results:
        raise UserError(
            f"check_verdict: no {check!r} result to read; "
            f"available results are {sorted(results)}"
        )
    if not results[check]:
        raise UserError(f"Capacity check failed: {check!r} is False")
    return {"ok": True}


# All node types this example defines (for schema snapshots / registries).
NODES = [select_extreme, check_verdict]


# -- the graph, as ordinary Python (ADR 0004 straight-line form) -------------


@main
def capacity_check_report(
    forces_path: str = "forces.csv", members_path: str = "members.csv"
) -> str:
    """Read both CSVs, pick the extremes, typeset the margin, and check it."""
    # Two independent CSV arcs: each file becomes one {columns, rows} table.
    forces = read_table(path=forces_path)
    members = read_table(path=members_path)

    # Reduce each arc to its governing extreme (sockets: name, value): the
    # highest applied force and the lowest available capacity.
    max_force = select_extreme(forces, column="force", mode="max")
    min_capacity = select_extreme(members, column="capacity", mode="min")

    # The arcs meet at ONE calc block. Each extreme's `value` fans in as a
    # derived socket (ADR 0007). The `lines` field holds the equation AND the
    # assertion that judges it — `check = margin > 0` is the single source of
    # the verdict; handcalcs typesets it with the numbers substituted
    # (check = margin > 0 = 90.000 > 0 = True), so the card itself shows pass/
    # fail and nothing re-derives the comparison.
    steps = handcalc(lines="margin = C_min - F_max\ncheck = margin > 0", C_min=min_capacity.value, F_max=max_force.value)
    # steps.latex → native MathML, so the card renders with zero JS (no CDN).
    mathml = latex_to_mathml(steps.latex)

    # Side-assertion: read `check` back out of the calc's own results and raise
    # if it is False — reddening this node (and stopping the run). A no-op on
    # pass; it computes nothing, so the judgment stays single-sourced.
    verdict = check_verdict(results=steps.results)   # raises on false → red; no-op on pass

    # Caption concern: the value-notes come FROM the calc's own results
    # (steps.results — handcalc's second fan-out, ADR 0013), so the symbol
    # names are declared exactly once — in the equation — and the
    # handcalc → calc_notes caption dependency is an explicit wire on the canvas.
    #
    # Straight-line form (ADR 0004 D7): each call is its own assignment — no
    # nested calls in arguments — so the composite round-trips through the
    # graph⟷source bijection and can be served + edited in the UI.
    notes = calc_notes(steps.results)
    # One card closes the diamond — typeset math (equation + check row) on top,
    # the results notes as the caption underneath (no PASS/FAIL fragment: the
    # check row already is the verdict) — and its `result` socket is the graph
    # output (the `return` below).
    report = render_math_card(title="Capacity check", mathml=mathml, caption=notes)
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
