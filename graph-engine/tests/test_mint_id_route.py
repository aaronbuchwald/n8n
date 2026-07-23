"""``POST .../mint-id`` — server-assisted node-id minting (ADR 0011 W3 route).

The minting algorithm itself (snake_case, dedupe, the four collision classes)
is proven engine-side in ``tests/test_mint.py``; ``module_collision_set`` there
is exercised against raw source strings. These tests prove the *server* wiring:
that the route builds the collision set from the **live workspace's own
module** — its source, its module name, its current node ids — which is the
one piece of data a client cannot have on its own (ADR 0011 HD4), for both the
id-scoped route and the unscoped default-entry alias.
"""

from __future__ import annotations

import importlib
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import calc  # noqa: F401 — registers calc.* (a foreign module) on DEFAULT_REGISTRY
from engine import DEFAULT_REGISTRY, ENTRY_POINTS
from server import create_app
from server.entries import EntryCatalog
from server.workspace import Workspace

# A local node ("total") happens to share its short name with the unrelated
# calc.total; `average` is imported and already used once. Both set up real
# collisions that only someone who can read this module's source would know
# about — exactly the information a client posting `{"type": ...}` lacks.
FIXTURE_SOURCE = '''\
"""Fixture module for mint-id route tests."""

from __future__ import annotations

from calc import average

from engine import main, node


@node
def total(values: list) -> float:
    """A local node that happens to share its name with the unrelated calc.total."""
    return sum(values)


@main
def report() -> float:
    """One locally-defined node, one node from the calc pack."""
    t = total(values=[1, 2, 3])
    a = average(values=[4, 5, 6])
    return a


NODES = [total]
'''


@dataclass
class Sandbox:
    client: TestClient
    workspace: Workspace
    module_name: str


def _make_sandbox(tmp_path: Path) -> Sandbox:
    name = f"mintfixture_{uuid.uuid4().hex[:8]}"
    (tmp_path / f"{name}.py").write_text(FIXTURE_SOURCE, encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    importlib.import_module(name)
    workspace = Workspace(DEFAULT_REGISTRY, name, allowed_roots=[tmp_path])
    graph = workspace.parse_graph()
    client = TestClient(create_app(DEFAULT_REGISTRY, graph, workspace=workspace))
    return Sandbox(client=client, workspace=workspace, module_name=name)


@pytest.fixture()
def sandbox(tmp_path: Path):
    sb = _make_sandbox(tmp_path)
    yield sb
    sys.path.remove(str(tmp_path))
    sys.modules.pop(sb.module_name, None)
    DEFAULT_REGISTRY.unregister_module(sb.module_name)


# ----------------------------------------------------------------------
# unscoped alias (single-slot workspace)
# ----------------------------------------------------------------------


def test_mint_id_avoids_the_modules_own_call_name_shadow(sandbox: Sandbox):
    # Dropping a second node of the module's OWN local `total` type must not
    # mint "total" — that would shadow the call the composite already makes
    # (`t = total(...)`), the exact shadow `wiring_lines` rejects.
    res = sandbox.client.post(
        "/api/graph/mint-id", json={"type": f"{sandbox.module_name}.total"}
    )
    assert res.status_code == 200, res.text
    assert res.json() == {"id": "total_2"}


def test_mint_id_is_module_aware_across_a_same_named_foreign_type(sandbox: Sandbox):
    # calc.total's short name is also "total" — a client blindly minting from
    # the spec alone would not know this workspace already has an unrelated
    # local `total`. Only server-side knowledge of the module avoids it.
    res = sandbox.client.post("/api/graph/mint-id", json={"type": "calc.total"})
    assert res.status_code == 200, res.text
    assert res.json() == {"id": "total_2"}


def test_mint_id_avoids_an_already_imported_foreign_call_name(sandbox: Sandbox):
    # calc.average is already imported and used once (`a = average(...)`) —
    # dropping a second one must dedupe against the existing call, matching
    # HD4's canonical total/total_2 example.
    res = sandbox.client.post("/api/graph/mint-id", json={"type": "calc.average"})
    assert res.status_code == 200, res.text
    assert res.json() == {"id": "average_2"}


def test_mint_id_reserves_a_first_time_foreign_types_own_call_name(sandbox: Sandbox):
    # calc.median has never been imported/used in this module. Minting the
    # bare "median" would still be *safe* — write-back would alias the fresh
    # import (`from calc import median as median_2`) to dodge the self-shadow,
    # same as `test_placing_a_shadowing_foreign_type_aliases_its_import` in
    # test_writeback_fidelity.py — but that leaves an ugly aliased import.
    # Reserving the qualname up front (HD4's `extra`) bumps the *node id*
    # instead, keeping the import clean (`from calc import median`).
    res = sandbox.client.post("/api/graph/mint-id", json={"type": "calc.median"})
    assert res.status_code == 200, res.text
    assert res.json() == {"id": "median_2"}


def test_mint_id_unknown_type_404s(sandbox: Sandbox):
    res = sandbox.client.post("/api/graph/mint-id", json={"type": "no.such.type"})
    assert res.status_code == 404


def test_mint_id_rejects_a_missing_type_field(sandbox: Sandbox):
    res = sandbox.client.post("/api/graph/mint-id", json={})
    assert res.status_code == 400


def test_mint_id_without_workspace_stays_501():
    client = TestClient(create_app())
    assert client.post("/api/graph/mint-id", json={"type": "calc.total"}).status_code == 501


# ----------------------------------------------------------------------
# id-scoped route (entry catalog) + its unscoped alias
# ----------------------------------------------------------------------


@pytest.fixture()
def entry_client(tmp_path: Path):
    root = tmp_path / "entries"
    name = f"mintentry_{uuid.uuid4().hex[:8]}"
    directory = root / name
    directory.mkdir(parents=True)
    (directory / f"{name}.py").write_text(FIXTURE_SOURCE, encoding="utf-8")

    catalog = EntryCatalog(roots=[root], default=name).discover()
    client = TestClient(create_app(registry=DEFAULT_REGISTRY, web_dist=None, catalog=catalog))
    yield client, name

    sys.modules.pop(name, None)
    ENTRY_POINTS.unregister_module(name)
    DEFAULT_REGISTRY.unregister_module(name)
    entry_dir = str(directory)
    if entry_dir in sys.path:
        sys.path.remove(entry_dir)


def test_scoped_mint_id_uses_the_entrys_own_module(entry_client):
    client, name = entry_client
    res = client.post(f"/api/graphs/{name}/mint-id", json={"type": f"{name}.total"})
    assert res.status_code == 200, res.text
    assert res.json() == {"id": "total_2"}


def test_scoped_mint_id_unknown_entry_404s(entry_client):
    client, _name = entry_client
    res = client.post("/api/graphs/nope/mint-id", json={"type": "calc.total"})
    assert res.status_code == 404


def test_unscoped_mint_id_aliases_the_default_entry(entry_client):
    client, name = entry_client
    scoped = client.post(f"/api/graphs/{name}/mint-id", json={"type": "calc.average"})
    unscoped = client.post("/api/graph/mint-id", json={"type": "calc.average"})
    assert scoped.status_code == unscoped.status_code == 200
    assert scoped.json() == unscoped.json() == {"id": "average_2"}
