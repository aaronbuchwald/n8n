"""``PUT /api/graph`` (and its id-scoped twin) envelope shape (ADR 0011 W3).

``server/workspace.py::save_graph`` (11-W2) parks a structural write-back
fallback warning at ``graph["writeback"]`` — a seam note left for this stream
to lift it onto the **PUT response envelope** as a top-level field, so a
lossless save's ``graph`` stays byte-for-byte what ``GET`` serves (``GET ==
PUT`` never gets an extra key nested in it) and a canvas client has one
consistent place to look for the warning regardless of save shape.

Fidelity of the write-back strategies themselves (insert/delete/import/reorder)
is proven in ``tests/test_writeback_fidelity.py``; these tests are narrowly
about the envelope contract.
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

# A linear chain of one self-referential type: a rewire that reverses the
# chain forces the existing statements out of dependency order — a reorder
# the in-place statement patcher can't express, so it falls back to
# regenerating the whole wiring block (ADR 0011 HD2 §4). The inline comment
# only survives a line-by-line patch, so its disappearance also proves the
# fallback actually ran.
REORDER_SOURCE = '''\
"""A linear chain that a reversing rewire cannot patch in place."""

from __future__ import annotations

from engine import main, node


@node
def step(value: int = 0) -> int:
    """Pass a number through untouched."""
    return value


@main
def chain() -> int:
    """A three-step chain."""
    first = step(value=1)
    # midpoint comment that only a block-regen would drop
    mid = step(value=first)
    last = step(value=mid)
    return last


NODES = [step]
'''


@dataclass
class Sandbox:
    client: TestClient
    workspace: Workspace
    module_name: str
    file: Path


@pytest.fixture()
def sandbox(tmp_path: Path):
    name = f"envelope_{uuid.uuid4().hex[:8]}"
    module_file = tmp_path / f"{name}.py"
    module_file.write_text(REORDER_SOURCE, encoding="utf-8")

    sys.path.insert(0, str(tmp_path))
    importlib.import_module(name)
    workspace = Workspace(DEFAULT_REGISTRY, name, allowed_roots=[tmp_path])
    graph = workspace.parse_graph()
    client = TestClient(create_app(DEFAULT_REGISTRY, graph, workspace=workspace))
    yield Sandbox(client=client, workspace=workspace, module_name=name, file=module_file)

    sys.path.remove(str(tmp_path))
    sys.modules.pop(name, None)
    DEFAULT_REGISTRY.unregister_module(name)


def test_value_edit_put_has_no_writeback_on_the_envelope(sandbox: Sandbox):
    """A lossless statement-patch save carries no warning anywhere."""
    graph = sandbox.client.get("/api/graph").json()
    for node in graph["nodes"]:
        if node["id"] == "first":
            node["inputs"]["value"] = 5  # a plain literal edit, no reorder

    res = sandbox.client.put("/api/graph", json={"graph": graph})
    assert res.status_code == 200, res.text
    envelope = res.json()
    assert set(envelope) == {"graph"}  # no top-level `writeback` key at all
    assert "writeback" not in envelope["graph"]
    # ...and GET now serves exactly the PUT's `graph` (round-trip identity).
    assert sandbox.client.get("/api/graph").json() == envelope["graph"]


def test_structural_fallback_put_surfaces_writeback_on_the_envelope(
    sandbox: Sandbox, caplog
):
    """A save the statement model can't express falls back, and the loss is
    surfaced as a top-level `writeback` field — not nested under `graph`."""
    graph = sandbox.client.get("/api/graph").json()
    # Reverse the chain's dependency direction (still acyclic): the file order
    # (first, mid, last) becomes the exact reverse of the required order.
    graph["edges"] = [
        {"source": "mid", "sourceOutput": "result", "target": "first", "targetInput": "value"},
        {"source": "last", "sourceOutput": "result", "target": "mid", "targetInput": "value"},
    ]
    for n in graph["nodes"]:
        n["inputs"] = {"value": 1} if n["id"] == "last" else {}
    graph["output"] = {"node": "first", "socket": "result"}

    with caplog.at_level(logging.WARNING):
        res = sandbox.client.put("/api/graph", json={"graph": graph})
    assert res.status_code == 200, res.text

    envelope = res.json()
    assert envelope["writeback"]["code"] == "wiring-block-regenerated"
    assert envelope["writeback"]["droppedComments"] is True
    assert "writeback" not in envelope["graph"]  # never nested — lifted, not duplicated

    # `graph` is still exactly what GET now serves.
    assert sandbox.client.get("/api/graph").json() == envelope["graph"]
    # The regenerated block really did drop the comment (proves this is the
    # lossy path, not a coincidental warning-free save).
    text = sandbox.file.read_text(encoding="utf-8")
    assert "midpoint comment" not in text
