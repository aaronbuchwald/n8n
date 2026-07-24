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

import ast
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

# A composite already written in the ADR 0020 block form: the `text` literal is
# parenthesized implicit concatenation inside an expanded call, so the wiring
# statement spans FIVE physical lines. Used to prove multi-line statements
# splice, patch, insert and delete exactly like one-liners.
BLOCK_SOURCE = '''\
"""A composite whose @main body carries a block-form multi-line literal."""

from __future__ import annotations

from engine import main, node


@node
def note(text: str = "", label: str = "note") -> dict:
    """A node with a genuinely multi-line text literal."""
    return {"text": text, "label": label}


@node
def render(data: dict, title: str = "Report") -> str:
    """Render the note as a one-line HTML string."""
    return f"<p>{title}: {data}</p>"


@main
def report() -> str:
    """Build the tiny report."""
    # --- the calc-ish literal, in ADR 0020 block form ---------------------
    entry = note(
        text=(
            'r = F_max / C_min  # demand / capacity\\n'
            'U = 100 * r [%]  # utilisation'
        ),
        label='entry',
    )

    # --- render: the final HTML card --------------------------------------
    card = render(entry, title="Block form")
    return card


NODES = [note, render]
'''

# The same value, hand-typed in the three spellings CPython collapses to one
# `ast.Constant` (ADR 0020 D4). Each must be a no-op on save.
_SPELLINGS = {
    "escaped": (
        "    entry = note(text='r = F_max / C_min  # demand / capacity"
        "\\nU = 100 * r [%]  # utilisation', label='entry')"
    ),
    "concatenated": (
        "    entry = note(\n"
        "        text=(\n"
        "            'r = F_max / C_min  # demand / capacity\\n'\n"
        "            'U = 100 * r [%]  # utilisation'\n"
        "        ),\n"
        "        label='entry',\n"
        "    )"
    ),
    # Triple-quoted content is taken literally, so its lines start at column 0.
    "triple_quoted": (
        '    entry = note(text="""r = F_max / C_min  # demand / capacity\n'
        'U = 100 * r [%]  # utilisation""", label=\'entry\')'
    ),
}

BLOCK_STATEMENT = _SPELLINGS["concatenated"]


def _spelled(statement: str) -> str:
    """BLOCK_SOURCE with its `entry` statement written in another spelling."""
    return BLOCK_SOURCE.replace(BLOCK_STATEMENT, statement)


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

    envelope = res.json()
    # The fallback is surfaced structurally on the PUT envelope (ADR 0011 W3),
    # not nested under `graph` — so a lossless `graph` stays byte-for-byte what
    # GET serves, and a canvas client can look for one top-level field.
    assert envelope["writeback"]["code"] == "wiring-block-regenerated"
    assert envelope["writeback"]["droppedComments"] is True
    assert "writeback" not in envelope["graph"]
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


# ----------------------------------------------------------------------
# G. multi-line string literals (ADR 0020) — a block-form statement patches,
#    splices, inserts and deletes exactly like a one-line one
# ----------------------------------------------------------------------

CALC_TEXT = "r = F_max / C_min  # demand / capacity\nU = 100 * r [%]  # utilisation"

# Values chosen to break naive multi-line spellings: preserved byte-exactly.
AWKWARD_VALUES = {
    "trailing_newline": "a\nb\n",
    "crlf": "first\r\nsecond\r\n",
    "embedded_quotes": "he said \"hi\"\nshe said 'bye'\n",
    "backslashes_latex": "\\nu = \\frac{a}{b}\\\\\nE = m c^2  # \\nu, not a newline",
    "triple_quote": 'a """ b\nc """',
    "blank_lines": "first\n\n\nlast",
}


