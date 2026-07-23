"""The force-vs-load (capacity_check) program is serveable + runnable in the app.

Proves the modular serving path (``--example capacity_check``): its ``@main`` is
straight-line so it parses through the graph⟷source bijection, it serves
pristine (relative CSV paths), and ``/api/run`` resolves both CSVs against the
program's own directory (``run_base_dir``) — the modular replacement for
per-example path lists — producing the PASS/FAIL card with no errors.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from server.app import create_app
from server.demo import example_dir, load_graph, make_workspace


def _capacity_client() -> TestClient:
    workspace = make_workspace("capacity_check")
    graph = load_graph("capacity_check", workspace)
    return TestClient(
        create_app(sample_graph=graph, workspace=workspace, run_base_dir=example_dir("capacity_check"))
    )


def test_capacity_check_serves_two_read_tables_pristine() -> None:
    client = _capacity_client()
    graph = client.get("/api/graph").json()
    reads = [n for n in graph["nodes"] if n["type"] == "table.read_table"]
    assert len(reads) == 2  # forces + members arcs
    # served pristine: relative filenames, no absolute machine path
    assert {n["inputs"]["path"] for n in reads} == {"forces.csv", "members.csv"}


def test_capacity_check_runs_to_a_verdict() -> None:
    client = _capacity_client()
    graph = client.get("/api/graph").json()
    result = client.post("/api/run", json={"graph": graph}).json()
    assert result["errors"] == []
    out = graph["output"]
    html = result["outputs"][out["node"]][out["socket"]]
    assert isinstance(html, str) and "<math" in html
    assert "PASS" in html or "FAIL" in html  # the separate check node's verdict


def test_capacity_check_node_source_is_reachable() -> None:
    client = _capacity_client()
    # a node whose type is defined in the example module itself
    r = client.get("/api/source/capacity_check.check_capacity")
    assert r.status_code == 200
    assert "def check_capacity" in r.json()["source"]
