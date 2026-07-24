"""The capacity_check program is serveable + runnable in the app.

Proves the modular serving path (``--example capacity_check``): its ``@main`` is
straight-line so it parses through the graph⟷source bijection, it serves
pristine (relative CSV paths), and ``/api/run`` resolves both CSVs against the
program's own directory (``run_base_dir``) — the modular replacement for
per-example path lists — producing the calc card (its FAIL verdict being card
content, not a run error) with no errors.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from server.app import create_app
from server.demo import example_dir, load_graph, make_workspace


def _capacity_client() -> TestClient:
    workspace = make_workspace("capacity_check")
    graph = load_graph("capacity_check", workspace)
    return TestClient(
        create_app(sample_graph=graph, workspace=workspace, run_base_dir=example_dir("capacity_check"))
    )


def test_capacity_check_serves_two_csv_reads_pristine() -> None:
    client = _capacity_client()
    graph = client.get("/api/graph").json()
    reads = [n for n in graph["nodes"] if n["type"] == "sources.read_csv"]
    assert len(reads) == 2  # forces + members arcs
    # served pristine: relative filenames, no absolute machine path
    assert {n["inputs"]["path"] for n in reads} == {"forces.csv", "members.csv"}
    # each read names the column it pulls
    assert {n["inputs"]["column"] for n in reads} == {"force", "capacity"}


def test_capacity_check_serves_the_authored_node_ids() -> None:
    """Node id = the ``@main`` variable name (ADR 0004 D3) — five of them."""
    client = _capacity_client()
    graph = client.get("/api/graph").json()
    assert [n["id"] for n in graph["nodes"]] == ["forces", "members", "F_max", "C_min", "card"]
    assert graph["output"] == {"node": "card", "socket": "result"}


def test_capacity_check_runs_to_a_rendered_verdict() -> None:
    client = _capacity_client()
    graph = client.get("/api/graph").json()
    result = client.post("/api/run", json={"graph": graph}).json()
    assert result["errors"] == []
    out = graph["output"]
    html = result["outputs"][out["node"]][out["socket"]]
    assert isinstance(html, str) and "<math" in html
    # The computed values and both verdicts are on the card…
    assert '<span class="val">0.571</span>' in html
    assert "57.1 &lt; 100 = True" in html and "57.1 &lt; 50 = False" in html
    assert 'badge--pass">PASS' in html and 'badge--fail">FAIL' in html
    # …and the failing check did NOT redden the run: errors is empty above.
    assert "Overall <b>FAIL</b>" in html



def test_calc_card_derives_its_symbol_sockets_from_the_formulas() -> None:
    """The formulas' free symbols are served as derived inputs (ADR 0007)."""
    client = _capacity_client()
    graph = client.get("/api/graph").json()
    formulas = next(
        n["inputs"]["formulas"] for n in graph["nodes"] if n["type"] == "sheet.calc_card"
    )
    r = client.post("/api/specs/sheet.calc_card/derive", json={"value": formulas})
    assert r.status_code == 200
    derived = r.json()["inputs"]
    assert [i["name"] for i in derived] == ["F_max", "C_min"]
    assert all(i["derived"] is True for i in derived)


def test_capacity_check_node_source_is_reachable() -> None:
    client = _capacity_client()
    # the pack node the graph's card is an instance of
    r = client.get("/api/source/sheet.calc_card")
    assert r.status_code == 200
    assert "def calc_card" in r.json()["source"]
