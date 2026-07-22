"""Engine-core tests: introspection, bind/validation, run, export, ordering.

Self-contained — only toy functions defined here. No `from __future__ import
annotations` needed (multi-output is declared via `outputs=`, not annotations).
Run with:  uv run --extra dev pytest tests/ -q
"""

import pytest

from engine import (
    BindError,
    CycleError,
    DuplicateNodeType,
    EngineError,
    Graph,
    NodeExecutionError,
    NodeRegistry,
    UnknownNodeType,
    bind,
    node_spec,
    run,
    to_python,
    topological_sort,
    validate_node_spec,
)


# -- toy node functions ----------------------------------------------------


def inc(x: int = 0) -> int:
    return x + 1


def add(a: int, b: int) -> int:
    return a + b


def split(x: int = 0) -> dict:
    return {"lo": x, "hi": x + 1}


def diff(a, b, /) -> int:  # positional-only
    return a - b


def boom(x: int = 0) -> int:
    raise ValueError("nope")


def _registry() -> NodeRegistry:
    reg = NodeRegistry()
    reg.register(inc)
    reg.register(add)
    reg.register(split, outputs=["lo", "hi"])
    reg.register(diff)
    reg.register(boom)
    return reg


# -- node_spec introspection ----------------------------------------------


def test_default_output_is_result():
    spec = node_spec(inc)
    assert spec["outputs"] == [{"name": "result", "type": "int"}]
    assert spec["id"] == f"{__name__}.inc"
    validate_node_spec(spec)


def test_input_kind_recorded():
    assert node_spec(inc)["inputs"][0]["kind"] == "positionalOrKeyword"
    assert [i["kind"] for i in node_spec(diff)["inputs"]] == ["positionalOnly", "positionalOnly"]


def test_declared_outputs():
    spec = node_spec(split, outputs=["lo", "hi"])
    assert [o["name"] for o in spec["outputs"]] == ["lo", "hi"]


def test_dict_return_is_not_special_cased():
    # A plain -> dict is one 'result' socket, not auto-exploded.
    spec = node_spec(split)
    assert [o["name"] for o in spec["outputs"]] == ["result"]


def test_varargs_rejected():
    def variadic(*args):
        return args

    with pytest.raises(EngineError):
        node_spec(variadic)


# -- registry: qualified ids, collisions -----------------------------------


def test_duplicate_id_different_callable_errors():
    reg = NodeRegistry()
    reg.register(inc)
    with pytest.raises(DuplicateNodeType):
        reg.register(lambda x=0: x, module=inc.__module__, qualname="inc")


def test_same_short_name_different_module_coexist():
    reg = NodeRegistry()
    a = reg.register(inc, module="pkg_a", qualname="total")
    b = reg.register(inc, module="pkg_b", qualname="total")
    assert a.id == "pkg_a.total" and b.id == "pkg_b.total"
    assert set(reg.ids()) == {"pkg_a.total", "pkg_b.total"}


# -- bind: up-front validation --------------------------------------------


def test_bind_unknown_type():
    with pytest.raises(UnknownNodeType) as exc:
        bind(Graph().add("a", "nope"), _registry())
    assert exc.value.node_id == "a"  # structured: the offending graph node


def test_bind_bad_source_socket():
    g = Graph().add("a", f"{__name__}.inc").add("b", f"{__name__}.inc")
    g.connect("a", "nonesuch", "b", "x")
    with pytest.raises(BindError, match="output") as exc:
        bind(g, _registry())
    # Bad sourceOutput badges the source node + the full edge.
    assert exc.value.node_id == "a"
    assert exc.value.edge == {
        "source": "a", "sourceOutput": "nonesuch", "target": "b", "targetInput": "x",
    }


def test_bind_bad_target_input():
    g = Graph().add("a", f"{__name__}.inc").add("b", f"{__name__}.inc")
    g.connect("a", "result", "b", "nonesuch")
    with pytest.raises(BindError, match="parameter") as exc:
        bind(g, _registry())
    # Bad targetInput badges the target node + the full edge.
    assert exc.value.node_id == "b"
    assert exc.value.edge == {
        "source": "a", "sourceOutput": "result", "target": "b", "targetInput": "nonesuch",
    }


def test_bind_edge_unknown_node():
    g = Graph().add("a", f"{__name__}.inc")
    g.connect("a", "result", "ghost", "x")  # target does not exist
    with pytest.raises(BindError, match="unknown node") as exc:
        bind(g, _registry())
    assert exc.value.node_id == "ghost"
    assert exc.value.edge["target"] == "ghost"


def test_bind_duplicate_input_edge():
    g = Graph().add("a", f"{__name__}.inc").add("b", f"{__name__}.inc").add("c", f"{__name__}.inc")
    g.connect("a", "result", "c", "x")
    g.connect("b", "result", "c", "x")
    with pytest.raises(BindError, match="more than one edge") as exc:
        bind(g, _registry())
    # The second (offending) edge into c is badged, with c as the node.
    assert exc.value.node_id == "c"
    assert exc.value.edge == {
        "source": "b", "sourceOutput": "result", "target": "c", "targetInput": "x",
    }


def test_bind_missing_required_input():
    g = Graph().add("s", f"{__name__}.add")  # add(a, b) both required
    with pytest.raises(BindError, match="required") as exc:
        bind(g, _registry())
    assert exc.value.node_id == "s"
    assert exc.value.edge is None  # node-scoped, not edge-scoped


