"""Bijection round-trip for a dynamic ``sym.handcalc`` node (ADR 0007 D5).

Derived symbols serialise as ordinary keyword arguments on the wiring line —
wired symbols are references (edges), unwired symbols are literals (widget
values). ``to_composite`` emits them via the node's **effective** inputs (in
deriver/appearance order); ``from_composite`` passes them through by name and
defers legality to the dynamic bind. Proves identity for (i) all symbols wired,
(ii) mixed wired/inline, (iii) a multi-line calc — the three obligations the ADR
adds to the existing bijection tests.
"""

from __future__ import annotations

import sym  # noqa: F401 - registers sym.* (incl. sym.handcalc) into DEFAULT_REGISTRY
from engine import DEFAULT_REGISTRY, Graph, from_composite, node, to_composite


@node
def num(value: float = 0.0) -> float:
    """Toy numeric source so derived symbols have something to wire from."""
    return value


def _canonical(graph: Graph) -> dict:
    d = graph.to_dict()
    nodes = {n["id"]: {"type": n["type"], "inputs": n["inputs"]} for n in d["nodes"]}
    edges = frozenset(tuple(sorted(e.items())) for e in d["edges"])
    return {"nodes": nodes, "edges": edges, "output": d["output"]}


def _assert_roundtrip(graph: Graph) -> None:
    restored = from_composite(to_composite(graph, DEFAULT_REGISTRY), DEFAULT_REGISTRY)
    assert _canonical(restored) == _canonical(graph)


def test_roundtrip_all_symbols_wired():
    g = Graph()
    g.add("cap", f"{__name__}.num", inputs={"value": 210.0})
    g.add("force", f"{__name__}.num", inputs={"value": 120.0})
    g.add("steps", "sym.handcalc", inputs={"lines": "margin = C_min - F_max"})
    g.connect("cap", "result", "steps", "C_min")
    g.connect("force", "result", "steps", "F_max")
    g.output = {"node": "steps", "socket": "latex"}
    _assert_roundtrip(g)

    # The emitted wiring line carries the equation + both feeds in one statement,
    # derived kwargs after the static param, in appearance order.
    source = to_composite(g, DEFAULT_REGISTRY)
    assert "steps = handcalc(lines='margin = C_min - F_max', C_min=cap, F_max=force)" in source


def test_roundtrip_mixed_wired_and_inline_symbol():
    g = Graph()
    g.add("picked", f"{__name__}.num", inputs={"value": 3.0})
    g.add("steps", "sym.handcalc", inputs={"lines": "E_k = 1/2*m*v**2", "m": 2.0})
    g.connect("picked", "result", "steps", "v")
    g.output = {"node": "steps", "socket": "latex"}
    _assert_roundtrip(g)

    source = to_composite(g, DEFAULT_REGISTRY)
    # m is an inline literal, v is a wire — both after lines, in appearance order.
    assert "steps = handcalc(lines='E_k = 1/2*m*v**2', m=2.0, v=picked)" in source


def test_roundtrip_multiline_calc():
    g = Graph()
    g.add("velocity", f"{__name__}.num", inputs={"value": 4.0})
    g.add("steps", "sym.handcalc", inputs={"lines": "d = v*t\nE = m*d", "t": 2.0, "m": 5.0})
    g.connect("velocity", "result", "steps", "v")
    g.output = {"node": "steps", "socket": "latex"}
    _assert_roundtrip(g)
