"""Tests for the ``capacity_check_split`` example (ADR 0021 — the graph split).

The single-node form is covered by ``test_capacity_check_example.py``; this
file covers what the split adds, in order:

* the graph's shape — seven nodes, with the ``Result`` on a wire and **two**
  renderings hanging off it;
* the split is not a rewrite: the plain card's HTML is **byte-identical** to
  the card ``examples/capacity_check`` renders from the same data;
* options are literals on the render node only, and they move that node's
  output without touching anyone else's;
* served, the ``Result`` socket previews as real JSON (the ``to_jsonable``
  protocol hook), not a Python repr;
* the module is a fixed point of the graph⟷source bijection: a save with no
  edits changes nothing, and an edit followed by its revert restores the file
  byte-for-byte.

Run with:  uv run --extra dev --extra sym python -m pytest -q
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from engine import DEFAULT_REGISTRY, from_composite, run, validate_graph
from server.app import create_app
from server.demo import example_dir, load_graph, make_workspace
from server.writeback import compute_writeback

ENTRY = "capacity_check_split"
HEAVY_DEPS = ("calcsheet", "sympy", "latex2mathml")


def _calc_deps_available() -> bool:
    for name in HEAVY_DEPS:
        try:
            __import__(name)
        except ImportError:
            return False
    return True


needs_sym_extra = pytest.mark.skipif(
    not _calc_deps_available(), reason="sym extra not installed"
)


def _edge_set(graph) -> set[tuple[str, str, str, str]]:
    return {
        (e["source"], e["sourceOutput"], e["target"], e["targetInput"])
        for e in graph.to_dict()["edges"]
    }


def _module_text() -> str:
    return (example_dir(ENTRY) / f"{ENTRY}.py").read_text(encoding="utf-8")


# -- the graph's shape (no heavy deps needed) ---------------------------------


def test_graph_is_read_select_calc_then_two_renderings():
    from capacity_check_split import build_graph

    doc = build_graph().to_dict()
    assert [n["type"] for n in doc["nodes"]] == [
        "sources.read_csv",
        "sources.read_csv",
        "calc.maximum",
        "calc.minimum",
        "sheet.calc",
        "sheet.render_html",
        "sheet.render_html",
    ]


def test_the_result_is_on_a_wire_feeding_both_renderings():
    """One evaluation, two documents — the whole point of the split (D2)."""
    from capacity_check_split import build_graph

    edges = _edge_set(build_graph())
    assert ("calc", "result", "render_html", "result") in edges
    assert ("calc", "result", "render_html_2", "result") in edges
    # The extremes still arrive on the calc node's derived symbol sockets…
    assert ("maximum", "result", "calc", "F_max") in edges
    assert ("minimum", "result", "calc", "C_min") in edges
    # …and nothing feeds a renderer from anywhere but the calc.
    assert {t for _s, _o, t, _i in edges if t.startswith("render_html")} == {
        "render_html",
        "render_html_2",
    }


def test_options_are_literals_on_the_render_node_only():
    """Presentation never leaks upstream (ADR 0019's constraint, D3's rule)."""
    from capacity_check_split import build_graph

    nodes = {n["id"]: n for n in build_graph().to_dict()["nodes"]}
    assert nodes["render_html"]["inputs"] == {}  # every option left at default
    assert nodes["render_html_2"]["inputs"] == {
        "header": "Acme Corp",
        "footer": "forces.csv · members.csv",
    }
    assert set(nodes["calc"]["inputs"]) == {"title", "as_of", "formulas", "checks"}


def test_the_plain_card_is_the_graph_output():
    from capacity_check_split import build_graph

    assert build_graph().output == {"node": "render_html", "socket": "result"}


# -- the example graph, end-to-end --------------------------------------------


@needs_sym_extra
def test_the_split_output_is_byte_identical_to_the_single_node_example():
    """Splitting the node changed the wiring, not the artifact."""
    from capacity_check import build_graph as build_welded
    from capacity_check_split import build_graph as build_split

    split = build_split()
    validate_graph(split.to_dict())
    result = run(split)
    html = result.value(split.output["node"], split.output["socket"])

    welded = build_welded()
    assert html == run(welded).value(welded.output["node"], welded.output["socket"])
    assert html.startswith("<!doctype html>")


@needs_sym_extra
def test_the_second_rendering_differs_only_in_presentation():
    from capacity_check_split import build_graph

    result = run(build_graph())
    plain = result.value("render_html", "result")
    branded = result.value("render_html_2", "result")

    assert "Acme Corp" in branded and "Acme Corp" not in plain
    # Same evaluation underneath: same values, same verdicts, same references.
    for fragment in (
        '<span class="val">0.571</span>',
        "57.1&nbsp;<span class=\"unit\">%</span>",
        "57.1 &lt; 50 = False",
        "Overall <b>FAIL</b>",
    ):
        assert fragment in plain and fragment in branded
    # Still offline and self-contained on both paths.
    assert "http" not in branded and "<script" not in branded and "<link" not in branded


@needs_sym_extra
def test_a_failing_check_does_not_fail_the_run():
    """The verdict is card content: FAIL renders on both cards, `run` is green."""
    from capacity_check_split import build_graph

    result = run(build_graph())
    assert set(result.outputs) == {
        "read_csv",
        "read_csv_2",
        "maximum",
        "minimum",
        "calc",
        "render_html",
        "render_html_2",
    }
    assert result.value("calc", "result").passed is False


@needs_sym_extra
def test_graph_declares_environment_dependencies():
    from capacity_check_split import DEPENDENCIES, build_graph

    graph = build_graph()
    assert graph.environment is not None
    assert graph.environment["network"] == "none"
    assert graph.environment["dependencies"] == DEPENDENCIES


# -- served: node ids, the Result preview, and the bijection ------------------


def _client() -> TestClient:
    workspace = make_workspace(ENTRY)
    graph = load_graph(ENTRY, workspace)
    return TestClient(
        create_app(sample_graph=graph, workspace=workspace, run_base_dir=example_dir(ENTRY))
    )


def test_the_entry_is_discoverable_by_the_picker():
    """ADR 0009: a bundled `<name>/<name>.py` is a viewable entry, no registration."""
    from server.entries import EntryCatalog

    entries = {e["id"]: e for e in EntryCatalog().discover().entries()}
    assert entries[ENTRY]["status"] == "ok", entries[ENTRY].get("error")
    assert entries[ENTRY]["title"] == "Capacity check split"


def test_served_node_ids_are_the_authored_variable_names():
    """Node id = the ``@main`` variable name (ADR 0004 D3)."""
    graph = _client().get("/api/graph").json()
    assert [n["id"] for n in graph["nodes"]] == [
        "forces",
        "members",
        "F_max",
        "C_min",
        "sheet",
        "card",
        "branded",
    ]
    assert graph["output"] == {"node": "card", "socket": "result"}
    # Served pristine: relative filenames, no absolute machine path.
    reads = [n for n in graph["nodes"] if n["type"] == "sources.read_csv"]
    assert {n["inputs"]["path"] for n in reads} == {"forces.csv", "members.csv"}


@needs_sym_extra
def test_the_result_socket_previews_as_real_json_not_a_repr():
    """The ADR 0021 D2 hook, end to end through /api/run."""
    client = _client()
    graph = client.get("/api/graph").json()
    result = client.post("/api/run", json={"graph": graph}).json()
    assert result["errors"] == []

    preview = result["outputs"]["sheet"]["result"]
    assert "$repr" not in preview  # the old degradation
    assert preview["calcsheet_result"] == 1  # the versioned archival form
    assert preview["passed"] is False
    assert [row["symbol"] for row in preview["formulas"]] == ["r", "U"]
    # The card socket is still a plain HTML string for the iframe renderer.
    assert result["outputs"]["card"]["result"].startswith("<!doctype html>")


def test_the_module_is_a_fixed_point_of_the_bijection():
    """Saving an unedited graph rewrites nothing (ADR 0004 D5 / 0020)."""
    text = _module_text()
    graph = from_composite(text, DEFAULT_REGISTRY, module_name=ENTRY)
    written = compute_writeback(text, graph, DEFAULT_REGISTRY, ENTRY)
    assert written.strategy == "unchanged"
    assert written.text == text


def test_an_edit_and_its_revert_restore_the_file_byte_for_byte():
    """The statements are already in the emitter's canonical form."""
    text = _module_text()

    edited = from_composite(text, DEFAULT_REGISTRY, module_name=ENTRY)
    next(n for n in edited.nodes if n.id == "branded").inputs["header"] = "Other Corp"
    patched = compute_writeback(text, edited, DEFAULT_REGISTRY, ENTRY)
    assert patched.strategy == "patched" and patched.changed_ids == ["branded"]
    assert "Other Corp" in patched.text

    reverted = from_composite(patched.text, DEFAULT_REGISTRY, module_name=ENTRY)
    next(n for n in reverted.nodes if n.id == "branded").inputs["header"] = "Acme Corp"
    assert compute_writeback(patched.text, reverted, DEFAULT_REGISTRY, ENTRY).text == text