def test_bind_non_serialisable_literal():
    g = Graph().add("a", f"{__name__}.inc", inputs={"x": object()})
    with pytest.raises(BindError, match="serialisable") as exc:
        bind(g, _registry())
    assert exc.value.node_id == "a"


def test_bind_unknown_literal_param():
    g = Graph().add("a", f"{__name__}.inc", inputs={"nope": 1})
    with pytest.raises(BindError, match="not a") as exc:
        bind(g, _registry())
    assert exc.value.node_id == "a"


def test_bind_cycle_carries_node_ids():
    g = Graph().add("a", f"{__name__}.inc").add("b", f"{__name__}.inc")
    g.connect("a", "result", "b", "x")
    g.connect("b", "result", "a", "x")
    with pytest.raises(CycleError) as exc:
        bind(g, _registry())
    assert set(exc.value.node_ids) == {"a", "b"}


def test_bind_reports_before_running():
    # A bad socket must raise at bind, not during execution.
    g = Graph().add("a", f"{__name__}.inc", inputs={"x": 1}).add("b", f"{__name__}.inc")
    g.connect("a", "ghost", "b", "x")
    with pytest.raises(BindError) as exc:
        run(g, _registry())
    assert exc.value.node_id == "a"


# -- run -------------------------------------------------------------------


def test_run_single_chain():
    g = Graph().add("a", f"{__name__}.inc", inputs={"x": 1}).add("b", f"{__name__}.inc")
    g.connect("a", "result", "b", "x")
    assert run(g, _registry()).value("b") == 3


def test_run_positional_only():
    g = Graph().add("d", f"{__name__}.diff", inputs={"a": 10, "b": 3})
    assert run(g, _registry()).value("d") == 7


def test_run_multi_output_selection():
    g = Graph().add("m", f"{__name__}.split", inputs={"x": 5}).add("s", f"{__name__}.add")
    g.connect("m", "lo", "s", "a")
    g.connect("m", "hi", "s", "b")
    assert run(g, _registry()).value("s") == 11  # 5 + 6


def test_node_execution_error_carries_node_id():
    g = Graph().add("boom", f"{__name__}.boom", inputs={"x": 1})
    with pytest.raises(NodeExecutionError) as exc:
        run(g, _registry())
    assert exc.value.node_id == "boom"
    assert isinstance(exc.value.__cause__, ValueError)


def test_run_cycle():
    g = Graph().add("a", f"{__name__}.inc").add("b", f"{__name__}.inc")
    g.connect("a", "result", "b", "x")
    g.connect("b", "result", "a", "x")
    with pytest.raises(CycleError):
        run(g, _registry())


# -- to_python -------------------------------------------------------------


def test_emit_positional_only():
    g = Graph().add("d", f"{__name__}.diff", inputs={"a": 10, "b": 3})
    script = to_python(g, _registry(), header=False)
    assert "_d = diff(10, 3)" in script


def test_emit_aliases_colliding_imports():
    reg = NodeRegistry()

    def one(values: list = None) -> float:
        return sum(values)

    def two(values: list = None) -> float:
        return sum(values)

    reg.register(one, module="pkg_a", qualname="total")
    reg.register(two, module="pkg_b", qualname="total")
    g = Graph().add("x", "pkg_a.total").add("y", "pkg_b.total")
    g.connect("x", "result", "y", "values")
    script = to_python(g, reg)
    assert "from pkg_a import total\n" in script
    assert "from pkg_b import total as total_2" in script
    assert "_y = total_2(values=_x)" in script


def test_exported_python_reproduces_result():
    reg = NodeRegistry()
    reg.register(inc, module="builtins_shim", qualname="inc")
    reg.register(add, module="builtins_shim", qualname="add")
    g = Graph().add("a", "builtins_shim.inc", inputs={"x": 1}).add("b", "builtins_shim.inc").add("c", "builtins_shim.add")
    g.connect("a", "result", "b", "x")
    g.connect("a", "result", "c", "a")
    g.connect("b", "result", "c", "b")

    script = to_python(g, reg, header=False)
    # Execute without the (fake) module by injecting the callables and dropping imports.
    body = "\n".join(ln for ln in script.splitlines() if not ln.startswith("from "))
    namespace = {"inc": inc, "add": add}
    exec(compile(body, "<exported>", "exec"), namespace)  # noqa: S102 - trusted, generated
    assert namespace["_c"] == run(g, reg).value("c") == (2 + 3)


# -- generic topological sort ----------------------------------------------


def test_toposort_orders_and_is_stable():
    nodes = ["a", "b", "c", "d"]
    edges = [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")]
    order = topological_sort(nodes, edges)
    assert order.index("a") < order.index("b") < order.index("d")
    assert order.index("a") < order.index("c") < order.index("d")
    assert topological_sort(nodes, edges) == order  # deterministic


def test_toposort_parallel_edges_collapse():
    assert topological_sort(["a", "b"], [("a", "b"), ("a", "b")]) == ["a", "b"]


def test_toposort_self_loop_and_cycle():
    with pytest.raises(CycleError):
        topological_sort(["a"], [("a", "a")])
    with pytest.raises(CycleError):
        topological_sort(["a", "b"], [("a", "b"), ("b", "a")])


def test_toposort_disconnected_and_empty():
    assert set(topological_sort(["a", "b", "c"], [])) == {"a", "b", "c"}
    assert topological_sort([], []) == []
