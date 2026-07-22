"""Engine-core tests: introspection, schema, run, and the export round-trip.

Self-contained — uses only toy functions defined here, no external example.
Run with:  uv run --extra dev pytest tests/ -q

NOTE: no ``from __future__ import annotations`` here — it would stringify the
list-of-dicts multi-output annotation on ``make`` and break its detection.
"""

import pytest

from engine import (
    CycleError,
    Graph,
    NodeRegistry,
    UnknownNodeType,
    node_spec,
    run,
    to_python,
    validate_graph,
    validate_node_spec,
)


# -- toy node functions ----------------------------------------------------


def inc(x: int = 0) -> int:
    return x + 1


def add(a: int, b: int) -> int:
    return a + b


def make(a: int = 1, b: int = 2) -> [{"name": "a"}, {"name": "b"}]:
    return {"a": a, "b": b}


# -- node_spec introspection ----------------------------------------------


def test_single_output_and_widget():
    spec = node_spec(inc)
    assert spec["outputs"] == [{"name": "output", "type": "int"}]
    x = spec["inputs"][0]
    assert x["name"] == "x" and x["default"] == 0
    assert x["widget"] == {"kind": "number", "subtype": "int"}
    validate_node_spec(spec)


def test_multi_output_from_annotation():
    spec = node_spec(make)
    assert [o["name"] for o in spec["outputs"]] == ["a", "b"]
    validate_node_spec(spec)


# -- Graph model + schema --------------------------------------------------


def test_graph_json_roundtrip():
    g = Graph().add("a", "inc", inputs={"x": 1})
    g.connect("a", "output", "b", "x")
    g.add("b", "inc")
    restored = Graph.from_json(g.to_json())
    assert restored.to_dict() == g.to_dict()


def test_validate_graph_rejects_dangling_edge():
    bad = {
        "version": "0.1.0",
        "nodes": [{"id": "a", "type": "inc"}],
        "edges": [{"source": "a", "sourceOutput": "output", "target": "ghost", "targetInput": "x"}],
    }
    with pytest.raises(Exception):
        validate_graph(bad)


# -- run -------------------------------------------------------------------


def _registry() -> NodeRegistry:
    reg = NodeRegistry()
    reg.register(inc)
    reg.register(add)
    reg.register(make)
    return reg


def test_run_single_chain():
    reg = _registry()
    g = Graph().add("a", "inc", inputs={"x": 1}).add("b", "inc")
    g.connect("a", "output", "b", "x")
    assert run(g, reg).value("b") == 3


def test_run_multi_output_sockets():
    reg = _registry()
    g = Graph().add("m", "make", inputs={"a": 10, "b": 5}).add("s", "add")
    g.connect("m", "a", "s", "a")
    g.connect("m", "b", "s", "b")
    assert run(g, reg).value("s") == 15


def test_unknown_node_type():
    g = Graph().add("a", "nope")
    with pytest.raises(UnknownNodeType):
        run(g, _registry())


def test_cycle_detection():
    reg = _registry()
    g = Graph().add("a", "inc").add("b", "inc")
    g.connect("a", "output", "b", "x")
    g.connect("b", "output", "a", "x")
    with pytest.raises(CycleError):
        run(g, reg)


# -- to_python round-trip (no imports so we can exec with injected fns) -----


def test_exported_python_reproduces_result():
    reg = NodeRegistry()
    reg.register(inc, third_party_import=None)
    reg.register(add, third_party_import=None)
    g = Graph().add("a", "inc", inputs={"x": 1}).add("b", "inc").add("c", "add")
    g.connect("a", "output", "b", "x")
    g.connect("a", "output", "c", "a")
    g.connect("b", "output", "c", "b")

    script = to_python(g, reg, header=False)
    namespace = {"inc": inc, "add": add}
    exec(compile(script, "<exported>", "exec"), namespace)  # noqa: S102 - trusted, generated
    assert namespace["_c"] == run(g, reg).value("c") == (2 + 3)
