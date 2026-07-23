"""Node-declared whole-node rendering seam — engine seam of ADR 0010 (stream 10-E).

Proves the *contract-defining* half in Python:

* :class:`engine.Renderer` serialises to the frozen ``{kind, config?}`` wire
  shape, with an import-time (not save-time) JSON guard, mirroring
  :class:`engine.Widget`;
* ``@node(renderer=Renderer(kind, **config))`` threads that declaration into
  the node spec's top-level, additive ``renderer`` field;
* the ``socket`` config key is validated against the node's declared
  ``outputs=`` at import time: a nonexistent socket raises, an omitted socket
  defaults to the sole output (or ``result`` among several), and an
  irreducibly ambiguous omission (several outputs, no ``result``) raises;
* a spec that declares no renderer is byte-unchanged — no ``renderer`` key at
  all, no schema-version bump;
* ``engine.schema._validate_renderer`` accepts/rejects the right shapes,
  wired into ``validate_node_spec`` next to the widget check.
"""

from __future__ import annotations

import pytest

from engine import (
    EngineError,
    NodeRegistry,
    Renderer,
    SchemaError,
    Widget,
    node_spec,
    validate_node_spec,
)
from engine.schema import _validate_renderer


# -- demo nodes ---------------------------------------------------------------


def render_math_card(title: str = "Calculation", mathml: str = "") -> str:
    """Render a self-contained HTML card: title + MathML block."""
    return f"<div>{title}: {mathml}</div>"


def multi_output(x: int = 0) -> dict:
    """A node with two named outputs — no single-output default applies."""
    return {"a": x, "b": x + 1}


multi_output_spec_outputs = ["a", "b"]


def multi_output_with_result(x: int = 0) -> dict:
    """A multi-output node whose outputs happen to include 'result'."""
    return {"result": x, "extra": x + 1}


# -- Renderer value object (D1) ----------------------------------------------


def test_renderer_to_dict_kind_only():
    assert Renderer("html-card").to_dict() == {"kind": "html-card"}


def test_renderer_to_dict_with_config():
    assert Renderer("html-card", socket="result", height=220).to_dict() == {
        "kind": "html-card",
        "config": {"socket": "result", "height": 220},
    }


def test_renderer_config_guarded_at_construction_time():
    # Non-JSON config fails when the Renderer is built (import time), not save.
    with pytest.raises(TypeError):
        Renderer("html-card", value={1, 2, 3})  # a set is not JSON-serialisable


def test_renderer_open_vocabulary_namespaced_kind():
    # Pack kinds namespace (e.g. 'sym.plot'); core kinds stay flat.
    assert Renderer("sym.plot").to_dict() == {"kind": "sym.plot"}


# -- threading into the node spec (D1 / D2) ----------------------------------


def test_declared_renderer_serialises_to_kind_config_shape():
    spec = node_spec(render_math_card, renderer=Renderer("html-card", socket="result", height=220))
    assert spec["renderer"] == {
        "kind": "html-card",
        "config": {"socket": "result", "height": 220},
    }


def test_spec_without_renderer_has_no_renderer_key():
    # Additive: a spec that declares nothing is byte-unchanged, no schema bump.
    spec = node_spec(render_math_card)
    assert "renderer" not in spec


def test_renderer_lives_in_spec_only():
    # One declaration per node type, threaded into the spec — never a
    # per-instance/graph concern (that's the bijection's job to keep excluded).
    spec = node_spec(render_math_card, renderer=Renderer("html-card"))
    assert spec["renderer"] == {"kind": "html-card"}


# -- socket validation against outputs= (D1) ---------------------------------


def test_socket_defaults_to_sole_output_when_omitted():
    spec = node_spec(render_math_card, renderer=Renderer("html-card", height=220))
    assert spec["renderer"] == {"kind": "html-card", "config": {"height": 220}}


def test_socket_naming_declared_output_is_accepted():
    spec = node_spec(render_math_card, renderer=Renderer("html-card", socket="result"))
    assert spec["renderer"]["config"]["socket"] == "result"


def test_socket_naming_nonexistent_output_raises_at_import():
    with pytest.raises(EngineError, match="not a declared output"):
        node_spec(render_math_card, renderer=Renderer("html-card", socket="nope"))


def test_socket_defaults_to_result_with_multiple_outputs():
    spec = node_spec(
        multi_output_with_result,
        outputs=["result", "extra"],
        renderer=Renderer("html-card"),
    )
    assert spec["renderer"] == {"kind": "html-card"}


def test_socket_ambiguous_multi_output_without_result_raises():
    with pytest.raises(EngineError, match="pass socket=") :
        node_spec(multi_output, outputs=["a", "b"], renderer=Renderer("html-card"))


def test_socket_explicit_disambiguates_multi_output():
    spec = node_spec(
        multi_output, outputs=["a", "b"], renderer=Renderer("html-card", socket="b")
    )
    assert spec["renderer"]["config"]["socket"] == "b"


# -- registration end-to-end (registry.register threads renderer=) ----------


def test_registry_register_threads_renderer():
    reg = NodeRegistry()
    entry = reg.register(render_math_card, renderer=Renderer("html-card", height=220))
    assert entry.spec["renderer"] == {"kind": "html-card", "config": {"height": 220}}


def test_renderer_and_widgets_compose_independently():
    # Widgets live in socket rows, renderers below (D3) — a node can declare both.
    spec = node_spec(
        render_math_card,
        widgets={"title": Widget("text")},
        renderer=Renderer("html-card", socket="result"),
    )
    assert spec["inputs"][0]["widget"] == {"kind": "text"}
    assert spec["renderer"]["config"]["socket"] == "result"


# -- schema validation (D2) --------------------------------------------------


def test_schema_accepts_spec_without_renderer():
    spec = node_spec(render_math_card)
    assert validate_node_spec(spec) is spec


def test_schema_accepts_valid_renderer():
    spec = node_spec(render_math_card, renderer=Renderer("html-card", height=220))
    assert validate_node_spec(spec) is spec


def test_validate_renderer_accepts_null():
    _validate_renderer(None)  # does not raise


def test_validate_renderer_accepts_kind_only():
    _validate_renderer({"kind": "html-card"})  # does not raise


def test_validate_renderer_accepts_kind_and_config():
    _validate_renderer({"kind": "html-card", "config": {"height": 220}})  # does not raise


def test_validate_renderer_tolerates_unknown_keys():
    _validate_renderer({"kind": "html-card", "extra": "ignored"})  # does not raise


def test_schema_rejects_non_string_kind():
    spec = node_spec(render_math_card)
    spec["renderer"] = {"kind": 123}
    with pytest.raises(SchemaError, match="string 'kind'"):
        validate_node_spec(spec)


def test_schema_rejects_non_object_config():
    spec = node_spec(render_math_card)
    spec["renderer"] = {"kind": "html-card", "config": "nope"}
    with pytest.raises(SchemaError, match="'config' must be an object"):
        validate_node_spec(spec)


def test_schema_rejects_non_object_renderer():
    spec = node_spec(render_math_card)
    spec["renderer"] = "html-card"
    with pytest.raises(SchemaError, match="must be an object or null"):
        validate_node_spec(spec)
