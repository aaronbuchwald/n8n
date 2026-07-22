"""Tests for the decorated minimal example + the tracing layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine import TracingError, main, node, run, to_python, validate_graph, validate_node_spec

from minimal import CSV_PATH, NODES, build_graph, readings_report

SCHEMAS = Path(__file__).resolve().parents[1] / "engine" / "schemas"


# -- tracing produces the right graph --------------------------------------


def test_trace_shape():
    g = build_graph()
    assert {n.type for n in g.nodes} == {"read_values", "total", "average", "render_summary"}
    # read_values fans out to both processors; render joins them.
    pairs = {(e.source, e.target) for e in g.edges}
    assert ("read_values", "total") in pairs
    assert ("read_values", "average") in pairs
    assert ("total", "render_summary") in pairs
    assert ("average", "render_summary") in pairs
    assert g.output_id == "render_summary"
    validate_graph(g.to_dict())


def test_run_matches_expected():
    g = build_graph()
    result = run(g)
    assert result.value("total") == 100.0
    assert result.value("average") == 25.0
    html = result.value(g.output_id)
    assert "Total: <b>100</b>" in html
    assert "Average: <b>25</b>" in html


def test_export_round_trips():
    g = build_graph()
    script = to_python(g)
    namespace: dict = {}
    exec(compile(script, "<exported>", "exec"), namespace)  # noqa: S102 - trusted, generated
    assert namespace["_render_summary"] == run(g).value(g.output_id)


def test_composite_runs_eagerly():
    # Called normally (no trace) the composite just computes the real result.
    html = readings_report(path=str(CSV_PATH))
    assert "Total:" in html


# -- the dataflow boundary is enforced -------------------------------------


def test_branching_on_a_traced_value_raises():
    @node
    def load(path: str = "x") -> list:
        return []

    @main
    def bad(path: str = "x") -> list:
        xs = load(path)
        if xs:  # branching on a traced handle
            return xs
        return xs

    with pytest.raises(TracingError):
        bad.to_graph()


# -- golden snapshots stay in sync -----------------------------------------


def test_snapshots_match():
    specs = json.loads((SCHEMAS / "example.node-specs.json").read_text())
    assert specs == {n.name: n.spec for n in NODES}, "run: uv run python freeze_schemas.py"
    for spec in specs.values():
        validate_node_spec(spec)

    graph = json.loads((SCHEMAS / "example.graph.json").read_text())
    assert graph == build_graph("readings.csv").to_dict(), "run: uv run python freeze_schemas.py"
    validate_graph(graph)
