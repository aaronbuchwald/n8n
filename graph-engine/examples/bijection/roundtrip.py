"""Demonstrate the Graph ⟷ composite bijection end to end (ADR 0004).

    parse the hand-written composite  ->  Graph
    run the Graph                     ->  a rendered HTML card
    emit the Graph back to composite  ->  source text
    re-parse the emitted source       ->  identical Graph  (the round-trip)

Pure standard library + the installed ``engine`` / ``calc`` / ``sources``
packages. Run it::

    uv run python examples/bijection/roundtrip.py
"""

from __future__ import annotations

from pathlib import Path

import calc  # noqa: F401 - registers calc.* node types into DEFAULT_REGISTRY
import sources  # noqa: F401 - registers sources.* node types
from engine import Graph, from_composite, run, to_composite

HERE = Path(__file__).resolve().parent
COMPOSITE = HERE / "report.py"


def _canonical(graph: Graph) -> dict:
    """A layout-independent view of a graph — the bijective content only."""
    d = graph.to_dict()
    nodes = {n["id"]: {"type": n["type"], "inputs": n["inputs"]} for n in d["nodes"]}
    edges = frozenset(tuple(sorted(e.items())) for e in d["edges"])
    return {"nodes": nodes, "edges": edges, "output": d["output"]}


def main() -> None:
    source = COMPOSITE.read_text(encoding="utf-8")

    # 1. composite source -> Graph (AST parse)
    graph = from_composite(source)
    print(f"parsed {len(graph.nodes)} nodes: {', '.join(n.id for n in graph.nodes)}")
    print(f"node ids == variable names; output = {graph.output}")

    # 2. run the parsed Graph
    out = run(graph).value(graph.output["node"], graph.output["socket"])
    print("\n----- run(graph) -----")
    print(out)

    # 3. Graph -> composite source (emit)
    emitted = to_composite(graph)
    print("\n----- to_composite(graph) -----")
    print(emitted)

    # 4. re-parse the emitted source; the Graph must be identical (modulo layout)
    reparsed = from_composite(emitted)
    assert _canonical(reparsed) == _canonical(graph), "round-trip changed the graph!"
    # ...and the emit is byte-stable (idempotent).
    assert to_composite(reparsed) == emitted, "emit is not idempotent!"
    print("round-trip: identical ✓")


if __name__ == "__main__":
    main()
