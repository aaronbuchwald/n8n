"""Bijection tests for ``to_composite`` / ``from_composite`` (ADR 0004).

The core deliverable: prove Graph ⟷ wiring-composite is an identity round-trip
**modulo layout** (positions) and wiring-line formatting. Covers a real traced
graph, a multi-output source, a positional-only node, source idempotence, a
hand-written composite that drives real execution, control-flow rejection, and
the variable-name-is-id invariant.

Self-contained toy node types (multi-output ``split``, positional-only ``diff``)
are registered into a local registry, mirroring ``test_engine.py``.
"""

from __future__ import annotations

import pytest

import calc  # noqa: F401 - registers calc.* node types into DEFAULT_REGISTRY
import sources  # noqa: F401 - registers sources.* node types
from engine import (
    DEFAULT_REGISTRY,
    EngineError,
    Graph,
    NodeRegistry,
    from_composite,
    run,
    to_composite,
)

from minimal import build_graph


# -- toy node functions (multi-output + positional-only) -------------------


def split(x: int = 0) -> dict:
    return {"lo": x, "hi": x + 1}


def diff(a, b, /) -> int:  # positional-only
    return a - b


def scale(value: int, factor: int = 2) -> int:
    return value * factor


@pytest.fixture
def toy_registry() -> NodeRegistry:
    reg = NodeRegistry()
    reg.register(split, outputs=["lo", "hi"])
    reg.register(diff)
    reg.register(scale)
    return reg


# -- comparison helper: graph equality modulo layout -----------------------


def _canonical(graph: Graph) -> dict:
    """A layout-independent, order-independent view of a graph for equality.

    Nodes compared by id (positions dropped), edges as an unordered set, plus
    the output socket — exactly the bijective content per ADR 0004.
    """
    d = graph.to_dict()
    nodes = {n["id"]: {"type": n["type"], "inputs": n["inputs"]} for n in d["nodes"]}
    edges = frozenset(tuple(sorted(e.items())) for e in d["edges"])
    return {"nodes": nodes, "edges": edges, "output": d["output"]}


def _assert_roundtrip_identity(graph: Graph, registry: NodeRegistry) -> None:
    restored = from_composite(to_composite(graph, registry), registry)
    assert _canonical(restored) == _canonical(graph)


# -- graph-level round-trip identity ---------------------------------------


def test_roundtrip_identity_traced_minimal_graph():
    # A real traced graph over registered node types (read -> total/average ->
    # render), including a str widget literal (the CSV path).
    graph = build_graph()
    _assert_roundtrip_identity(graph, DEFAULT_REGISTRY)


def test_roundtrip_identity_multi_output_source(toy_registry: NodeRegistry):
    # split has two output sockets, wired via x["lo"] / x["hi"].
    graph = Graph()
    graph.add("s", f"{__name__}.split", inputs={"x": 5})
    graph.add("lo_scaled", f"{__name__}.scale")
    graph.add("hi_scaled", f"{__name__}.scale", inputs={"factor": 3})
    graph.connect("s", "lo", "lo_scaled", "value")
    graph.connect("s", "hi", "hi_scaled", "value")
    graph.output = {"node": "hi_scaled", "socket": "result"}
    _assert_roundtrip_identity(graph, toy_registry)


def test_roundtrip_identity_positional_only(toy_registry: NodeRegistry):
    # diff(a, b, /) — both params positional-only, emitted positionally.
    graph = Graph()
    graph.add("s", f"{__name__}.split", inputs={"x": 10})
    graph.add("d", f"{__name__}.diff")
    graph.connect("s", "hi", "d", "a")
    graph.connect("s", "lo", "d", "b")
    graph.output = {"node": "d", "socket": "result"}
    _assert_roundtrip_identity(graph, toy_registry)

    # And the emitted call is truly positional (no a=/b= keywords).
    source = to_composite(graph, toy_registry)
    assert "d = diff(s['hi'], s['lo'])" in source


