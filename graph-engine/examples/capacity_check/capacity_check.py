"""Capacity check — two CSV arcs meeting at one completed calculation.

Read → select → calc. Five nodes, no bespoke glue:

* **Arc 1** — read the ``force`` column of ``forces.csv`` into a list of
  floats, reduce it to the **highest** value (``calc.maximum``).
* **Arc 2** — read the ``capacity`` column of ``members.csv``, reduce it to the
  **lowest** value (``calc.minimum``).
* **Combine** — both extremes fan into a single ``sheet.calc_card`` node. That
  node *is* the calculation: its ``formulas`` and ``checks`` literals declare
  the whole sheet, :mod:`calcsheet` evaluates it **once**, and the card it
  renders is a pure function of that one result — the HTML can never disagree
  with the numbers it was built from.

``sources.read_csv`` returns bare floats, so the member/force *names* are
deliberately dropped: what governs the check is the number, and re-introducing
labels would mean a second place for them to drift from the CSV.

The calc's mini-syntax, one entry per line — ``# text`` after an expression is
the row's **reference** (formula) or **description** (check), and a trailing
``[unit]`` on a formula is its display unit::

    r = F_max / C_min  # demand / capacity
    U = 100 * r [%]    # utilisation

``F_max`` and ``C_min`` are read before any formula defines them, so they are
the calc's **inputs** — and therefore the node's input sockets, derived from
the formulas themselves (ADR 0007) exactly as ``sym.handcalc``'s are. They are
wired from the two extremes; nothing restates them.

Dataflow, edge by edge — node ids are the ``@main`` variable names (ADR 0004
D3), ``x.y`` is output socket ``y`` of node ``x``::

    forces.csv  ─> forces (read_csv "force")     ──> F_max (calc.maximum) ──┐
                                                                            ├─> card ─> html
    members.csv ─> members (read_csv "capacity") ──> C_min (calc.minimum) ──┘

**A failing check does not fail the run.** ``U < 50`` is false for this data
(57.1 %), so that row renders FAIL and the card's overall verdict is FAIL —
while the run stays green. The verdict is card content, not an execution error;
there is no separate assertion node re-deriving it on the side.

Simple, generic mock data only — no real engineering formulas, just a
highest-force-vs-lowest-capacity ratio.

Run (the ``sym`` extra provides calcsheet/SymPy/latex2mathml)::

    uv run --extra sym python examples/capacity_check/capacity_check.py
"""

from __future__ import annotations

from pathlib import Path

from calc import maximum, minimum
from engine import main
from sheet import calc_card
from sources import read_csv

HERE = Path(__file__).resolve().parent
FORCES_CSV = HERE / "forces.csv"
MEMBERS_CSV = HERE / "members.csv"

# What the graph needs to run — the ADR 0003 declarative descriptor. Versions
# match the `sym` extra in pyproject.toml; calcsheet pulls sympy + latex2mathml.
DEPENDENCIES = [
    {"name": "calcsheet", "version": "0.1.*"},
    {"name": "sympy", "version": "1.14.*"},
    {"name": "latex2mathml", "version": "3.81.*"},
]


# -- the graph, as ordinary Python (ADR 0004 straight-line form) -------------


@main
def capacity_check_report(
    forces_path: str = "forces.csv", members_path: str = "members.csv"
) -> str:
    """Read both CSVs, reduce each to its extreme, and render the calc card."""
    # Two independent CSV arcs. `read_csv` names a column and yields a list of
    # floats — interchangeable with `sources.mock_api`, which emits the same shape.
    forces = read_csv(path=forces_path, column="force")
    members = read_csv(path=members_path, column="capacity")

    # Reduce each arc to the value that governs the check: the highest applied
    # force and the lowest available capacity. Plain `calc` pack reductions —
    # nothing example-local.
    F_max = maximum(forces)
    C_min = minimum(members)

    # The arcs meet at ONE node that holds the entire calculation as data.
    # `F_max`/`C_min` are free symbols of the formulas, so they arrive as
    # derived input sockets (ADR 0007) and are wired straight from the extremes
    # — the symbols are declared exactly once, in the formulas literal.
    #
    # Straight-line form (ADR 0004 D7): each call is its own assignment — no
    # nested calls in arguments — so the composite round-trips through the
    # graph⟷source bijection and can be served + edited in the UI.
    card = calc_card(
        title="Capacity check",
        as_of="2026-07-24",
        formulas="r = F_max / C_min  # demand / capacity\nU = 100 * r [%]  # utilisation",
        checks="U < 100  # capacity not exceeded\nU < 50  # utilisation target",
        F_max=F_max.result,
        C_min=C_min.result,
    )
    # The card's `result` socket (the self-contained HTML document) is the graph
    # output; its sibling `height` socket tells the UI how tall to draw it.
    return card


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
