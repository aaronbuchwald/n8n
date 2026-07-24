"""Handcalc demo — a dynamic ``sym.handcalc`` node with derived symbol sockets.

The reference graph for the **dynamic calc node** (ADR 0007) and its editor
(ADR 0007 stream W): one ``sym.handcalc`` node whose ``lines`` literal holds
both an equation and the assertion that judges it, and whose free symbols
(``C_min``, ``F_max``) are the node's input sockets — derived from the equation
text itself, not from the Python signature — wired straight from two upstream
reductions.

::

    loads.csv ─> forces (read_csv "force")     ──> max_force (calc.maximum) ──┐
              └> capacities (read_csv "cap")   ──> min_capacity (calc.minimum) ┤
                                                                               │
                        steps (sym.handcalc)  "margin = C_min - F_max          │
                                               check = margin > 0"  <──────────┘
                              │
                  ┌───────────┴───────────┐
              steps.latex             steps.results
                  │                        │
                mathml                   notes
                  └───────────┬───────────┘
                              ▼
                     report (render_math_card)

handcalcs typesets the substituted comparison natively, so the card's math
block *is* the verdict: ``check = margin > 0 = 90.000 > 0 = True``. Nothing
re-derives it on the side.

The ``capacity_check`` example used to carry this node; it now runs on
``sheet.calc_card`` instead, so this demo exists to keep a dynamic ``handcalc``
node on a served graph — it is what the calc-widget, lines-preview and
inspector-value specs drive.

Run (the ``sym`` extra provides handcalcs/SymPy/latex2mathml)::

    uv run --extra sym python examples/handcalc_demo/handcalc_demo.py
"""

from __future__ import annotations

from pathlib import Path

from calc import maximum, minimum
from engine import main
from sources import read_csv
from sym import calc_notes, handcalc, latex_to_mathml, render_math_card

HERE = Path(__file__).resolve().parent
LOADS_CSV = HERE / "loads.csv"

# What the graph needs to run — the ADR 0003 declarative descriptor. Versions
# match the `sym` extra in pyproject.toml.
DEPENDENCIES = [
    {"name": "sympy", "version": "1.14.*"},
    {"name": "handcalcs", "version": "1.11.*"},
    {"name": "forallpeople", "version": "2.7.*"},
    {"name": "latex2mathml", "version": "3.81.*"},
]


# -- the graph, as ordinary Python (ADR 0004 straight-line form) -------------


@main
def handcalc_demo_report(path: str = "loads.csv") -> str:
    """Reduce two CSV columns to extremes, typeset the margin, and card it."""
    # One CSV, two columns: each read yields a list of floats.
    forces = read_csv(path=path, column="force")
    capacities = read_csv(path=path, column="capacity")

    # The two numbers the calc compares.
    max_force = maximum(forces)
    min_capacity = minimum(capacities)

    # ONE calc block. `lines` holds the equation AND the assertion that judges
    # it; `C_min`/`F_max` are its free symbols, so they are derived input
    # sockets (ADR 0007) and are wired here — the symbol names are declared
    # exactly once, in the equation.
    steps = handcalc(lines="margin = C_min - F_max\ncheck = margin > 0", C_min=min_capacity, F_max=max_force)
    # steps.latex → native MathML, so the card renders with zero JS (no CDN).
    mathml = latex_to_mathml(steps.latex)
    # The caption's labels come FROM the calc's own results (ADR 0013), so they
    # cannot drift from the equation that produced them.
    notes = calc_notes(steps.results)
    report = render_math_card(title="Margin check", mathml=mathml, caption=notes)
    return report


def build_graph(loads_csv: Path | str = LOADS_CSV):
    """Trace the composite into a Graph (absolute CSV path so it runs anywhere)."""
    graph = handcalc_demo_report.to_graph(path=str(loads_csv))
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