def _file_literal(path: Path, node_id: str, name: str):
    """The value of ``node_id``'s ``name=`` argument, read from the file's AST.

    Asserts on the way that the emitted argument really is a single
    ``ast.Constant`` — the block form's fragments are concatenated by the
    parser itself, which is why the parse side needed no change (ADR 0020 D4).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assign = next(
        s
        for s in ast.walk(tree)
        if isinstance(s, ast.Assign)
        and isinstance(s.targets[0], ast.Name)
        and s.targets[0].id == node_id
    )
    assert isinstance(assign.value, ast.Call)
    arg = next(kw.value for kw in assign.value.keywords if kw.arg == name)
    assert isinstance(arg, ast.Constant), f"{name} is a {type(arg).__name__}, not a literal"
    return arg.value


def _node_input(graph: dict, node_id: str, name: str):
    return next(n for n in graph["nodes"] if n["id"] == node_id)["inputs"][name]


def _set_input(graph: dict, node_id: str, name: str, value) -> None:
    next(n for n in graph["nodes"] if n["id"] == node_id)["inputs"][name] = value


def test_no_op_save_on_a_block_form_file_is_byte_identical(
    make_sandbox: Callable[[str], Sandbox]
):
    sb = make_sandbox(BLOCK_SOURCE)
    before = sb.file.read_text(encoding="utf-8")
    graph = sb.client.get("/api/graph").json()
    assert _node_input(graph, "entry", "text") == CALC_TEXT  # parsed byte-exact

    res = sb.client.put("/api/graph", json={"graph": graph})
    assert res.status_code == 200, res.text
    assert sb.file.read_text(encoding="utf-8") == before
    assert "writeback" not in res.json()["graph"]


@pytest.mark.parametrize("spelling", list(_SPELLINGS), ids=list(_SPELLINGS))
def test_every_handwritten_spelling_is_a_no_op_on_save(
    make_sandbox: Callable[[str], Sandbox], spelling: str
):
    """A hand-typed variant denoting the same string is never churned (D4/D6).

    Write-back compares parsed meaning, so escaped-``\\n``, implicit
    concatenation and a column-0 triple-quoted literal all survive a save
    byte-for-byte — the file only migrates when its meaning actually changes.
    """
    sb = make_sandbox(_spelled(_SPELLINGS[spelling]))
    before = sb.file.read_text(encoding="utf-8")
    graph = sb.client.get("/api/graph").json()
    assert _node_input(graph, "entry", "text") == CALC_TEXT

    res = sb.client.put("/api/graph", json={"graph": graph})
    assert res.status_code == 200, res.text
    assert sb.file.read_text(encoding="utf-8") == before


def test_editing_a_multiline_literal_writes_the_block_form(
    make_sandbox: Callable[[str], Sandbox]
):
    sb = make_sandbox(BLOCK_SOURCE)
    before = sb.file.read_text(encoding="utf-8")
    graph = sb.client.get("/api/graph").json()
    edited = f"{CALC_TEXT}\nm = C_min - F_max  # margin over demand"
    _set_input(graph, "entry", "text", edited)

    res = sb.client.put("/api/graph", json={"graph": graph})
    assert res.status_code == 200, res.text

    after = sb.file.read_text(encoding="utf-8")
    assert (
        "    entry = note(\n"
        "        text=(\n"
        "            'r = F_max / C_min  # demand / capacity\\n'\n"
        "            'U = 100 * r [%]  # utilisation\\n'\n"
        "            'm = C_min - F_max  # margin over demand'\n"
        "        ),\n"
        "        label='entry',\n"
        "    )\n"
    ) in after
    # The value came back byte-exact through the file.
    assert _node_input(sb.client.get("/api/graph").json(), "entry", "text") == edited
    # Only the one statement moved: every comment and the render line survive.
    inserted, deleted, _replace = _touched(before, after)
    assert "    # --- render: the final HTML card --------------------------------------" not in (
        inserted + deleted
    )
    assert '    card = render(entry, title="Block form")' in after
    assert "# --- the calc-ish literal, in ADR 0020 block form" in after


def test_editing_a_sibling_param_reemits_the_whole_statement_in_block_form(
    make_sandbox: Callable[[str], Sandbox]
):
    """Changing `label` re-emits the statement — its multi-line sibling included.

    The re-emitted statement takes the canonical block shape and the untouched
    `text` value survives byte-exactly (representation changed, value did not).
    """
    sb = make_sandbox(BLOCK_SOURCE)
    graph = sb.client.get("/api/graph").json()
    _set_input(graph, "entry", "label", "edited")

    res = sb.client.put("/api/graph", json={"graph": graph})
    assert res.status_code == 200, res.text

    after = sb.file.read_text(encoding="utf-8")
    assert "        label='edited',\n" in after
    assert "            'r = F_max / C_min  # demand / capacity\\n'\n" in after
    served = sb.client.get("/api/graph").json()
    assert _node_input(served, "entry", "text") == CALC_TEXT
    assert "# --- render: the final HTML card" in after


def test_a_value_crossing_the_boundary_expands_and_collapses_without_thrash(
    make_sandbox: Callable[[str], Sandbox]
):
    """Single ⟷ multi-line only ever rewrites the statement that changed.

    `card`'s single-line `title` grows a newline (its statement expands), then
    loses it again — and the file returns to its original bytes.
    """
    sb = make_sandbox(BLOCK_SOURCE)
    before = sb.file.read_text(encoding="utf-8")

    graph = sb.client.get("/api/graph").json()
    _set_input(graph, "card", "title", "Block form\nrevision B")
    assert sb.client.put("/api/graph", json={"graph": graph}).status_code == 200

    expanded = sb.file.read_text(encoding="utf-8")
    assert (
        "    card = render(\n"
        "        data=entry,\n"
        "        title=(\n"
        "            'Block form\\n'\n"
        "            'revision B'\n"
        "        ),\n"
        "    )\n"
    ) in expanded
    # `entry`'s block-form statement was NOT touched by an edit to `card`: the
    # only line that left the file is `card`'s own former one-liner.
    assert "        label='entry',\n" in expanded
    _inserted, deleted, _replace = _touched(before, expanded)
    assert deleted == ['    card = render(entry, title="Block form")']

    # A second, identical save changes nothing (idempotence on disk).
    graph = sb.client.get("/api/graph").json()
    assert sb.client.put("/api/graph", json={"graph": graph}).status_code == 200
    assert sb.file.read_text(encoding="utf-8") == expanded

    # Drop the newline again: back to a plain one-line call, no residue.
    _set_input(graph, "card", "title", "Block form")
    assert sb.client.put("/api/graph", json={"graph": graph}).status_code == 200
    collapsed = sb.file.read_text(encoding="utf-8")
    assert "    card = render(data=entry, title='Block form')\n" in collapsed
    assert "revision B" not in collapsed


def test_inserting_a_node_after_a_block_form_statement_touches_no_existing_line(
    make_sandbox: Callable[[str], Sandbox]
):
    """The planner spans a multi-line statement via `end_lineno` (D7).

    A node depending on `entry` must land after the block's CLOSING paren — not
    inside it — and no existing line may be rewritten.
    """
    sb = make_sandbox(BLOCK_SOURCE)
    before = sb.file.read_text(encoding="utf-8")
    graph = sb.client.get("/api/graph").json()
    graph["nodes"].append(
        {"id": "extra", "type": f"{sb.module_name}.render",
         "inputs": {"title": "Extra"}, "position": None}
    )
    graph["edges"].append(
        {"source": "entry", "sourceOutput": "result", "target": "extra", "targetInput": "data"}
    )

    res = sb.client.put("/api/graph", json={"graph": graph})
    assert res.status_code == 200, res.text

    after = sb.file.read_text(encoding="utf-8")
    inserted, deleted, any_replace = _touched(before, after)
    assert deleted == [] and any_replace is False
    assert inserted == ["    extra = render(data=entry, title='Extra')"]
    # It lands immediately after the block statement's closing paren.
    assert "    )\n    extra = render(data=entry, title='Extra')\n" in after


def test_deleting_a_block_form_node_removes_exactly_its_whole_span(
    make_sandbox: Callable[[str], Sandbox]
):
    sb = make_sandbox(BLOCK_SOURCE)
    before = sb.file.read_text(encoding="utf-8")
    graph = sb.client.get("/api/graph").json()
    # Drop the render node (the leaf) so `entry` can go too, then drop `entry`.
    graph["nodes"] = [n for n in graph["nodes"] if n["id"] != "entry"]
    graph["edges"] = [e for e in graph["edges"] if e["source"] != "entry"]
    _set_input(graph, "card", "data", {"inline": True})

    res = sb.client.put("/api/graph", json={"graph": graph})
    assert res.status_code == 200, res.text

    after = sb.file.read_text(encoding="utf-8")
    inserted, deleted, _replace = _touched(before, after)
    # The whole SEVEN-line statement (not just its first line) plus the comment
    # block attached above it — the span came from `end_lineno`.
    assert deleted[:8] == [
        "    # --- the calc-ish literal, in ADR 0020 block form ---------------------",
        "    entry = note(",
        "        text=(",
        "            'r = F_max / C_min  # demand / capacity\\n'",
        "            'U = 100 * r [%]  # utilisation'",
        "        ),",
        "        label='entry',",
        "    )",
    ]
    # The only other rewritten line is `card`'s own statement — it lost its edge.
    assert deleted[8:] == ['    card = render(entry, title="Block form")']
    assert "# --- render: the final HTML card" in after
    assert "note(" not in after[after.index("def report"):]


@pytest.mark.parametrize("value", AWKWARD_VALUES.values(), ids=list(AWKWARD_VALUES))
def test_awkward_multiline_values_survive_a_real_save_byte_exact(
    make_sandbox: Callable[[str], Sandbox], value: str
):
    """Trailing newlines, `\\r\\n`, quotes, backslashes and `\"\"\"` round-trip.

    Nothing is normalized on the way to disk or back: the served value after the
    save is the exact bytes that were sent, and a second save is a no-op.
    """
    sb = make_sandbox(BLOCK_SOURCE)
    graph = sb.client.get("/api/graph").json()
    _set_input(graph, "entry", "text", value)

    res = sb.client.put("/api/graph", json={"graph": graph})
    assert res.status_code == 200, res.text
    assert _node_input(sb.client.get("/api/graph").json(), "entry", "text") == value
    # On disk the argument is still ONE `ast.Constant` holding the exact bytes
    # (the parser concatenates the fragments) — no dedent, no normalization.
    assert _file_literal(sb.file, "entry", "text") == value

    # Saving the re-read graph changes nothing — emit(parse(emit(x))) == emit(x).
    settled = sb.file.read_text(encoding="utf-8")
    again = sb.client.get("/api/graph").json()
    assert sb.client.put("/api/graph", json={"graph": again}).status_code == 200
    assert sb.file.read_text(encoding="utf-8") == settled
