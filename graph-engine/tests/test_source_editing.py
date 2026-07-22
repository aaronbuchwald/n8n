"""Tests for source-tree editing (stream E / ADR 0004 D2): the server edits the
real ``.py`` files — node bodies via ``PUT /api/source/{id}``, wiring via
``PUT /api/graph`` — with branch reporting on ``GET /api/workspace``.

Every test operates on a TEMP COPY of ``examples/minimal/minimal.py`` (its own
module name, its own git repo, its own workspace root), so the real example is
never touched.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
import textwrap
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine import DEFAULT_REGISTRY
from server import create_app
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
    """A temp copy of the minimal example: own module, git repo, workspace."""
    name = f"minimal_{uuid.uuid4().hex[:8]}"
    module_file = tmp_path / f"{name}.py"
    module_file.write_text((EXAMPLE_DIR / "minimal.py").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "readings.csv").write_text((EXAMPLE_DIR / "readings.csv").read_text(encoding="utf-8"), encoding="utf-8")
    _git(tmp_path, "init", "-b", "edit-me")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "seed")

    sys.path.insert(0, str(tmp_path))
    importlib.import_module(name)
    workspace = Workspace(DEFAULT_REGISTRY, name, allowed_roots=[tmp_path])

    graph = workspace.parse_graph()
    for node in graph["nodes"]:
        if node["id"] == "values":  # absolute CSV path so /api/run works from any cwd
            node["inputs"]["path"] = str(tmp_path / "readings.csv")

    client = TestClient(create_app(DEFAULT_REGISTRY, graph, workspace=workspace))
    yield Sandbox(client=client, workspace=workspace, module_name=name, file=module_file, dir=tmp_path)

    sys.path.remove(str(tmp_path))
    sys.modules.pop(name, None)
    DEFAULT_REGISTRY.unregister_module(name)


# ----------------------------------------------------------------------
# A. current-branch reporting
# ----------------------------------------------------------------------


def test_workspace_reports_branch_and_module_path(sandbox: Sandbox):
    body = sandbox.client.get("/api/workspace").json()
    assert body["branch"] == "edit-me"
    assert body["detached"] is False
    assert body["commit"]
    assert body["modules"] == [
        {"module": sandbox.module_name, "path": f"{sandbox.module_name}.py"}
    ]


def test_workspace_handles_detached_head(sandbox: Sandbox):
    _git(sandbox.dir, "checkout", "--detach", "--quiet")
    body = sandbox.client.get("/api/workspace").json()
    assert body["branch"] is None
    assert body["detached"] is True


def test_workspace_without_a_bound_module_still_reports_a_branch():
    # No workspace configured: modules is empty but the response shape holds
    # (branch of the tree the server runs from, or null outside a repo).
    client = TestClient(create_app())
    body = client.get("/api/workspace").json()
    assert set(body) == {"branch", "detached", "commit", "modules"}
    assert body["modules"] == []


# ----------------------------------------------------------------------
# B. node-body editing
# ----------------------------------------------------------------------


def test_get_source_returns_the_exact_def(sandbox: Sandbox):
    spec_id = f"{sandbox.module_name}.average"
    body = sandbox.client.get(f"/api/source/{spec_id}").json()
    assert body["specId"] == spec_id
    assert body["path"] == f"{sandbox.module_name}.py"
    assert body["source"].startswith("@node\ndef average(")
    assert '"""Mean of the values."""' in body["source"]
    # The reported line range is exactly the def's span in the file.
    file_lines = sandbox.file.read_text(encoding="utf-8").splitlines(keepends=True)
    assert "".join(file_lines[body["startLine"] - 1 : body["endLine"]]) == body["source"]


def test_put_source_edits_the_real_file_and_run_uses_the_new_body(sandbox: Sandbox):
    spec_id = f"{sandbox.module_name}.average"
    before = sandbox.client.get(f"/api/source/{spec_id}").json()
    file_lines = sandbox.file.read_text(encoding="utf-8").splitlines(keepends=True)
    prefix = "".join(file_lines[: before["startLine"] - 1])
    suffix = "".join(file_lines[before["endLine"]:])

    new_source = textwrap.dedent('''\
        @node
        def average(values: list) -> float:
            """Mean of the values, doubled."""
            return 2 * sum(values) / len(values)
    ''')
    res = sandbox.client.put(f"/api/source/{spec_id}", json={"source": new_source})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["source"] == new_source
    assert body["spec"]["doc"] == "Mean of the values, doubled."
    assert body["graphErrors"] == []

    # Byte-for-byte preservation of everything outside the replaced def.
    after = sandbox.file.read_text(encoding="utf-8")
    assert after.startswith(prefix)
    assert after.endswith(suffix)

    # A fresh GET reflects the file, and /api/run executes the new body.
    assert sandbox.client.get(f"/api/source/{spec_id}").json()["source"] == new_source
    graph = sandbox.client.get("/api/graph").json()
    run = sandbox.client.post("/api/run", json={"graph": graph}).json()
    assert run["errors"] == []
    assert run["outputs"]["a"]["result"] == 50.0  # 25.0 doubled
    assert run["outputs"]["t"]["result"] == 100.0  # untouched node unchanged


def test_put_source_signature_change_is_reintrospected(sandbox: Sandbox):
    spec_id = f"{sandbox.module_name}.average"
    new_source = textwrap.dedent('''\
        @node
        def average(values: list, precision: int = 2) -> float:
            """Rounded mean."""
            return round(sum(values) / len(values), precision)
    ''')
    res = sandbox.client.put(f"/api/source/{spec_id}", json={"source": new_source})
    assert res.status_code == 200, res.text
    inputs = {i["name"]: i for i in res.json()["spec"]["inputs"]}
    assert set(inputs) == {"values", "precision"}
    assert inputs["precision"]["default"] == 2
    # The palette the app serves picked it up too.
    specs = sandbox.client.get("/api/specs").json()["specs"]
    assert {i["name"] for i in specs[spec_id]["inputs"]} == {"values", "precision"}


def test_put_source_rejects_unparseable_source_without_writing(sandbox: Sandbox):
    spec_id = f"{sandbox.module_name}.average"
    original = sandbox.file.read_text(encoding="utf-8")
    res = sandbox.client.put(f"/api/source/{spec_id}", json={"source": "def average(:\n"})
    assert res.status_code == 400
    assert "parse" in res.json()["message"]
    assert sandbox.file.read_text(encoding="utf-8") == original


def test_put_source_rejects_a_renamed_function(sandbox: Sandbox):
    spec_id = f"{sandbox.module_name}.average"
    original = sandbox.file.read_text(encoding="utf-8")
    res = sandbox.client.put(
        f"/api/source/{spec_id}",
        json={"source": "@node\ndef avg(values: list) -> float:\n    return 0.0\n"},
    )
    assert res.status_code == 400
    assert "'average'" in res.json()["message"]
    assert sandbox.file.read_text(encoding="utf-8") == original


def test_put_source_rejects_dropping_the_decorator(sandbox: Sandbox):
    spec_id = f"{sandbox.module_name}.average"
    res = sandbox.client.put(
        f"/api/source/{spec_id}",
        json={"source": "def average(values: list) -> float:\n    return 0.0\n"},
    )
    assert res.status_code == 400
    assert "@node" in res.json()["message"]


def test_source_endpoints_refuse_files_outside_the_workspace(sandbox: Sandbox):
    # A registered type whose module resolves to a file outside allowed_roots
    # (here: the stdlib) must never be readable or writable.
    import textwrap as tw

    DEFAULT_REGISTRY.register(tw.indent, module="textwrap", qualname="indent")
    try:
        res = sandbox.client.get("/api/source/textwrap.indent")
        assert res.status_code == 403
        res = sandbox.client.put(
            "/api/source/textwrap.indent",
            json={"source": "@node\ndef indent():\n    pass\n"},
        )
        assert res.status_code == 403
    finally:
        DEFAULT_REGISTRY.unregister_module("textwrap")


# ----------------------------------------------------------------------
# C. graph persistence — wiring write-back + round-trip
# ----------------------------------------------------------------------


def test_put_graph_rewrites_wiring_and_round_trips(sandbox: Sandbox):
    graph = sandbox.client.get("/api/graph").json()
    values = next(n for n in graph["nodes"] if n["id"] == "values")
    values["inputs"]["path"] = "other.csv"  # mutate a literal input

    res = sandbox.client.put("/api/graph", json={"graph": graph})
    assert res.status_code == 200, res.text
    saved = res.json()["graph"]

    # Round trip: the graph re-parsed from the rewritten module is equivalent.
    assert {n["id"] for n in saved["nodes"]} == {"values", "t", "a", "summary"}
    assert {n["id"]: n["inputs"] for n in saved["nodes"]} == {
        n["id"]: n["inputs"] for n in graph["nodes"]
    }
    assert {tuple(e.values()) for e in saved["edges"]} == {tuple(e.values()) for e in graph["edges"]}
    assert saved["output"] == graph["output"]
    # ...and it is what the server now serves.
    assert sandbox.client.get("/api/graph").json() == saved

    # The file: wiring updated, everything else preserved.
    text = sandbox.file.read_text(encoding="utf-8")
    assert "values = read_values(path='other.csv')" in text
    assert '"""Read the file, reduce it two ways, and render the result."""' in text
    assert "@main\ndef readings_report(path: str = \"readings.csv\") -> str:" in text
    assert "def total(values: list) -> float:" in text  # node bodies untouched
    assert "# -- nodes -----" in text  # comments untouched
    assert "return summary" in text

    # The rewritten module still runs end-to-end (with a runnable csv path).
    values["inputs"]["path"] = str(sandbox.dir / "readings.csv")
    run = sandbox.client.post("/api/run", json={"graph": graph}).json()
    assert run["errors"] == []
    assert run["outputs"]["summary"]["result"].startswith("<div")


def test_put_graph_writes_layout_to_sidecar_not_python(sandbox: Sandbox):
    graph = sandbox.client.get("/api/graph").json()
    for i, node in enumerate(graph["nodes"]):
        node["position"] = {"x": 100.0 * i, "y": 40.0}

    res = sandbox.client.put("/api/graph", json={"graph": graph})
    assert res.status_code == 200, res.text

    sidecar = sandbox.file.with_suffix(".layout.json")
    assert sidecar.exists()
    assert json.loads(sidecar.read_text(encoding="utf-8"))["summary"] == {"x": 300.0, "y": 40.0}
    assert "position" not in sandbox.file.read_text(encoding="utf-8")
    # Served graph merges the sidecar back in.
    served = sandbox.client.get("/api/graph").json()
    assert next(n for n in served["nodes"] if n["id"] == "values")["position"] == {"x": 0.0, "y": 40.0}


def test_put_graph_rejects_a_node_id_that_shadows_its_function(sandbox: Sandbox):
    graph = sandbox.client.get("/api/graph").json()
    original = sandbox.file.read_text(encoding="utf-8")
    for node in graph["nodes"]:
        if node["id"] == "t":
            node["id"] = "total"  # would shadow the function it calls
    for edge in graph["edges"]:
        for key in ("source", "target"):
            if edge[key] == "t":
                edge[key] = "total"

    res = sandbox.client.put("/api/graph", json={"graph": graph})
    assert res.status_code == 422
    assert "shadows" in res.text
    assert sandbox.file.read_text(encoding="utf-8") == original


def test_put_graph_rejects_types_from_other_modules(sandbox: Sandbox):
    def helper(x: int = 0) -> int:
        return x

    DEFAULT_REGISTRY.register(helper, module="elsewhere", qualname="helper")
    try:
        graph = sandbox.client.get("/api/graph").json()
        original = sandbox.file.read_text(encoding="utf-8")
        graph["nodes"].append(
            {"id": "extra", "type": "elsewhere.helper", "inputs": {"x": 1}, "position": None}
        )
        res = sandbox.client.put("/api/graph", json={"graph": graph})
        assert res.status_code == 422
        assert "elsewhere" in res.text
        assert sandbox.file.read_text(encoding="utf-8") == original
    finally:
        DEFAULT_REGISTRY.unregister_module("elsewhere")


def test_put_graph_without_workspace_stays_501():
    client = TestClient(create_app())
    assert client.put("/api/graph", json={"graph": {"version": "0.2.0", "nodes": [], "edges": [], "output": None}}).status_code == 501