def test_roundtrip_identity_alias_collision(toy_registry: NodeRegistry):
    # A node id equal to a type's call name must not shadow the function: the
    # type imports under an alias and the body calls the alias.
    graph = Graph()
    graph.add("s", f"{__name__}.split", inputs={"x": 1})
    graph.add("diff", f"{__name__}.diff")  # id collides with the `diff` import
    graph.connect("s", "hi", "diff", "a")
    graph.connect("s", "lo", "diff", "b")
    graph.output = {"node": "diff", "socket": "result"}

    source = to_composite(graph, toy_registry)
    assert "import diff as diff_2" in source
    assert "diff = diff_2(" in source
    _assert_roundtrip_identity(graph, toy_registry)


# -- source idempotence (byte-stable emit) ---------------------------------


def test_source_idempotence_minimal():
    source = to_composite(build_graph())
    assert to_composite(from_composite(source)) == source


def test_source_idempotence_multi_output(toy_registry: NodeRegistry):
    graph = Graph()
    graph.add("s", f"{__name__}.split", inputs={"x": 5})
    graph.add("d", f"{__name__}.diff")
    graph.connect("s", "lo", "d", "a")
    graph.connect("s", "hi", "d", "b")
    graph.output = {"node": "d", "socket": "result"}

    source = to_composite(graph, toy_registry)
    assert to_composite(from_composite(source, toy_registry), toy_registry) == source


# -- parse a hand-written composite and run it -----------------------------


HANDWRITTEN = '''\
from engine import main
from sources import mock_api
from calc import average, median, render_summary


@main
def report():
    values = mock_api(dataset="readings")
    avg = average(values=values)
    med = median(values=values)
    card = render_summary(title="Readings", average=avg, median=med)
    return card
'''


def test_parse_handwritten_composite_drives_execution():
    graph = from_composite(HANDWRITTEN, DEFAULT_REGISTRY)

    # Structure parsed as expected.
    assert {n.id for n in graph.nodes} == {"values", "avg", "med", "card"}
    assert graph.node("values").type == "sources.mock_api"
    assert graph.node("values").inputs == {"dataset": "readings"}
    assert graph.output == {"node": "card", "socket": "result"}

    # The parsed graph really runs (mock readings: [10,20,30,40]).
    result = run(graph)
    assert result.value("avg") == 25.0
    assert result.value("med") == 25.0
    html = result.value("card", "result")
    assert html.startswith("<div")
    assert "25" in html


def test_parse_then_emit_roundtrips_handwritten():
    graph = from_composite(HANDWRITTEN, DEFAULT_REGISTRY)
    reparsed = from_composite(to_composite(graph), DEFAULT_REGISTRY)
    assert _canonical(reparsed) == _canonical(graph)


# -- variable-name ids -----------------------------------------------------


def test_node_ids_equal_source_variable_names():
    graph = from_composite(HANDWRITTEN, DEFAULT_REGISTRY)
    # ids are exactly the composite's assignment variable names.
    assert sorted(n.id for n in graph.nodes) == ["avg", "card", "med", "values"]
    # positions are excluded from the bijection (layout is a sidecar concern).
    assert all(n.position is None for n in graph.nodes)


# -- rejection of non-dataflow constructs (ADR 0004 D7) --------------------


def test_rejects_if_statement():
    source = '''\
from engine import main
from calc import total


@main
def bad():
    a = total(values=[1, 2])
    if a:
        b = total(values=[3])
    return a
'''
    with pytest.raises(EngineError, match="D7"):
        from_composite(source, DEFAULT_REGISTRY)


def test_rejects_for_loop():
    source = '''\
from engine import main
from calc import total


@main
def bad():
    for i in range(3):
        a = total(values=[i])
    return a
'''
    with pytest.raises(EngineError, match="D7"):
        from_composite(source, DEFAULT_REGISTRY)


def test_rejects_tuple_target():
    source = '''\
from engine import main
from calc import total


@main
def bad():
    a, b = total(values=[1]), total(values=[2])
    return a
'''
    with pytest.raises(EngineError, match="D7"):
        from_composite(source, DEFAULT_REGISTRY)


def test_unknown_type_names_the_node():
    source = '''\
from engine import main
from calc import bogus_node


@main
def bad():
    x = bogus_node(values=[1])
    return x
'''
    with pytest.raises(EngineError, match="x"):
        from_composite(source, DEFAULT_REGISTRY)
