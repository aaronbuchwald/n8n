"""Write-back fidelity for ``PUT /api/graph`` (ADR 0004 D5/A1, ADR 0011 HD2).

Fidelity is the whole point of the structural write-back stream. These tests are
the sign-off artifact for it:

* **Value/edge edit (A1).** A single widget/literal edit rewrites ONLY the wiring
  statement that changed, leaving every surrounding comment, blank line and
  multi-line literal byte-for-byte.
* **Pure insertion (HD2 §1).** Adding a node splices in the new assignment
  line(s) and touches **no existing line** — proved with a diff that contains
  only insertions. A dependent node lands right after its deepest upstream
  dependency; an independent node lands just before the ``return``.
* **Pure deletion (HD2 §2).** Removing a node splices out exactly its span plus
  the ``#`` comment block attached directly above it — and nothing else. An
  orphaned comment that was not attached survives (prose is never silently eaten).
* **Replace-node (HD2 §3).** A save that both deletes and inserts rewrites no
  surviving line.
* **Import management (HD2 §5).** Placing a node whose type the module neither
  imports nor defines inserts a ``from <pack> import <fn>`` line, aliased when the
  name would shadow a node id — touching only the import block.
* **Fallback (HD2 §4).** A rewire that would force existing statements out of
  dependency order can't be applied line-by-line, so it regenerates the wiring
  block — and now surfaces a structured warning in the save response, not just a
  server log.

Every test runs against a SEPARATE fixture module written to a temp dir — its own
module name, its own workspace root — so no real example (least of all the
showcase) is ever touched.
"""

from __future__ import annotations

import difflib
import importlib
import logging
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest
from fastapi.testclient import TestClient

import calc  # noqa: F401 — registers calc.* into DEFAULT_REGISTRY for import tests
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

# A fixture built to exercise the deletion comment policy: a node whose leading
# comment block is attached (removed with it), and a trailing note that is NOT
# attached (must survive as an orphan).
DELETION_SOURCE = '''\
"""A composite with an independent, commented, deletable node."""

from __future__ import annotations

from engine import main, node


@node
def source(rows: int = 3, label: str = "raw") -> dict:
    """A tiny literal source."""
    return {"rows": rows, "label": label}


@node
def render(data: dict, title: str = "Report") -> str:
    """Render as a one-line HTML string."""
    return f"<p>{title}: {data}</p>"


@main
def report() -> str:
    """Build the report."""
    a = source(rows=1, label="a")

    # --- section: extras --------------------------------------------------
    # attached to b, removed when b is
    b = source(rows=2, label="b")
    # trailing note after b — not attached to c, must survive

    c = render(a, title="C")
    return c


NODES = [source, render]
'''

# A three-node chain of one self-referential type, so a save can reverse the
# dependency direction — a reorder the in-place statement model can't express.
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


def _make_sandbox(tmp_path: Path, source: str) -> Sandbox:
    name = f"fixture_{uuid.uuid4().hex[:8]}"
    module_file = tmp_path / f"{name}.py"
    module_file.write_text(source, encoding="utf-8")

    sys.path.insert(0, str(tmp_path))
    importlib.import_module(name)
    workspace = Workspace(DEFAULT_REGISTRY, name, allowed_roots=[tmp_path])
    graph = workspace.parse_graph()
    client = TestClient(create_app(DEFAULT_REGISTRY, graph, workspace=workspace))
    return Sandbox(client=client, workspace=workspace, module_name=name, file=module_file)


@pytest.fixture()
def sandbox(tmp_path: Path):
    """A temp copy of the commented fixture: own module + workspace root."""
    sb = _make_sandbox(tmp_path, FIXTURE_SOURCE)
    yield sb
    sys.path.remove(str(tmp_path))
    sys.modules.pop(sb.module_name, None)
    DEFAULT_REGISTRY.unregister_module(sb.module_name)


@pytest.fixture()
def make_sandbox(tmp_path: Path):
    """Factory for a sandbox over an arbitrary fixture source, with cleanup."""
    created: list[Sandbox] = []

    def _factory(source: str) -> Sandbox:
        sb = _make_sandbox(tmp_path, source)
        created.append(sb)
        return sb

    yield _factory

    if str(tmp_path) in sys.path:
        sys.path.remove(str(tmp_path))
    for sb in created:
        sys.modules.pop(sb.module_name, None)
        DEFAULT_REGISTRY.unregister_module(sb.module_name)


