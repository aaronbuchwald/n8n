"""A hand-written **wiring composite** — the round-trip surface of ADR 0004.

This is ordinary Python *and* a graph: a ``@main`` function whose body is a
straight-line sequence of single-assignment calls. Each variable is a node id;
each argument reference is an edge; each literal is a widget value. Parse it with
:func:`engine.from_composite` to get the exact same :class:`~engine.graph.Graph`
you would build on the canvas — and emit it back with
:func:`engine.to_composite`.

Simple-math node types only (the ``sources`` + ``calc`` packs), network-free via
the in-process ``mock_api``. Runnable on its own::

    uv run python examples/bijection/report.py
"""

from __future__ import annotations

from calc import average, median, render_summary
from engine import main
from sources import mock_api


@main
def report():
    values = mock_api(dataset="readings")
    avg = average(values=values)
    med = median(values=values)
    card = render_summary(title="Readings summary", average=avg, median=med)
    return card


if __name__ == "__main__":
    print(report())
