"""Engine-level tests for the dynamic-spec seam (ADR 0007).

Covers the parts owned by stream E — independent of the ``sym`` pack:

* ``DerivedInputs`` + ``effective_inputs`` (static sockets + derived entries);
* the ``**kwargs``-only-on-dynamic-nodes signature rule at import time;
* a dynamic node's **effective inputs** computed once in bind;
* required-with-no-default fails to bind loudly (naming the symbol) while
  optional-with-default binds unsatisfied and uses the default (ADR 0007 #5);
* the deriving param wired → ``BindError`` (D2);
* execution passing derived kwargs through the ``VAR_KEYWORD`` receptacle (D6);
* the programmatic-tracing path flattening derived kwargs into edges (D6).
"""

from __future__ import annotations

import pytest

from engine import (
    BindError,
    DerivedInputs,
    EngineError,
    Graph,
    NodeRegistry,
    UserError,
    bind,
    effective_inputs,
    main,
    node,
    node_spec,
    run,
)


def _entry(name: str, *, required: bool = True, default=None) -> dict:
    return {
        "name": name,
        "type": "float",
        "kind": "keywordOnly",
        "required": required,
        "default": default,
        "widget": {"kind": "number", "subtype": "float"},
        "derived": True,
    }


def _derive_required(value) -> list[dict]:
    """Comma-separated names → one required derived socket each (no default)."""
    if not isinstance(value, str):
        raise UserError("value must be a string")
    return [_entry(n.strip()) for n in value.split(",") if n.strip()]


def _derive_optional(value) -> list[dict]:
    """Comma-separated names → optional derived sockets with a 0.0 default."""
    return [_entry(n.strip(), required=False, default=0.0) for n in str(value).split(",") if n.strip()]


# -- effective_inputs + the signature rule ----------------------------------


def test_effective_inputs_appends_derived_after_static():
    def dyn(names: str = "", **fields) -> dict:
        return dict(fields)

    spec = node_spec(dyn, module="t", qualname="dyn", dynamic=DerivedInputs("names", _derive_required))
    got = effective_inputs(spec, DerivedInputs("names", _derive_required), {"names": "a,b"})
    assert [i["name"] for i in got] == ["names", "a", "b"]
    assert all(i["derived"] for i in got[1:])
    # non-dynamic: just the static inputs
    assert effective_inputs(spec, None, {"names": "a,b"}) == spec["inputs"]


def test_dynamic_node_requires_var_keyword_receptacle():
    def no_kwargs(names: str = "") -> dict:
        return {}

    with pytest.raises(EngineError, match="kwargs receptacle"):
        node_spec(no_kwargs, module="t", qualname="nk", dynamic=DerivedInputs("names", _derive_required))


def test_var_keyword_rejected_without_dynamic():
    def plain(x: int = 0, **rest) -> int:
        return x

    with pytest.raises(EngineError, match=r"\*\*kwargs"):
        node_spec(plain, module="t", qualname="plain")


def test_dynamic_param_must_be_a_declared_parameter():
    def dyn(names: str = "", **fields) -> dict:
        return dict(fields)

    with pytest.raises(EngineError, match="not a declared parameter"):
        node_spec(dyn, module="t", qualname="dyn2", dynamic=DerivedInputs("ghost", _derive_required))


def test_spec_carries_additive_dynamic_marker():
    def dyn(names: str = "", **fields) -> dict:
        return dict(fields)

    spec = node_spec(dyn, module="t", qualname="dyn3", dynamic=DerivedInputs("names", _derive_required))
    assert spec["dynamicInputs"] == {"param": "names"}
    # the **kwargs receptacle is not itself a socket
    assert "fields" not in {i["name"] for i in spec["inputs"]}


# -- bind: effective inputs + required/optional enforcement -----------------


