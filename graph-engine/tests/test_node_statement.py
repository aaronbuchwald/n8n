"""Read-only call-site statement route (ADR 0015 D2).

``GET /api/nodes/{node_id}/statement`` (unscoped, default entry) and
``GET /api/graphs/{entry_id}/nodes/{node_id}/statement`` (scoped) return a
node's actual ``@main`` call-site statement as the **real file bytes** —
``{nodeId, path, startLine, endLine, source}`` — located by the same AST line
span the wiring write-back uses. Read-only: no mutation, no module reload.

Both surfaces are exercised: the unscoped alias over a legacy single-slot
workspace (a temp copy of the minimal example) and the scoped route over an
entry catalog. Every test runs against its own temp module, so no real example
is touched.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine import DEFAULT_REGISTRY, ENTRY_POINTS
from server import create_app
from server.entries import EntryCatalog
from server.workspace import Workspace

EXAMPLE_DIR = Path(__file__).resolve().parents[1] / "examples" / "minimal"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
        cwd=cwd, check=True, capture_output=True,
    )


@dataclass
class Sandbox:
    client: TestClient
    workspace: Workspace
    module_name: str
    file: Path
    dir: Path


@pytest.fixture()
def sandbox(tmp_path: Path):
    """A temp copy of the minimal example: own module, git repo, workspace.

    Wired to the UNSCOPED routes (legacy single-slot, no catalog), so this
    fixture exercises ``GET /api/nodes/{id}/statement``.
    """
    name = f"minimal_{uuid.uuid4().hex[:8]}"
    module_file = tmp_path / f"{name}.py"
    module_file.write_text(
        (EXAMPLE_DIR / "minimal.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "readings.csv").write_text(
        (EXAMPLE_DIR / "readings.csv").read_text(encoding="utf-8"), encoding="utf-8"
    )
    _git(tmp_path, "init", "-b", "edit-me")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "seed")

    sys.path.insert(0, str(tmp_path))
    importlib.import_module(name)
    workspace = Workspace(DEFAULT_REGISTRY, name, allowed_roots=[tmp_path])

    graph = workspace.parse_graph()
    client = TestClient(create_app(DEFAULT_REGISTRY, graph, workspace=workspace))
    yield Sandbox(
        client=client, workspace=workspace, module_name=name, file=module_file, dir=tmp_path
    )

    sys.path.remove(str(tmp_path))
    sys.modules.pop(name, None)
    DEFAULT_REGISTRY.unregister_module(name)


# ----------------------------------------------------------------------
# unscoped route (default entry) — byte-match + span
# ----------------------------------------------------------------------


def test_statement_returns_real_file_bytes_and_span(sandbox: Sandbox):
    # `summary = render_summary(total=t, average=a)` is the node id `summary`'s
    # call site in the minimal example's @main body.
    body = sandbox.client.get("/api/nodes/summary/statement").json()
    assert body["nodeId"] == "summary"
    assert body["path"] == f"{sandbox.module_name}.py"
    assert body["source"].strip() == "summary = render_summary(total=t, average=a)"

    # The reported span byte-matches the real statement bytes in the file.
    file_lines = sandbox.file.read_text(encoding="utf-8").splitlines(keepends=True)
    assert "".join(file_lines[body["startLine"] - 1 : body["endLine"]]) == body["source"]


def test_statement_resolves_every_node_in_the_body(sandbox: Sandbox):
    expected = {
        "values": "values = read_values(path)",
        "t": "t = total(values)",
        "a": "a = average(values)",
        "summary": "summary = render_summary(total=t, average=a)",
    }
    for node_id, line in expected.items():
        body = sandbox.client.get(f"/api/nodes/{node_id}/statement").json()
        assert body["source"].strip() == line, node_id


def test_statement_404s_for_an_unknown_node(sandbox: Sandbox):
    res = sandbox.client.get("/api/nodes/no_such_node/statement")
    assert res.status_code == 404
    assert "no_such_node" in res.json()["message"]


def test_statement_is_read_only(sandbox: Sandbox):
    """The route mutates nothing: the file is byte-identical after the read."""
    before = sandbox.file.read_text(encoding="utf-8")
    sandbox.client.get("/api/nodes/summary/statement")
    assert sandbox.file.read_text(encoding="utf-8") == before


# ----------------------------------------------------------------------
# scoped route (entry catalog)
# ----------------------------------------------------------------------

ENTRY = "stmtroute_alpha"
ENTRY_SOURCE = '''\
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


@pytest.fixture()
def scoped_client(tmp_path: Path):
    root = tmp_path / "entries"
    directory = root / ENTRY
    directory.mkdir(parents=True)
    (directory / f"{ENTRY}.py").write_text(ENTRY_SOURCE, encoding="utf-8")

    catalog = EntryCatalog(roots=[root], default=ENTRY).discover()
    yield TestClient(create_app(registry=DEFAULT_REGISTRY, web_dist=None, catalog=catalog))

    sys.modules.pop(ENTRY, None)
    ENTRY_POINTS.unregister_module(ENTRY)
    DEFAULT_REGISTRY.unregister_module(ENTRY)
    entry_dir = str(root / ENTRY)
    if entry_dir in sys.path:
        sys.path.remove(entry_dir)


def test_scoped_statement_returns_the_call_site(scoped_client: TestClient):
    body = scoped_client.get(f"/api/graphs/{ENTRY}/nodes/doubled/statement").json()
    assert body["nodeId"] == "doubled"
    assert body["source"].strip() == "doubled = double(x)"
    assert body["path"].endswith(f"{ENTRY}/{ENTRY}.py")


def test_scoped_statement_404s_for_an_unknown_node(scoped_client: TestClient):
    res = scoped_client.get(f"/api/graphs/{ENTRY}/nodes/nope/statement")
    assert res.status_code == 404


def test_unscoped_alias_serves_the_default_entry(scoped_client: TestClient):
    """With a catalog, the unscoped route aliases the default entry (ADR 0009 D4)."""
    body = scoped_client.get("/api/nodes/doubled/statement").json()
    assert body["source"].strip() == "doubled = double(x)"
