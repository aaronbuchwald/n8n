"""Tests for the decorated minimal example + the tracing layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine import TracingError, main, node, run, to_python, validate_graph, validate_node_spec

from minimal import CSV_PATH, NODES, build_graph, readings_report

SCHEMAS = Path(__file__).resolve().parents[1] / "engine" / "schemas"


def test_trace_shape():
    g = build_graph()
    assert {n.type for n in g.nodes} == {
        "minimal.read_values",
        "minimal.total",
        "minimal.average",
        "minimal.render_summary",
    }
    pairs = {(e.source, e.target) for e in g.edges}
    assert ("read_values", "total") in pairs
    assert ("read_values", "average") in pairs
    assert ("total", "render_summary") in pairs
    assert ("average", "render_summary") in pairs
    assert g.output == {"node": "render_summary", "socket": "result"}
    validate_graph(g.to_dict())


def test_output_survives_json_roundtrip():
    g = build_graph()
    from engine import Graph

    restored = Graph.from_json(g.to_json())
    assert restored.output == g.output
    assert restored.to_dict() == g.to_dict()


def test_run_matches_expected():
    g = build_graph()
    result = run(g)
    assert result.value("total") == 100.0
    assert result.value("average") == 25.0
    html = result.value(g.output["node"], g.output["socket"])
    assert "Total: <b>100</b>" in html
    assert "Average: <b>25</b>" in html


def test_export_round_trips():
    g = build_graph()
    script = to_python(g)
    namespace: dict = {}
    exec(compile(script, "<exported>", "exec"), namespace)  # noqa: S102 - trusted, generated
    assert namespace["_render_summary"] == run(g).value(g.output["node"], g.output["socket"])


def test_composite_runs_eagerly():
    html = readings_report(path=str(CSV_PATH))
    assert "Total:" in html


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


def test_snapshots_match():
    specs = json.loads((SCHEMAS / "example.node-specs.json").read_text())
    assert specs == {n.id: n.spec for n in NODES}, "run: uv run python freeze_schemas.py"
    for spec in specs.values():
        validate_node_spec(spec)

    graph = json.loads((SCHEMAS / "example.graph.json").read_text())
    assert graph == build_graph("readings.csv").to_dict(), "run: uv run python freeze_schemas.py"
    validate_graph(graph)
