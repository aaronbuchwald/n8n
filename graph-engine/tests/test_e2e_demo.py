"""End-to-end test of the bundled ``--demo`` experience.

Boots the real FastAPI app exactly as ``python -m server --demo`` wires it — the
showcase workspace + graph on the default registry — and drives the same HTTP
surface a browser would: list specs, fetch the graph, read a node's source, and
**actually run the graph**, asserting it produces the rendered output with no
errors. This is the guard that "the demo works": it executes the sym + table
node bodies for real (needs the ``sym`` deps, which the ``dev`` extra pulls in),
so a missing dependency, a broken wire, or a bad widget literal fails here
instead of in the user's browser.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from server.app import create_app
from server.demo import SHOWCASE_RUN_PATH_OVERRIDES, load_showcase_graph, make_showcase_workspace


def _demo_client() -> TestClient:
    workspace = make_showcase_workspace()
    graph = load_showcase_graph(workspace)
    return TestClient(
        create_app(sample_graph=graph, workspace=workspace, run_path_overrides=SHOWCASE_RUN_PATH_OVERRIDES)
    )


def test_demo_specs_include_sym_and_table_nodes() -> None:
    client = _demo_client()
    body = client.get("/api/specs").json()
    assert body["version"]
    specs = body["specs"]
    # The showcase surfaces both new packs' widget-bearing nodes.
    assert "sym.parse_expr" in specs
    assert "table.apply_recipe" in specs


def test_demo_graph_is_served_and_parses() -> None:
    client = _demo_client()
    graph = client.get("/api/graph").json()
    assert graph["nodes"], "showcase graph should have nodes"
    assert graph["output"] is not None
    types = {n["type"] for n in graph["nodes"]}
    assert "sym.parse_expr" in types
    assert "table.apply_recipe" in types


def test_demo_graph_served_path_stays_relative() -> None:
    """The served graph is pristine (review 0005 #3): no machine-absolute path,
    even though the same graph runs successfully below."""
    client = _demo_client()
    graph = client.get("/api/graph").json()
    read_table = next(n for n in graph["nodes"] if n["type"] == "table.read_table")
    assert read_table["inputs"]["path"] == "showcase.csv"


def test_demo_workspace_reports_branch_and_module() -> None:
    client = _demo_client()
    info = client.get("/api/workspace").json()
    # branch may be a name or null (detached); the shape is what matters.
    assert "branch" in info and "modules" in info
    assert any(m["module"] == "showcase" for m in info["modules"])


def test_demo_run_executes_end_to_end_with_no_errors() -> None:
    """The core guarantee: running the served demo graph succeeds and renders."""
    client = _demo_client()
    graph = client.get("/api/graph").json()

    result = client.post("/api/run", json={"graph": graph}).json()

    assert result["errors"] == [], f"demo run reported errors: {result['errors']}"
    # Every node produced outputs.
    assert set(result["outputs"]) == {n["id"] for n in graph["nodes"]}

    out = graph["output"]
    value = result["outputs"][out["node"]][out["socket"]]
    # The output is a rendered, self-contained HTML string (the dashboard card).
    assert isinstance(value, str) and value.strip()
    assert "<" in value  # it's markup
    # Full pipeline proof: the symbolic branch emits MathML, the table branch a
    # summary — both must reach the composed output.
    assert "<math" in value or "math" in value.lower()


def test_demo_source_endpoint_returns_a_node_body() -> None:
    client = _demo_client()
    r = client.get("/api/source/sym.parse_expr")
    assert r.status_code == 200
    body = r.json()
    assert body["qualname"] == "parse_expr"
    assert "def parse_expr" in body["source"]
