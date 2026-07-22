"""The smallest end-to-end graph on the engine.

read a file  ->  two small processors  ->  a rendered result

    read_values ──> total ───┐
              └──> average ───┴──> render_summary  (HTML card)

Pure standard library — no third-party dependencies. Run it directly to execute
the graph, print the rendered HTML, and print the equivalent exported Python::

    uv run python examples/minimal/minimal.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CSV_PATH = HERE / "readings.csv"

# Make the engine importable when this file is run directly (the package lives
# at the graph-engine/ root, two levels up).
_ENGINE_ROOT = HERE.parents[1]
if str(_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ENGINE_ROOT))

from engine import Graph, NodeRegistry


# -- nodes -----------------------------------------------------------------


def read_values(path: str = "readings.csv") -> list:
    """Read a one-column CSV (header ``value``) into a list of floats."""
    with open(path, newline="", encoding="utf-8") as handle:
        return [float(row["value"]) for row in csv.DictReader(handle)]


def total(values: list) -> float:
    """Sum the values."""
    return sum(values)


def average(values: list) -> float:
    """Mean of the values."""
    return sum(values) / len(values)


def render_summary(total: float, average: float) -> str:
    """Render a small, self-contained HTML card (inline CSS, no CDN)."""
    return (
        '<div style="font-family:system-ui;max-width:20rem;padding:1rem;'
        'border:1px solid #ddd;border-radius:8px">'
        '<h1 style="font-size:1rem;margin:0 0 .5rem">Readings summary</h1>'
        f"<p>Total: <b>{total:g}</b> &middot; Average: <b>{average:g}</b></p></div>"
    )


# -- wiring ----------------------------------------------------------------


# Replace registry pattern with decorators - decorate a function as a node type
# so it can be called in any other (this should parse it for any children and allow parents to invoke it)
# this should result in every decorated node being possible to render as a graph including main
# do we need a separate decorator for main in that case or is it just the higher level instance / class ?
# maybe main (or similar) is a UI only decorator that creates a view or graph instance from it and everything
# else is just a node.
def build_registry() -> NodeRegistry:
    reg = NodeRegistry()
    reg.register(read_values, third_party_import="from minimal import read_values")
    reg.register(total, third_party_import="from minimal import total")
    reg.register(average, third_party_import="from minimal import average")
    reg.register(render_summary, third_party_import="from minimal import render_summary")
    return reg


def build_graph(csv_path: Path | str = CSV_PATH) -> Graph:
    g = Graph()
    g.add("read", "read_values", inputs={"path": str(csv_path)})
    g.add("sum", "total")
    g.add("avg", "average")
    g.add("card", "render_summary")
    g.connect("read", "output", "sum", "values")
    g.connect("read", "output", "avg", "values")
    g.connect("sum", "output", "card", "total")
    g.connect("avg", "output", "card", "average")
    return g


def main() -> None:
    from engine import run, to_python

    reg = build_registry()
    g = build_graph()
    print(run(g, reg).value("card"))
    print("\n----- to_python(graph) -----")
    print(to_python(g, reg))


if __name__ == "__main__":
    main()