# ----------------------------------------------------------------------
# diff helpers: prove exactly which lines the write-back touched
# ----------------------------------------------------------------------


def _touched(before: str, after: str) -> tuple[list[str], list[str], bool]:
    """``(inserted, deleted, any_replace)`` between two texts, line-wise.

    ``any_replace`` is True if any opcode *rewrote* an existing line (a ``replace``
    — i.e. an existing line was changed rather than purely added or removed).
    """
    a, b = before.splitlines(), after.splitlines()
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    inserted: list[str] = []
    deleted: list[str] = []
    any_replace = False
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "insert":
            inserted.extend(b[j1:j2])
        elif tag == "delete":
            deleted.extend(a[i1:i2])
        elif tag == "replace":
            any_replace = True
            deleted.extend(a[i1:i2])
            inserted.extend(b[j1:j2])
    return inserted, deleted, any_replace


# The comments/formatting the FIXTURE body carries — every one must survive a
# value edit to an unrelated statement.
_COMMENTS = [
    "# --- source: two editable widgets (a number and a text label) ---------",
    "# --- shape: a hand-formatted, multi-line options literal --------------",
    "# --- render: the final HTML card --------------------------------------",
    '"mode": "wide",      # keep this inline comment',
    '"limit": 10,',
    '"tags": ["a", "b"],',
]


# ----------------------------------------------------------------------
# A. value / edge edits (Amendment A1) — unchanged behaviour, still proven
# ----------------------------------------------------------------------


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
    assert "'mode': 'narrow'" in text
    assert "keep this inline comment" not in text
    assert "# --- source: two editable widgets" in text
    assert "# --- render: the final HTML card" in text
    assert 'label="raw"' in text  # source statement untouched
    assert 'card = render(shaped, title="Widget showcase")' in text


def test_no_op_save_leaves_the_file_byte_identical(sandbox: Sandbox):
    graph = sandbox.client.get("/api/graph").json()
    before = sandbox.file.read_text(encoding="utf-8")

    res = sandbox.client.put("/api/graph", json={"graph": graph})
    assert res.status_code == 200, res.text
    assert sandbox.file.read_text(encoding="utf-8") == before
    assert "writeback" not in res.json()["graph"]  # no warning on a clean save


def test_rewired_edge_patches_only_the_target_statement(sandbox: Sandbox):
    graph = sandbox.client.get("/api/graph").json()
    graph["edges"] = [e for e in graph["edges"] if e["target"] != "card"]
    card = next(n for n in graph["nodes"] if n["id"] == "card")
    card["inputs"]["data"] = {"literal": True}

    res = sandbox.client.put("/api/graph", json={"graph": graph})
    assert res.status_code == 200, res.text

    text = sandbox.file.read_text(encoding="utf-8")
    assert "# --- source: two editable widgets" in text
    assert "# --- shape: a hand-formatted" in text
    assert 'label="raw"' in text
    assert "keep this inline comment" in text


# ----------------------------------------------------------------------
# B. pure insertion (HD2 §1) — no existing line is touched
# ----------------------------------------------------------------------


def test_inserting_independent_node_touches_no_existing_line(sandbox: Sandbox):
    before = sandbox.file.read_text(encoding="utf-8")
    graph = sandbox.client.get("/api/graph").json()
    graph["nodes"].append(
        {"id": "extra", "type": f"{sandbox.module_name}.source",
         "inputs": {"rows": 1, "label": "x"}, "position": None}
    )

    res = sandbox.client.put("/api/graph", json={"graph": graph})
    assert res.status_code == 200, res.text

    after = sandbox.file.read_text(encoding="utf-8")
    inserted, deleted, any_replace = _touched(before, after)
    # The whole edit is exactly one inserted line; nothing existing moved.
    assert deleted == [] and any_replace is False
    assert inserted == ["    extra = source(rows=1, label='x')"]
    # An independent node lands just before the return.
    assert "    extra = source(rows=1, label='x')\n    return card\n" in after
    # Every hand-written comment is byte-identical.
    for fragment in _COMMENTS:
        assert fragment in after
    # The save was lossless → no warning surfaced.
    assert "writeback" not in res.json()["graph"]
    served = sandbox.client.get("/api/graph").json()
    assert "extra" in {n["id"] for n in served["nodes"]}


