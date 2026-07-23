"""``POST /api/graphs/validate`` edit mode (ADR 0011 W3, over W1's partial bind).

Route-level wiring only: the engine behaviour (``bind(partial=True)`` /
``validate_edit``) is proven in ``tests/test_partial_bind.py``. These tests
prove the HTTP surface: ``mode`` defaults to ``"run"`` (byte-for-byte the old
behaviour), ``mode: "edit"`` softens *only* the missing-required-input case into
a ``warnings`` array, and every other structural error still 422s in both
modes.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from engine import INCOMPLETE_INPUT, Graph, NodeRegistry
from server import create_app


def add(a: int, b: int) -> int:  # both required — no defaults
    return a + b


def inc(x: int = 0) -> int:
    return x + 1


@pytest.fixture()
def client() -> TestClient:
    reg = NodeRegistry()
    reg.register(add, module="calc", qualname="add")
    reg.register(inc, module="calc", qualname="inc")
    return TestClient(create_app(reg))


def _lonely_graph() -> dict:
    # add(a, b) with neither input wired nor given a literal.
    return Graph().add("s", "calc.add").to_dict()


# -- default / explicit run mode: unchanged hard-fail -----------------------


def test_default_mode_still_422s_on_missing_required_input(client):
    r = client.post("/api/graphs/validate", json={"graph": _lonely_graph()})
    assert r.status_code == 422
    body = r.json()
    assert body["ok"] is False
    assert "required" in body["errors"][0]["message"]
    assert body["errors"][0]["nodeId"] == "s"


def test_explicit_run_mode_still_422s(client):
    r = client.post("/api/graphs/validate", json={"graph": _lonely_graph(), "mode": "run"})
    assert r.status_code == 422
    assert r.json()["ok"] is False


def test_run_mode_ok_response_shape_is_byte_for_byte_unchanged(client):
    g = Graph().add("s", "calc.add", inputs={"a": 1, "b": 2}).to_dict()
    r = client.post("/api/graphs/validate", json={"graph": g})
    assert r.status_code == 200
    assert r.json() == {"ok": True}  # no `warnings` key leaks into run mode


# -- edit mode: tolerates + reports missing required inputs -----------------


def test_edit_mode_tolerates_missing_required_input(client):
    r = client.post(
        "/api/graphs/validate", json={"graph": _lonely_graph(), "mode": "edit"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert [d["input"] for d in body["warnings"]] == ["a", "b"]
    for diag in body["warnings"]:
        assert diag["code"] == INCOMPLETE_INPUT
        assert diag["nodeId"] == "s"
        assert "edge" not in diag  # input-scoped diagnostic, not edge-scoped


def test_edit_mode_partially_wired_node_reports_only_the_gap(client):
    g = Graph().add("src", "calc.inc", inputs={"x": 1}).add("s", "calc.add")
    g.connect("src", "result", "s", "a")
    r = client.post("/api/graphs/validate", json={"graph": g.to_dict(), "mode": "edit"})
    assert r.status_code == 200
    body = r.json()
    assert [(d["nodeId"], d["input"]) for d in body["warnings"]] == [("s", "b")]


def test_edit_mode_complete_graph_has_no_warnings(client):
    g = Graph().add("s", "calc.add", inputs={"a": 1, "b": 2}).to_dict()
    r = client.post("/api/graphs/validate", json={"graph": g, "mode": "edit"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "warnings": []}


# -- edit mode softens ONLY the missing-required-input case -----------------


def test_edit_mode_still_hard_fails_on_unknown_type(client):
    g = _lonely_graph()
    g["nodes"][0]["type"] = "calc.nope"
    r = client.post("/api/graphs/validate", json={"graph": g, "mode": "edit"})
    assert r.status_code == 422
    body = r.json()
    assert body["ok"] is False
    assert body["errors"][0]["code"] == "UnknownNodeType"


def test_edit_mode_still_hard_fails_on_bad_socket(client):
    g = (
        Graph()
        .add("a", "calc.inc", inputs={"x": 1})
        .add("b", "calc.inc", inputs={"x": 2})
    )
    g.connect("a", "ghost", "b", "x")
    r = client.post("/api/graphs/validate", json={"graph": g.to_dict(), "mode": "edit"})
    assert r.status_code == 422
    assert r.json()["ok"] is False


def test_edit_mode_still_hard_fails_on_double_wire(client):
    g = (
        Graph()
        .add("a", "calc.inc", inputs={"x": 1})
        .add("b", "calc.inc", inputs={"x": 2})
        .add("c", "calc.add", inputs={"b": 1})
    )
    g.connect("a", "result", "c", "a")
    g.connect("b", "result", "c", "a")  # second edge into the same input
    r = client.post("/api/graphs/validate", json={"graph": g.to_dict(), "mode": "edit"})
    assert r.status_code == 422
    assert "more than one edge" in r.json()["errors"][0]["message"]


def test_edit_mode_still_hard_fails_on_cycle(client):
    g = {
        "version": "0.2.0",
        "nodes": [
            {"id": "a", "type": "calc.inc", "inputs": {}},
            {"id": "b", "type": "calc.inc", "inputs": {}},
        ],
        "edges": [
            {"source": "a", "sourceOutput": "result", "target": "b", "targetInput": "x"},
            {"source": "b", "sourceOutput": "result", "target": "a", "targetInput": "x"},
        ],
        "output": None,
    }
    r = client.post("/api/graphs/validate", json={"graph": g, "mode": "edit"})
    assert r.status_code == 422
    assert r.json()["errors"][0]["code"] == "CycleError"


def test_unknown_mode_falls_back_to_run_semantics(client):
    # Not a documented value, but treated as run-mode rather than silently
    # accepted — a typo'd mode must not accidentally soften validation.
    r = client.post(
        "/api/graphs/validate", json={"graph": _lonely_graph(), "mode": "bogus"}
    )
    assert r.status_code == 422
    assert r.json()["ok"] is False
