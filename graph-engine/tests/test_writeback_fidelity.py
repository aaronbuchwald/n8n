"""Write-back fidelity for ``PUT /api/graph`` (ADR 0004 D5; review 0005, #5).

A single widget/literal edit must rewrite ONLY the wiring statement that
changed, leaving every surrounding comment, blank line and multi-line literal in
the ``@main`` body byte-for-byte. A structural change (nodes added/removed) may
fall back to normalizing the whole wiring block, but it must not do so silently.

Every test runs against a SEPARATE fixture module written to a temp dir — its own
module name, its own workspace root — so no real example (least of all the
showcase) is ever touched. The fixture deliberately packs the ``@main`` body with
the formatting the projection used to destroy: section comments, an inline
comment inside a multi-line dict literal, and blank lines between chains.
"""

from __future__ import annotations

import importlib
import logging
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine import DEFAULT_REGISTRY
from server import create_app
from server.workspace import Workspace

# A self-contained authoring module (pure stdlib nodes) whose @main body carries
# hand-written comments, blank lines and a multi-line literal — the formatting a
# whole-body regeneration would erase.
FIXTURE_SOURCE = '''\
"""A composite whose @main body has hand-written comments and formatting."""

from __future__ import annotations

from engine import main, node


@node
def source(rows: int = 3, label: str = "raw") -> dict:
    """A tiny literal source with two editable widget inputs."""
    return {"rows": rows, "label": label}


@node
def shape(data: dict, options: dict) -> dict:
    """Merge a multi-line options literal onto the source data."""
    return {**data, **options}


@node
def render(data: dict, title: str = "Report") -> str:
    """Render the shaped data as a one-line HTML string."""
    return f"<p>{title}: {data}</p>"


@main
def report() -> str:
    """Build the tiny report."""
    # --- source: two editable widgets (a number and a text label) ---------
    raw = source(rows=3, label="raw")

    # --- shape: a hand-formatted, multi-line options literal --------------
    shaped = shape(
        data=raw,
        options={
            "mode": "wide",      # keep this inline comment
            "limit": 10,
            "tags": ["a", "b"],
        },
    )

    # --- render: the final HTML card --------------------------------------
    card = render(shaped, title="Widget showcase")
    return card


NODES = [source, shape, render]
'''


@dataclass
class Sandbox:
    client: TestClient
    workspace: Workspace
    module_name: str
    file: Path


@pytest.fixture()
def sandbox(tmp_path: Path):
    """A temp copy of the commented fixture: own module + workspace root."""
    name = f"commented_{uuid.uuid4().hex[:8]}"
    module_file = tmp_path / f"{name}.py"
    module_file.write_text(FIXTURE_SOURCE, encoding="utf-8")

    sys.path.insert(0, str(tmp_path))
    importlib.import_module(name)
    workspace = Workspace(DEFAULT_REGISTRY, name, allowed_roots=[tmp_path])
    graph = workspace.parse_graph()
    client = TestClient(create_app(DEFAULT_REGISTRY, graph, workspace=workspace))
    yield Sandbox(client=client, workspace=workspace, module_name=name, file=module_file)

    sys.path.remove(str(tmp_path))
    sys.modules.pop(name, None)
    DEFAULT_REGISTRY.unregister_module(name)


# The comments/formatting the fixture body carries — every one must survive a
# value edit to an unrelated statement.
_COMMENTS = [
    "# --- source: two editable widgets (a number and a text label) ---------",
    "# --- shape: a hand-formatted, multi-line options literal --------------",
    "# --- render: the final HTML card --------------------------------------",
    '"mode": "wide",      # keep this inline comment',
    '"limit": 10,',
    '"tags": ["a", "b"],',
]