def test_inserting_dependent_node_lands_after_its_dependency(sandbox: Sandbox):
    before = sandbox.file.read_text(encoding="utf-8")
    graph = sandbox.client.get("/api/graph").json()
    graph["nodes"].append(
        {"id": "mid", "type": f"{sandbox.module_name}.shape",
         "inputs": {"options": {"k": "v"}}, "position": None}
    )
    graph["edges"].append(
        {"source": "raw", "sourceOutput": "result", "target": "mid", "targetInput": "data"}
    )

    res = sandbox.client.put("/api/graph", json={"graph": graph})
    assert res.status_code == 200, res.text

    after = sandbox.file.read_text(encoding="utf-8")
    inserted, deleted, any_replace = _touched(before, after)
    assert deleted == [] and any_replace is False
    assert inserted == ["    mid = shape(data=raw, options={'k': 'v'})"]
    # It lands immediately after its only dependency, `raw`.
    assert (
        '    raw = source(rows=3, label="raw")\n'
        "    mid = shape(data=raw, options={'k': 'v'})\n"
    ) in after
    for fragment in _COMMENTS:
        assert fragment in after


# ----------------------------------------------------------------------
# C. pure deletion (HD2 §2) — only the span + its attached comment go
# ----------------------------------------------------------------------


def test_deleting_a_node_takes_only_its_attached_comment(make_sandbox: Callable[[str], Sandbox]):
    sb = make_sandbox(DELETION_SOURCE)
    before = sb.file.read_text(encoding="utf-8")
    graph = sb.client.get("/api/graph").json()
    graph["nodes"] = [n for n in graph["nodes"] if n["id"] != "b"]  # b is a leaf

    res = sb.client.put("/api/graph", json={"graph": graph})
    assert res.status_code == 200, res.text

    after = sb.file.read_text(encoding="utf-8")
    inserted, deleted, any_replace = _touched(before, after)
    # Only a deletion; no surviving line rewritten, nothing inserted.
    assert inserted == [] and any_replace is False
    # Exactly b's statement AND the contiguous comment block above it.
    assert deleted == [
        "    # --- section: extras --------------------------------------------------",
        "    # attached to b, removed when b is",
        '    b = source(rows=2, label="b")',
    ]
    # The UNATTACHED trailing note survives even though b is gone.
    assert "# trailing note after b — not attached to c, must survive" in after
    # Survivors intact.
    assert '    a = source(rows=1, label="a")' in after
    assert '    c = render(a, title="C")' in after
    assert "writeback" not in res.json()["graph"]


# ----------------------------------------------------------------------
# D. replace-node (HD2 §3) — delete + insert, no survivor rewritten
# ----------------------------------------------------------------------


def test_replacing_a_node_inserts_and_deletes_without_rewriting_survivors(
    make_sandbox: Callable[[str], Sandbox]
):
    sb = make_sandbox(DELETION_SOURCE)
    before = sb.file.read_text(encoding="utf-8")
    graph = sb.client.get("/api/graph").json()
    graph["nodes"] = [n for n in graph["nodes"] if n["id"] != "b"]
    graph["nodes"].append(
        {"id": "d", "type": f"{sb.module_name}.source",
         "inputs": {"rows": 9, "label": "d"}, "position": None}
    )

    res = sb.client.put("/api/graph", json={"graph": graph})
    assert res.status_code == 200, res.text

    after = sb.file.read_text(encoding="utf-8")
    inserted, deleted, any_replace = _touched(before, after)
    # b (+ its attached comment) is gone; d is new; no survivor was rewritten.
    assert any_replace is False
    assert '    d = source(rows=9, label=\'d\')' in inserted
    assert '    b = source(rows=2, label="b")' in deleted
    assert '    # attached to b, removed when b is' in deleted
    # Survivors and the orphaned trailing note are all untouched.
    assert '    a = source(rows=1, label="a")' in after
    assert '    c = render(a, title="C")' in after
    assert "# trailing note after b — not attached to c, must survive" in after
    served = sb.client.get("/api/graph").json()
    assert {n["id"] for n in served["nodes"]} == {"a", "c", "d"}