@pytest.fixture
def reg() -> NodeRegistry:
    registry = NodeRegistry()

    def widget_sum(names: str = "", **fields) -> float:
        return sum(fields.values())

    def widget_opt(names: str = "", **fields) -> float:
        return sum(fields.values())

    registry.register(widget_sum, module="t", qualname="widget_sum",
                      dynamic=DerivedInputs("names", _derive_required))
    registry.register(widget_opt, module="t", qualname="widget_opt",
                      dynamic=DerivedInputs("names", _derive_optional))
    return registry


def test_bind_computes_effective_inputs_once(reg):
    g = Graph()
    g.add("n", "t.widget_sum", inputs={"names": "a,b", "a": 1.0, "b": 2.0})
    bound = bind(g, reg)
    node = bound.by_id["n"]
    assert [i["name"] for i in node.inputs_spec] == ["names", "a", "b"]


def test_required_derived_socket_with_no_default_fails_to_bind_loudly(reg):
    g = Graph()
    g.add("n", "t.widget_sum", inputs={"names": "a,b", "a": 1.0})  # 'b' unsatisfied
    with pytest.raises(BindError, match="'b'"):
        bind(g, reg)


def test_optional_derived_socket_with_default_binds_and_uses_default(reg):
    g = Graph()
    g.add("n", "t.widget_opt", inputs={"names": "a,b", "a": 5.0})  # 'b' unsatisfied
    result = run(g, reg)
    # 'b' uses its 0.0 default; a=5.0 → sum is 5.0, not an error.
    assert result.value("n") == 5.0


def test_a_freshly_derived_symbol_defaults_to_required(reg):
    # Editing the "equation" to add a symbol yields a new required socket that
    # is not silently zero: adding 'c' with no value fails to bind naming it.
    g = Graph()
    g.add("n", "t.widget_sum", inputs={"names": "a,c", "a": 1.0})
    with pytest.raises(BindError, match="'c'"):
        bind(g, reg)


# -- D2: the deriving param must be a literal, never wired ------------------


def test_deriving_param_wired_is_rejected(reg):
    def make_names() -> str:
        return "a"

    reg.register(make_names, module="t", qualname="make_names")
    g = Graph()
    g.add("src", "t.make_names")
    g.add("n", "t.widget_sum", inputs={"a": 1.0})
    g.connect("src", "result", "n", "names")  # wiring the deriving param
    with pytest.raises(BindError, match="deriving input 'names'.*not wired"):
        bind(g, reg)


# -- D6: execution + tracing pass derived kwargs through --------------------


def test_execute_passes_derived_kwargs_through_var_keyword(reg):
    g = Graph()
    g.add("n", "t.widget_sum", inputs={"names": "a,b", "a": 3.0, "b": 4.0})
    assert run(g, reg).value("n") == 7.0


# A dedicated registry + decorated node types for the tracing path. The
# derived-kwarg flattening in NodePrimitive.__call__ is what makes @main agree
# with the AST-parse path (ADR 0007 D6).
_TRACE_REG = NodeRegistry()


@node(registry=_TRACE_REG)
def source(v: float = 1.0) -> float:
    return v


@node(registry=_TRACE_REG, dynamic=DerivedInputs("names", _derive_required))
def widget_sum_traced(names: str = "", **fields) -> float:
    return sum(fields.values())


def test_tracing_flattens_derived_kwargs_into_edges():
    @main
    def flow():
        a = source()
        return widget_sum_traced(names="a,b", a=a, b=2.0)

    graph = flow.to_graph()
    dyn_node = next(n for n in graph.nodes if n.type.endswith("widget_sum_traced"))
    # 'a' is wired (an edge), 'b' is an inline literal, 'names' is the equation —
    # none of them buried inside a single `fields` dict.
    assert dyn_node.inputs.get("b") == 2.0
    assert dyn_node.inputs.get("names") == "a,b"
    assert "a" not in dyn_node.inputs  # 'a' is a wire, not a literal
    incoming = {e.target_input for e in graph.edges if e.target == dyn_node.id}
    assert "a" in incoming  # the derived symbol became a real wire

    # And it binds + runs against its own registry (a=1.0 default, b=2.0 → 3.0).
    assert run(graph, _TRACE_REG).value(dyn_node.id) == 3.0
