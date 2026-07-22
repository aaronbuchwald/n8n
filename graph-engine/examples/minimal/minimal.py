"""The smallest end-to-end graph, authored with decorators.

read a file  ->  two small processors  ->  a rendered result

    read_values ──> total ───┐
              └──> average ───┴──> render_summary  (HTML card)

Each leaf is a ``@node``; ``readings_report`` is a ``@main`` composite whose body
*is* the graph. Tracing it (``readings_report.to_graph()``) yields the engine's
Graph data model — from there ``run`` and ``to_python`` are unchanged.

Pure standard library. Run directly to execute + print the exported Python::

    uv run python examples/minimal/minimal.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CSV_PATH = HERE / "readings.csv"

# Make the engine importable when this file is run directly (package at the
# graph-engine/ root, two levels up).
_ENGINE_ROOT = HERE.parents[1]
if str(_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ENGINE_ROOT))

from engine import main, node


# -- nodes -----------------------------------------------------------------


@node
def read_values(path: str = "readings.csv") -> list:
    """Read a one-column CSV (header ``value``) into a list of floats."""
    with open(path, newline="", encoding="utf-8") as handle:
        return [float(row["value"]) for row in csv.DictReader(handle)]


@node
def total(values: list) -> float:
    """Sum the values."""
    return sum(values)


@node
def average(values: list) -> float:
    """Mean of the values."""
    return sum(values) / len(values)


@node
def render_summary(total: float, average: float) -> str:
    """Render a small, self-contained HTML card (inline CSS, no CDN)."""
    return (
        '<div style="font-family:system-ui;max-width:20rem;padding:1rem;'
        'border:1px solid #ddd;border-radius:8px">'
        '<h1 style="font-size:1rem;margin:0 0 .5rem">Readings summary</h1>'
        f"<p>Total: <b>{total:g}</b> &middot; Average: <b>{average:g}</b></p></div>"
    )


# -- the graph, as ordinary Python -----------------------------------------


@main
def readings_report(path: str = "readings.csv") -> str:
    """Read the file, reduce it two ways, and render the result."""
    values = read_values(path)
    return render_summary(total(values), average(values))


# All the node types this example defines (for schema snapshots).
NODES = [read_values, total, average, render_summary]


def build_graph(csv_path: Path | str = CSV_PATH):
    """Trace the composite into a Graph (absolute CSV path so it runs anywhere)."""
    return readings_report.to_graph(path=str(csv_path))


def main_cli() -> None:
    from engine import run, to_python

    g = build_graph()
    print(run(g).value(g.output_id))
    print("\n----- to_python(graph) -----")
    print(to_python(g))


if __name__ == "__main__":
    main_cli()
