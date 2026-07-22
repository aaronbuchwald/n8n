"""Node-declared UI widget seam — Stream A of ADR 0005 (Part A, A-D1…A-D6).

Proves the *contract-defining* half in Python:

* :class:`engine.Widget` serialises to the frozen ``{kind, config?}`` wire shape,
  with an import-time (not save-time) JSON guard;
* ``@node(widgets={...})`` threads that declaration into each input spec's
  existing ``widget`` field (additive, no schema bump), overriding the
  type-derived widget and leaving undeclared inputs untouched;
* a ``widgets`` key naming no parameter fails at import, like every spec-layer
  typo;
* the schema tolerates ``config`` and rejects malformed widgets;
* the seam is proven end-to-end: a demo node declares a widget, the edited value
  rides an ordinary literal through the Graph ⟷ composite bijection (ADR 0004),
  round-tripping char-for-char via ``repr`` / ``ast.literal_eval``.
"""

from __future__ import annotations

import ast

import pytest

from engine import (
    EngineError,
    Graph,
    NodeRegistry,
    SchemaError,
    Widget,
    from_composite,
    node_spec,
    to_composite,
    validate_node_spec,
)


# -- the demo widget node: one input carries a declared "text" widget -------
#
# The demo kind is "text" (a built-in editor on the JS side). The declaration
# adds config the type-derived widget could never carry, proving config threads
# through untouched. The node body stays the authority at run (A-D5); the widget
# only declares a contract.


def greet(name: str = "world", shout: bool = False) -> str:
    """Return a greeting. ``name`` is edited through the declared text widget."""
    text = f"hello, {name}"
    return text.upper() if shout else text


DEMO_WIDGETS = {"name": Widget("text", placeholder="type a name", maxLength=40)}


@pytest.fixture
def demo_registry() -> NodeRegistry:
    reg = NodeRegistry()
    reg.register(greet, widgets=DEMO_WIDGETS)
    return reg


def _input(spec: dict, name: str) -> dict:
    return next(i for i in spec["inputs"] if i["name"] == name)


# -- Widget value object (A-D2) --------------------------------------------


def test_widget_to_dict_kind_only():
    assert Widget("text").to_dict() == {"kind": "text"}


def test_widget_to_dict_with_config():
    assert Widget("math", syntax="sympy").to_dict() == {
        "kind": "math",
        "config": {"syntax": "sympy"},
    }


def test_widget_config_guarded_at_construction_time():
    # Non-JSON config fails when the Widget is built (import time), not at save.
    with pytest.raises(TypeError):
        Widget("bad", value={1, 2, 3})  # a set is not JSON-serialisable


# -- threading into the input spec (A-D2 / A-D3) ---------------------------


def test_declared_widget_serialises_to_kind_config_shape():
    spec = node_spec(greet, widgets=DEMO_WIDGETS)
    assert _input(spec, "name")["widget"] == {
        "kind": "text",
        "config": {"placeholder": "type a name", "maxLength": 40},
    }


def test_declared_widget_overrides_type_derived():
    # Without a declaration, str -> {"kind": "text"} with no config; the
    # declaration replaces that derived widget wholesale.
    derived = _input(node_spec(greet), "name")["widget"]
    assert derived == {"kind": "text"}
    declared = _input(node_spec(greet, widgets=DEMO_WIDGETS), "name")["widget"]
    assert declared["kind"] == "text" and "config" in declared


def test_undeclared_inputs_keep_type_derivation():
    spec = node_spec(greet, widgets=DEMO_WIDGETS)
    # 'shout' has no declaration -> still the bool-derived checkbox widget.
    assert _input(spec, "shout")["widget"] == {"kind": "checkbox"}


def test_widget_for_unknown_parameter_raises_at_import():
    with pytest.raises(EngineError, match="unknown parameter"):
        node_spec(greet, widgets={"nope": Widget("text")})


def test_declaration_lives_in_spec_not_graph(demo_registry: NodeRegistry):
    # The graph carries only the literal value, never the widget declaration.
    graph = Graph()
    graph.add("g", f"{__name__}.greet", inputs={"name": "Ada"})
    node = graph.to_dict()["nodes"][0]
    assert node["inputs"] == {"name": "Ada"}
    assert "widget" not in node and "widgets" not in node


# -- schema tolerance + validation (A-D3) ----------------------------------


def test_schema_accepts_widget_config():
    spec = node_spec(greet, widgets=DEMO_WIDGETS)
    assert validate_node_spec(spec) is spec


def test_schema_rejects_non_string_kind():
    spec = node_spec(greet)
    _input(spec, "name")["widget"] = {"kind": 123}
    with pytest.raises(SchemaError, match="string 'kind'"):
        validate_node_spec(spec)


def test_schema_rejects_non_object_config():
    spec = node_spec(greet)
    _input(spec, "name")["widget"] = {"kind": "text", "config": "nope"}
    with pytest.raises(SchemaError, match="'config' must be an object"):
        validate_node_spec(spec)


# -- end-to-end seam: value rides an ordinary literal (A-D5) ----------------


def test_widget_value_roundtrips_through_composite(demo_registry: NodeRegistry):
    graph = Graph()
    graph.add("g", f"{__name__}.greet", inputs={"name": "Ada Lovelace"})
    graph.output = {"node": "g", "socket": "result"}

    # Emit the wiring composite: the widget value is a plain literal in the call.
    source = to_composite(graph, demo_registry)
    assert "name='Ada Lovelace'" in source

    # And it parses straight back (the round-trip proof PUT /api/graph relies on).
    restored = from_composite(source, demo_registry)
    assert restored.to_dict()["nodes"][0]["inputs"] == {"name": "Ada Lovelace"}


def test_widget_literal_subset_survives_repr_literal_eval():
    # The literal-JSON subset (A-D5) is exactly what repr/ast.literal_eval
    # round-trips both ways — the constraint the widget seam commits under.
    for value in ["x**2 - 5*x + 6", 42, 3.5, True, None, ["a", 1], {"k": "v"}]:
        assert ast.literal_eval(repr(value)) == value
