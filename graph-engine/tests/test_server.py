"""Tests for the HTTP service (stream A2) — the engine over FastAPI."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from engine import Graph, NodeRegistry
from server import create_app


def total(values: list) -> float:
    return sum(values)


def average(values: list) -> float:
    return sum(values) / len(values)


def make(x: int = 0) -> list:
    return [x, x + 1, x + 2]


@pytest.fixture()
def client() -> TestClient:
    reg = NodeRegistry()
    reg.register(total, module="calc", qualname="total")
    reg.register(average, module="calc", qualname="average")
    reg.register(make, module="calc", qualname="make")
    return TestClient(create_app(reg))


def _graph() -> dict:
    g = Graph()
    g.add("src", "calc.make", inputs={"x": 10})
    g.add("avg", "calc.average")
    g.connect("src", "result", "avg", "values")
    g.output = {"node": "avg", "socket": "result"}
    return g.to_dict()


def test_specs_lists_registered_types(client):
    body = client.get("/api/specs").json()
    assert body["version"] == "0.2.0"
    assert set(body["specs"]) == {"calc.total", "calc.average", "calc.make"}


def test_validate_ok(client):
    r = client.post("/api/graphs/validate", json={"graph": _graph()})
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_validate_reports_bad_socket_with_nodeless_error(client):
    g = _graph()
    g["edges"][0]["sourceOutput"] = "ghost"
    r = client.post("/api/graphs/validate", json={"graph": g})
    assert r.status_code == 422
    assert r.json()["ok"] is False
    assert "output" in r.json()["errors"][0]["message"]


def test_run_returns_outputs(client):
    r = client.post("/api/run", json={"graph": _graph()}).json()
    assert r["outputs"]["avg"]["result"] == 11.0  # mean(10,11,12)
    assert r["output"] == {"node": "avg", "socket": "result"}
    assert r["errors"] == []


def test_run_node_error_carries_node_id(client):
    g = _graph()
    # average over an empty list -> ZeroDivisionError inside the node
    g["nodes"][0]["inputs"]["x"] = 0
    g["nodes"].append({"id": "empty", "type": "calc.average", "inputs": {"values": []}})
    g["edges"] = [{"source": "empty", "sourceOutput": "result", "target": "avg", "targetInput": "values"}]
    r = client.post("/api/run", json={"graph": g}).json()
    assert r["errors"] and r["errors"][0]["nodeId"] == "empty"


def test_export_returns_python(client):
    py = client.post("/api/export", json={"graph": _graph()}).json()["python"]
    assert "from calc import average" in py
    assert "_avg = average(values=_src)" in py


def test_source_endpoints_stubbed(client):
    assert client.get("/api/source/calc.total").status_code == 501
    assert client.put("/api/source/calc.total", json={}).status_code == 501


def test_malformed_graph_returns_422_not_500(client):
    # A non-dict node item must not escape as a TypeError → 500 (ADR 0002).
    bad = {"version": "0.2.0", "nodes": ["not-an-object"], "edges": []}
    r = client.post("/api/graphs/validate", json={"graph": bad})
    assert r.status_code == 422 and r.json()["ok"] is False
    assert client.post("/api/run", json={"graph": bad}).status_code == 422


def test_run_error_response_keeps_shape(client):
    g = _graph()
    g["nodes"].append({"id": "empty", "type": "calc.average", "inputs": {"values": []}})
    g["edges"] = [{"source": "empty", "sourceOutput": "result", "target": "avg", "targetInput": "values"}]
    r = client.post("/api/run", json={"graph": g}).json()
    assert set(r) == {"outputs", "order", "output", "errors"}  # output key present on failure


# -- GET /api/graph (the sample graph a client renders) --------------------


def test_graph_404_when_none_configured(client):
    # Default fixture builds the app without a sample graph.
    assert client.get("/api/graph").status_code == 404


def test_graph_returns_configured_sample():
    reg = NodeRegistry()
    reg.register(make, module="calc", qualname="make")
    reg.register(average, module="calc", qualname="average")
    app = create_app(reg, sample_graph=_graph())
    c = TestClient(app)
    r = c.get("/api/graph")
    assert r.status_code == 200
    assert r.json() == _graph()


def test_graph_accepts_a_graph_object():
    # create_app also accepts an engine Graph directly, not only its dict.
    reg = NodeRegistry()
    reg.register(make, module="calc", qualname="make")
    reg.register(average, module="calc", qualname="average")
    g = Graph()
    g.add("src", "calc.make", inputs={"x": 1})
    g.output = {"node": "src", "socket": "result"}
    c = TestClient(create_app(reg, sample_graph=g))
    assert c.get("/api/graph").json() == g.to_dict()


# -- the demo wiring: minimal example served end-to-end --------------------


@pytest.fixture()
def demo_client() -> TestClient:
    from engine import DEFAULT_REGISTRY

    from server.demo import load_minimal_graph

    graph = load_minimal_graph()  # imports minimal → registers minimal.* on DEFAULT_REGISTRY
    return TestClient(create_app(DEFAULT_REGISTRY, sample_graph=graph))


def test_demo_graph_types_all_present_in_specs(demo_client):
    specs = demo_client.get("/api/specs").json()["specs"]
    graph = demo_client.get("/api/graph").json()
    types = {n["type"] for n in graph["nodes"]}
    assert types == {"minimal.read_values", "minimal.total", "minimal.average", "minimal.render_summary"}
    assert types <= set(specs)  # every node type the sample graph uses exists in the palette


def test_demo_graph_validates_and_runs_to_html_card(demo_client):
    graph = demo_client.get("/api/graph").json()
    assert demo_client.post("/api/graphs/validate", json={"graph": graph}).status_code == 200
    result = demo_client.post("/api/run", json={"graph": graph}).json()
    assert result["errors"] == []
    out = result["output"]
    html = result["outputs"][out["node"]][out["socket"]]
    assert "Readings summary" in html
    assert "Total: <b>100</b>" in html and "Average: <b>25</b>" in html
