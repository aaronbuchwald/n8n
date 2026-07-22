"""The widget showcase (ADR 0005 integration): the demo the server serves and
its live editing seam, plus the ``engine.UserError`` the table pack re-points to.

Covers:

* ``engine.UserError`` exists, is an ``EngineError``, and is exactly what the
  ``table`` pack raises (it no longer defines its own).
* ``load_showcase_graph`` loads a graph whose node types are all in the served
  palette, binds, and runs end-to-end to one self-contained HTML card carrying
  BOTH the table and the symbolic outputs.
* A widget commit round-trips: ``PUT /api/graph`` on the showcase (which wires
  cross-pack ``table.*`` / ``sym.*`` nodes) rewrites the composite in place and
  re-serves the edited literal — the mechanism every widget edit rides (A-D5).
"""

from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine import DEFAULT_REGISTRY, EngineError, UserError, bind
from server import create_app
from server.workspace import Workspace

SHOWCASE_DIR = Path(__file__).resolve().parents[1] / "examples" / "showcase"


# -- engine.UserError ---------------------------------------------------------


def test_user_error_is_an_engine_error():
    assert issubclass(UserError, EngineError)
    err = UserError("bad input")
    assert isinstance(err, EngineError)
    assert str(err) == "bad input"


def test_table_pack_raises_engine_user_error():
    """The pack re-points to ``engine.UserError`` — no pack-local copy remains."""
    import table

    assert table.UserError is UserError
    with pytest.raises(UserError):
        table.apply_recipe({"columns": ["a"], "rows": [[1.0]]}, {"version": 99, "ops": []})
    # It is catchable as a plain engine error everywhere that already expects one.
    with pytest.raises(EngineError):
        table.apply_recipe({"columns": ["a"], "rows": [[1.0]]}, {"version": 1, "ops": [{"op": "nope"}]})


def test_table_errors_module_is_gone():
    with pytest.raises(ModuleNotFoundError):
        import table.errors  # noqa: F401


# -- the showcase demo graph, loaded / bound / run ----------------------------


def test_showcase_graph_types_are_all_in_the_palette():
    from server.demo import load_showcase_graph

    graph = load_showcase_graph()
    client = TestClient(create_app(DEFAULT_REGISTRY, sample_graph=graph, web_dist=None))
    specs = client.get("/api/specs").json()["specs"]
    types = {n["type"] for n in client.get("/api/graph").json()["nodes"]}
    assert {"table.read_table", "table.apply_recipe", "sym.parse_expr", "showcase.dashboard"} <= types
    assert types <= set(specs)  # every node type the demo uses exists in the palette


def test_showcase_graph_binds_and_runs_to_one_html_card():
    from server.demo import load_showcase_graph

    graph = load_showcase_graph()
    client = TestClient(create_app(DEFAULT_REGISTRY, sample_graph=graph, web_dist=None))

    assert client.post("/api/graphs/validate", json={"graph": graph}).status_code == 200
    result = client.post("/api/run", json={"graph": graph}).json()
    assert result["errors"] == []
    out = result["output"]
    html = result["outputs"][out["node"]][out["socket"]]
    # One card composing both chains: the table aggregate and the quadratic roots.
    assert "Sales by region" in html
    assert "Quadratic roots" in html
    # Self-contained: no external assets pulled in.
    assert "http://" not in html and "https://" not in html


def test_showcase_editable_widgets_are_declared_on_the_graph():
    """The graph carries the editable literals the widgets bind to (A-D5)."""
    from server.demo import load_showcase_graph

    by_type = {n["type"]: n for n in load_showcase_graph()["nodes"]}
    assert by_type["sym.parse_expr"]["inputs"]["text"] == "x**2 - 5*x + 6"
    assert by_type["table.apply_recipe"]["inputs"]["recipe"]["version"] == 1
    assert by_type["table.table_summary"]["inputs"]["title"] == "Sales by region"


# -- a widget commit round-trips through PUT /api/graph -----------------------


@pytest.fixture()
def showcase_sandbox(tmp_path: Path):
    """A temp copy of the showcase module + CSV, bound to its own workspace.

    Isolated so the ``PUT /api/graph`` rewrite (which reloads the module) never
    touches the repo's own ``showcase.py``.
    """
    name = f"showcase_{uuid.uuid4().hex[:8]}"
    module_file = tmp_path / f"{name}.py"
    shutil.copy(SHOWCASE_DIR / "showcase.py", module_file)
    shutil.copy(SHOWCASE_DIR / "showcase.csv", tmp_path / "showcase.csv")

    sys.path.insert(0, str(tmp_path))
    import importlib

    importlib.import_module(name)
    workspace = Workspace(DEFAULT_REGISTRY, name, allowed_roots=[tmp_path])

    graph = workspace.parse_graph()
    for node in graph["nodes"]:
        if node["type"] == "table.read_table" and "path" in node["inputs"]:
            node["inputs"]["path"] = str(tmp_path / "showcase.csv")

    client = TestClient(create_app(DEFAULT_REGISTRY, graph, workspace=workspace))
    yield client, module_file

    sys.path.remove(str(tmp_path))
    sys.modules.pop(name, None)
    DEFAULT_REGISTRY.unregister_module(name)


def test_showcase_widget_commit_round_trips(showcase_sandbox):
    client, module_file = showcase_sandbox
    graph = client.get("/api/graph").json()

    # Simulate a math-widget edit and a text-widget edit (the shell's onCommit).
    expr = next(n for n in graph["nodes"] if n["type"] == "sym.parse_expr")
    expr["inputs"]["text"] = "x**2 - 4"
    summary = next(n for n in graph["nodes"] if n["type"] == "table.table_summary")
    summary["inputs"]["title"] = "Edited via widget"

    res = client.put("/api/graph", json={"graph": graph})
    assert res.status_code == 200, res.text
    saved = res.json()["graph"]

    # Persisted (the round-trip proof) and now what the server serves.
    assert next(n for n in saved["nodes"] if n["type"] == "sym.parse_expr")["inputs"]["text"] == "x**2 - 4"
    assert (
        next(n for n in saved["nodes"] if n["type"] == "table.table_summary")["inputs"]["title"]
        == "Edited via widget"
    )
    assert client.get("/api/graph").json() == saved

    # The rewritten module still binds and runs; cross-pack calls stay by their
    # imported names.
    text = module_file.read_text(encoding="utf-8")
    assert "parse_expr(text='x**2 - 4')" in text
    assert client.post("/api/run", json={"graph": saved}).json()["errors"] == []


def test_showcase_reject_uncallable_type_is_still_rejected(showcase_sandbox):
    """A node type the module neither imports nor defines is refused, unchanged."""
    client, module_file = showcase_sandbox

    def helper(x: int = 0) -> int:
        return x

    DEFAULT_REGISTRY.register(helper, module="elsewhere", qualname="helper")
    try:
        graph = client.get("/api/graph").json()
        before = module_file.read_text(encoding="utf-8")
        graph["nodes"].append(
            {"id": "extra", "type": "elsewhere.helper", "inputs": {"x": 1}, "position": None}
        )
        res = client.put("/api/graph", json={"graph": graph})
        assert res.status_code == 422
        assert "elsewhere" in res.text
        assert module_file.read_text(encoding="utf-8") == before
    finally:
        DEFAULT_REGISTRY.unregister_module("elsewhere")