def test_editing_one_literal_preserves_all_other_comments_and_formatting(sandbox: Sandbox):
    graph = sandbox.client.get("/api/graph").json()
    source_node = next(n for n in graph["nodes"] if n["id"] == "raw")
    source_node["inputs"]["label"] = "edited"  # change ONE widget literal

    res = sandbox.client.put("/api/graph", json={"graph": graph})
    assert res.status_code == 200, res.text

    text = sandbox.file.read_text(encoding="utf-8")
    # The one edited statement is re-emitted with the new value...
    assert "label='edited'" in text
    assert 'label="raw"' not in text
    # ...and EVERY comment/format detail elsewhere in the body is untouched.
    for fragment in _COMMENTS:
        assert fragment in text, f"lost body formatting: {fragment!r}"
    # Blank lines between the three chains survive (body was not collapsed).
    assert "\n\n    # --- shape:" in text
    assert "    return card\n" in text

    # Round-trips: the served graph reflects the edit and nothing else moved.
    served = sandbox.client.get("/api/graph").json()
    assert next(n for n in served["nodes"] if n["id"] == "raw")["inputs"]["label"] == "edited"
    assert {n["id"] for n in served["nodes"]} == {"raw", "shaped", "card"}


def test_editing_the_multiline_literal_only_collapses_that_statement(sandbox: Sandbox):
    graph = sandbox.client.get("/api/graph").json()
    shaped = next(n for n in graph["nodes"] if n["id"] == "shaped")
    shaped["inputs"]["options"] = {"mode": "narrow", "limit": 5}  # edit the dict

    res = sandbox.client.put("/api/graph", json={"graph": graph})
    assert res.status_code == 200, res.text

    text = sandbox.file.read_text(encoding="utf-8")
    # The edited statement normalizes (its inline comment is honestly gone)...
    assert "'mode': 'narrow'" in text
    assert "keep this inline comment" not in text
    # ...but the UNRELATED section comments and the untouched statements survive.
    assert "# --- source: two editable widgets" in text
    assert "# --- render: the final HTML card" in text
    assert 'label="raw"' in text  # source statement untouched
    # The render statement was NOT rewritten, so it keeps its original text
    # (double-quoted title), not the single-quoted emitted form.
    assert 'card = render(shaped, title="Widget showcase")' in text


def test_no_op_save_leaves_the_file_byte_identical(sandbox: Sandbox):
    graph = sandbox.client.get("/api/graph").json()
    before = sandbox.file.read_text(encoding="utf-8")

    res = sandbox.client.put("/api/graph", json={"graph": graph})
    assert res.status_code == 200, res.text
    # Nothing changed, so the source file is not rewritten at all.
    assert sandbox.file.read_text(encoding="utf-8") == before


def test_structural_change_falls_back_and_warns(sandbox: Sandbox, caplog):
    # Adding a node changes the composite's node SET → whole-block regeneration.
    graph = sandbox.client.get("/api/graph").json()
    graph["nodes"].append(
        {
            "id": "extra",
            "type": f"{sandbox.module_name}.source",
            "inputs": {"rows": 1, "label": "extra"},
            "position": None,
        }
    )

    with caplog.at_level(logging.WARNING):
        res = sandbox.client.put("/api/graph", json={"graph": graph})
    assert res.status_code == 200, res.text

    text = sandbox.file.read_text(encoding="utf-8")
    # The new node landed and the graph still round-trips...
    assert "extra = source(" in text
    served = sandbox.client.get("/api/graph").json()
    assert "extra" in {n["id"] for n in served["nodes"]}
    # ...and the normalization was NOT silent: a warning names the file.
    assert any(
        "regenerated" in rec.getMessage() and sandbox.module_name in rec.getMessage()
        for rec in caplog.records
    ), "structural normalization must be logged, never silent"


def test_rewired_edge_patches_only_the_target_statement(sandbox: Sandbox):
    # Drop the edge feeding `render.data` and give it a literal instead: a
    # wiring change on one statement, node set unchanged → in-place patch.
    graph = sandbox.client.get("/api/graph").json()
    graph["edges"] = [e for e in graph["edges"] if e["target"] != "card"]
    card = next(n for n in graph["nodes"] if n["id"] == "card")
    card["inputs"]["data"] = {"literal": True}

    res = sandbox.client.put("/api/graph", json={"graph": graph})
    assert res.status_code == 200, res.text

    text = sandbox.file.read_text(encoding="utf-8")
    # Only the render statement changed; the source/shape comments are intact.
    assert "# --- source: two editable widgets" in text
    assert "# --- shape: a hand-formatted" in text
    assert 'label="raw"' in text
    assert "keep this inline comment" in text
