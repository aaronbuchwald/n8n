"""Scoped entry routes + unscoped default aliases (ADR 0009 D4)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine import DEFAULT_REGISTRY, ENTRY_POINTS, SCHEMA_VERSION
from server import create_app
from server.entries import EntryCatalog

ALPHA = "eproute_alpha"
BETA = "eproute_beta"
BAD = "eproute_bad"

ALPHA_SOURCE = '''\
from engine import main, node


@node
def double(x: int = 1) -> int:
    return x * 2


@main
def alpha_report(x: int = 2) -> int:
    """Doubles a number."""
    doubled = double(x)
    return doubled
'''

BETA_SOURCE = '''\
from engine import main, node


@node
def shout(text: str = "hi") -> str:
    return text.upper()


@main
def beta_report(text: str = "hi") -> str:
    """Shouts a string."""
    shouted = shout(text)
    return shouted
'''

BAD_SOURCE = 'raise RuntimeError("cannot import this one")\n'


@pytest.fixture()
def client(tmp_path: Path):
    root = tmp_path / "entries"
    for name, source in ((ALPHA, ALPHA_SOURCE), (BETA, BETA_SOURCE), (BAD, BAD_SOURCE)):
        directory = root / name
        directory.mkdir(parents=True)
        (directory / f"{name}.py").write_text(source, encoding="utf-8")

    catalog = EntryCatalog(roots=[root], default=ALPHA).discover()
    yield TestClient(create_app(registry=DEFAULT_REGISTRY, web_dist=None, catalog=catalog))

    for name in (ALPHA, BETA, BAD):
        sys.modules.pop(name, None)
        ENTRY_POINTS.unregister_module(name)
        DEFAULT_REGISTRY.unregister_module(name)
        entry_dir = str(root / name)
        if entry_dir in sys.path:
            sys.path.remove(entry_dir)


def _listed(client: TestClient, entry_id: str) -> dict:
    entries = client.get("/api/graphs").json()["entries"]
    matches = [e for e in entries if e["id"] == entry_id]
    assert len(matches) == 1
    return matches[0]


def test_list_graphs_frozen_shape(client: TestClient):
    body = client.get("/api/graphs").json()
    assert body["version"] == SCHEMA_VERSION
    assert body["default"] == ALPHA

    alpha = _listed(client, ALPHA)
    assert alpha["status"] == "ok"
    assert alpha["qualname"] == "alpha_report"
    assert alpha["title"] == "Alpha report"
    assert alpha["path"].endswith(f"{ALPHA}/{ALPHA}.py")

    bad = _listed(client, BAD)
    assert bad["status"] == "error"
    assert "cannot import this one" in bad["error"]


def test_scoped_graph_serves_each_entry(client: TestClient):
    alpha = client.get(f"/api/graphs/{ALPHA}/graph").json()
    beta = client.get(f"/api/graphs/{BETA}/graph").json()
    assert alpha["nodes"][0]["type"] == f"{ALPHA}.double"
    assert beta["nodes"][0]["type"] == f"{BETA}.shout"


def test_unknown_entry_404_names_known_ids(client: TestClient):
    response = client.get("/api/graphs/nope/graph")
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert ALPHA in detail and BETA in detail


def test_broken_entry_409_carries_import_error(client: TestClient):
    response = client.get(f"/api/graphs/{BAD}/graph")
    assert response.status_code == 409
    assert "cannot import this one" in response.json()["detail"]


def test_scoped_run_uses_entry_registry(client: TestClient):
    graph = client.get(f"/api/graphs/{BETA}/graph").json()
    result = client.post(f"/api/graphs/{BETA}/run", json={"graph": graph}).json()
    assert result["errors"] == []
    assert result["outputs"]["shouted"]["result"] == "HI"


def test_unscoped_routes_alias_the_default_entry(client: TestClient):
    assert client.get("/api/graph").json() == client.get(f"/api/graphs/{ALPHA}/graph").json()

    graph = client.get("/api/graph").json()
    result = client.post("/api/run", json={"graph": graph}).json()
    assert result["errors"] == []
    assert result["outputs"]["doubled"]["result"] == 4


def test_scoped_put_graph_persists_and_reserves(client: TestClient):
    graph = client.get(f"/api/graphs/{BETA}/graph").json()
    for node in graph["nodes"]:
        if node["id"] == "shouted":
            node["inputs"]["text"] = "changed"
    saved = client.put(f"/api/graphs/{BETA}/graph", json={"graph": graph})
    assert saved.status_code == 200
    served = client.get(f"/api/graphs/{BETA}/graph").json()
    shouted = next(n for n in served["nodes"] if n["id"] == "shouted")
    assert shouted["inputs"]["text"] == "changed"
    # The other entry is untouched — workspaces coexist.
    alpha = client.get(f"/api/graphs/{ALPHA}/graph").json()
    assert alpha["nodes"][0]["type"] == f"{ALPHA}.double"


def test_scoped_source_roundtrip(client: TestClient):
    source = client.get(f"/api/graphs/{ALPHA}/source/{ALPHA}.double").json()
    assert source["qualname"] == "double"
    assert "x * 2" in source["source"]

    edited = source["source"].replace("x * 2", "x * 20")
    saved = client.put(
        f"/api/graphs/{ALPHA}/source/{ALPHA}.double", json={"source": edited}
    )
    assert saved.status_code == 200
    assert saved.json()["graphErrors"] == []
    assert "x * 20" in client.get(f"/api/graphs/{ALPHA}/source/{ALPHA}.double").json()["source"]


def test_workspace_lists_all_viewable_modules(client: TestClient):
    modules = {m["module"] for m in client.get("/api/workspace").json()["modules"]}
    assert {ALPHA, BETA} <= modules
    assert BAD not in modules