# ----------------------------------------------------------------------
# E. import management (HD2 §5) — foreign type auto-imported, aliased on shadow
# ----------------------------------------------------------------------


def test_placing_a_foreign_type_adds_its_import(sandbox: Sandbox):
    before = sandbox.file.read_text(encoding="utf-8")
    graph = sandbox.client.get("/api/graph").json()
    graph["nodes"].append(
        {"id": "t", "type": "calc.total", "inputs": {"values": [1, 2, 3]},
         "position": None}
    )

    res = sandbox.client.put("/api/graph", json={"graph": graph})
    assert res.status_code == 200, res.text

    after = sandbox.file.read_text(encoding="utf-8")
    inserted, deleted, any_replace = _touched(before, after)
    assert deleted == [] and any_replace is False
    # Exactly two insertions: the import (in the header) and the node line.
    assert "from calc import total" in inserted
    assert "    t = total(values=[1, 2, 3])" in inserted
    # The import lands in the header, before the composite — never in the body.
    assert "from engine import main, node\nfrom calc import total\n" in after
    assert after.index("from calc import total") < after.index("def report")
    # No import for a type already local; body comments intact.
    for fragment in _COMMENTS:
        assert fragment in after


def test_placing_a_shadowing_foreign_type_aliases_its_import(sandbox: Sandbox):
    graph = sandbox.client.get("/api/graph").json()
    # The node id equals the imported function's name → the import must alias so
    # the local variable never shadows the callable it needs.
    graph["nodes"].append(
        {"id": "total", "type": "calc.total", "inputs": {"values": [4, 5]},
         "position": None}
    )

    res = sandbox.client.put("/api/graph", json={"graph": graph})
    assert res.status_code == 200, res.text

    after = sandbox.file.read_text(encoding="utf-8")
    assert "from calc import total as total_2" in after
    assert "    total = total_2(values=[4, 5])" in after
    served = sandbox.client.get("/api/graph").json()
    assert next(n for n in served["nodes"] if n["id"] == "total")["type"] == "calc.total"


# ----------------------------------------------------------------------
# F. fallback (HD2 §4) — a reorder can't patch in place; warn in the response
# ----------------------------------------------------------------------


def test_reorder_falls_back_and_surfaces_warning_in_response(
    make_sandbox: Callable[[str], Sandbox], caplog
):
    sb = make_sandbox(REORDER_SOURCE)
    graph = sb.client.get("/api/graph").json()
    # Reverse the chain's dependency direction (still acyclic): last seeds the
    # chain, first becomes the output. The file order (first, mid, last) is now
    # the exact reverse of the required order — no in-place patch can express it.
    graph["edges"] = [
        {"source": "mid", "sourceOutput": "result", "target": "first", "targetInput": "value"},
        {"source": "last", "sourceOutput": "result", "target": "mid", "targetInput": "value"},
    ]
    for n in graph["nodes"]:
        n["inputs"] = {"value": 1} if n["id"] == "last" else {}
    graph["output"] = {"node": "first", "socket": "result"}

    with caplog.at_level(logging.WARNING):
        res = sb.client.put("/api/graph", json={"graph": graph})
    assert res.status_code == 200, res.text

    body = res.json()["graph"]
    # The fallback is surfaced structurally in the response (not just logged).
    assert body["writeback"]["code"] == "wiring-block-regenerated"
    assert body["writeback"]["droppedComments"] is True
    # And it is still logged, naming the file.
    assert any(
        sb.module_name in rec.getMessage() for rec in caplog.records
    ), "the fallback must also be logged"

    text = sb.file.read_text(encoding="utf-8")
    # The block was regenerated in the new (valid) order; its inline comment,
    # which lived between statements, is honestly gone (that's the lossy case).
    assert "midpoint comment" not in text
    # The rewired graph still round-trips.
    served = sb.client.get("/api/graph").json()
    assert served["output"] == {"node": "first", "socket": "result"}
