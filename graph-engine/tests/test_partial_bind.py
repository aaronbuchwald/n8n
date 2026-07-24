"""Draft-tolerant (edit-mode) bind — ADR 0011 W1 / D6.

``bind(partial=True)`` tolerates a required input that is neither wired nor
given a literal, collecting a structured diagnostic instead of hard-failing, so
an in-progress draft graph can validate and be saved. Full ``bind`` is
unchanged (still a hard :class:`BindError`), and every *other* structural error
stays fatal even in partial mode.

Self-contained toy node types, mirroring ``test_engine.py``.
"""

from engine import (
    INCOMPLETE_INPUT,
    BindError,
    CycleError,
    Graph,
    NodeRegistry,
    bind,
    validate_edit,
)
import pytest


def inc(x: int = 0) -> int:
    return x + 1


def add(a: int, b: int) -> int:  # both required (no defaults)
    return a + b


def split(x: int = 0) -> dict:
    return {"lo": x, "hi": x + 1}


def _registry() -> NodeRegistry:
    reg = NodeRegistry()
    reg.register(inc)
    reg.register(add)
    reg.register(split, outputs=["lo", "hi"])
    return reg


# -- full bind is unchanged: still hard-fails ------------------------------


def test_full_bind_still_hard_fails_on_missing_required():
    g = Graph().add("s", f"{__name__}.add")  # add(a, b): both required, unset
    with pytest.raises(BindError, match="required") as exc:
        bind(g, _registry())
    assert exc.value.node_id == "s"
    assert exc.value.edge is None


def test_full_bind_default_has_empty_incomplete():
    # A *complete* graph: incomplete is present but empty under a normal bind.
    g = Graph().add("a", f"{__name__}.inc", inputs={"x": 1})
    bound = bind(g, _registry())
    assert bound.incomplete == []


# -- partial bind tolerates + reports missing required inputs --------------


def test_partial_bind_tolerates_missing_required_input():
    g = Graph().add("s", f"{__name__}.add")  # both a, b unset
    bound = bind(g, _registry(), partial=True)  # does not raise
    assert [d["input"] for d in bound.incomplete] == ["a", "b"]
    for diag in bound.incomplete:
        assert diag["code"] == INCOMPLETE_INPUT
        assert diag["nodeId"] == "s"
        assert "required" in diag["message"]
        assert "edge" not in diag  # input-scoped, not edge-scoped


def test_partial_bind_partially_wired_node_reports_only_the_gap():
    # a is wired from inc; b is left open -> only b is incomplete.
    g = (
        Graph()
        .add("src", f"{__name__}.inc", inputs={"x": 1})
        .add("s", f"{__name__}.add")
    )
    g.connect("src", "result", "s", "a")
    bound = bind(g, _registry(), partial=True)
    assert [(d["nodeId"], d["input"]) for d in bound.incomplete] == [("s", "b")]


def test_partial_bind_literal_satisfied_input_is_not_incomplete():
    g = Graph().add("s", f"{__name__}.add", inputs={"a": 1, "b": 2})
    bound = bind(g, _registry(), partial=True)
    assert bound.incomplete == []


def test_partial_bind_optional_input_is_never_incomplete():
    # inc(x=0): x is optional -> an empty draft node reports nothing.
    g = Graph().add("a", f"{__name__}.inc")
    bound = bind(g, _registry(), partial=True)
    assert bound.incomplete == []


def test_partial_bind_diagnostics_are_deterministic_by_node_then_input():
    g = (
        Graph()
        .add("s1", f"{__name__}.add")
        .add("s2", f"{__name__}.add")
    )
    bound = bind(g, _registry(), partial=True)
    assert [(d["nodeId"], d["input"]) for d in bound.incomplete] == [
        ("s1", "a"),
        ("s1", "b"),
        ("s2", "a"),
        ("s2", "b"),
    ]


# -- partial mode softens ONLY the missing-required-input case -------------


def test_partial_bind_still_rejects_unknown_socket():
    g = (
        Graph()
        .add("a", f"{__name__}.inc", inputs={"x": 1})
        .add("b", f"{__name__}.inc")
    )
    g.connect("a", "ghost", "b", "x")  # unknown output socket
    with pytest.raises(BindError, match="ghost"):
        bind(g, _registry(), partial=True)


def test_partial_bind_still_rejects_double_wire():
    g = (
        Graph()
        .add("a", f"{__name__}.inc", inputs={"x": 1})
        .add("b", f"{__name__}.inc", inputs={"x": 2})
        .add("c", f"{__name__}.add")
    )
    g.connect("a", "result", "c", "a")
    g.connect("b", "result", "c", "a")  # second edge into the same input
    with pytest.raises(BindError, match="more than one edge"):
        bind(g, _registry(), partial=True)


def test_partial_bind_still_rejects_cycle():
    g = Graph().add("a", f"{__name__}.inc").add("b", f"{__name__}.inc")
    g.connect("a", "result", "b", "x")
    g.connect("b", "result", "a", "x")
    with pytest.raises(CycleError):
        bind(g, _registry(), partial=True)


def test_partial_bind_still_rejects_unknown_literal_param():
    g = Graph().add("a", f"{__name__}.inc", inputs={"nope": 1})
    with pytest.raises(BindError, match="not a"):
        bind(g, _registry(), partial=True)


# -- validate_edit convenience entry ---------------------------------------


def test_validate_edit_returns_the_incomplete_list():
    g = Graph().add("s", f"{__name__}.add")
    diags = validate_edit(g, _registry())
    assert [d["input"] for d in diags] == ["a", "b"]
    assert all(d["code"] == INCOMPLETE_INPUT for d in diags)


def test_validate_edit_empty_for_complete_graph():
    g = Graph().add("s", f"{__name__}.add", inputs={"a": 1, "b": 2})
    assert validate_edit(g, _registry()) == []


def test_validate_edit_still_raises_on_hard_error():
    g = Graph().add("a", "no.such.type")
    with pytest.raises(Exception):
        validate_edit(g, _registry())
