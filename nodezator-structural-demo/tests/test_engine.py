"""Phase-0 engine tests: introspection, schema, run, and the graph->Python round-trip.

Run with:  uv run --extra dev pytest tests/ -q
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from demolib.data import unpack_member
from demolib.mechanics import axial_stress
from demo_graph import build_graph, build_registry

from engine import (
    GRAPH_SCHEMA,
    NODE_SPEC_SCHEMA,
    CycleError,
    Graph,
    UnknownNodeType,
    node_spec,
    run,
    to_python,
    validate_graph,
    validate_node_spec,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCHEMAS = ROOT / "engine" / "schemas"


# --------------------------------------------------------------------------
# node_spec — introspection
# --------------------------------------------------------------------------


def test_multi_output_from_annotation():
    spec = node_spec(unpack_member)
    assert [o["name"] for o in spec["outputs"]] == [
        "name",
        "force_kN",
        "width_mm",
        "thickness_mm",
        "fy_MPa",
    ]
    validate_node_spec(spec)


def test_single_output_and_widgets():
    spec = node_spec(axial_stress)
    assert len(spec["outputs"]) == 1
    assert spec["outputs"][0] == {"name": "output", "type": "si.Physical"}
    force = next(i for i in spec["inputs"] if i["name"] == "force_kN")
    assert force["widget"] == {"kind": "number", "subtype": "float"}
    assert force["default"] == 100.0
    assert force["required"] is False


def test_output_override_exposes_dict_keys():
    reg = build_registry()
    spec = reg.spec("render_stress_check")
    assert [o["name"] for o in spec["outputs"]] == ["latex", "utilisation", "summary"]


# --------------------------------------------------------------------------
# Graph model + schema
# --------------------------------------------------------------------------


def test_graph_json_roundtrip():
    g = build_graph(index=0)
    restored = Graph.from_json(g.to_json())
    assert restored.to_dict() == g.to_dict()
    validate_graph(g.to_dict())


def test_validate_graph_rejects_dangling_edge():
    bad = {
        "version": "0.1.0",
        "nodes": [{"id": "a", "type": "x"}],
        "edges": [
            {"source": "a", "sourceOutput": "output", "target": "ghost", "targetInput": "y"}
        ],
    }
    with pytest.raises(Exception):
        validate_graph(bad)


# --------------------------------------------------------------------------
# run — execution
# --------------------------------------------------------------------------


def test_run_matches_baseline_pass():
    reg = build_registry()
    result = run(build_graph(index=0), reg)
    assert result.value("report", "utilisation") == 0.8
    assert result.value("check").startswith("PASS")


def test_run_failing_member_raises_assertion():
    reg = build_registry()
    # Member index 1 is overstressed (utilisation 1.2) -> assertion node raises.
    with pytest.raises(AssertionError):
        run(build_graph(index=1), reg)


def test_unknown_node_type():
    reg = build_registry()
    g = Graph().add("a", "does_not_exist")
    with pytest.raises(UnknownNodeType):
        run(g, reg)


def test_cycle_detection():
    reg = build_registry()
    g = Graph()
    g.add("a", "select_member")
    g.add("b", "select_member")
    g.connect("a", "output", "b", "rows")
    g.connect("b", "output", "a", "rows")
    with pytest.raises(CycleError):
        run(g, reg)


# --------------------------------------------------------------------------
# to_python — the round-trip (graph -> Python -> run -> same result)
# --------------------------------------------------------------------------


def test_exported_python_reproduces_result():
    reg = build_registry()
    graph = build_graph(index=0)
    engine_result = run(graph, reg).value("report", "utilisation")

    script = to_python(graph, reg)
    namespace: dict = {}
    exec(compile(script, "<exported>", "exec"), namespace)  # noqa: S102 - trusted, generated

    assert namespace["_report"]["utilisation"] == engine_result == 0.8
    assert namespace["_check"].startswith("PASS")


# --------------------------------------------------------------------------
# Frozen schema files stay in sync with the in-code contract
# --------------------------------------------------------------------------


def test_frozen_schema_files_match_code():
    node = json.loads((SCHEMAS / "node-spec.schema.json").read_text())
    graph = json.loads((SCHEMAS / "graph.schema.json").read_text())
    assert node == NODE_SPEC_SCHEMA, "run: uv run python freeze_schemas.py"
    assert graph == GRAPH_SCHEMA, "run: uv run python freeze_schemas.py"


def test_frozen_examples_validate():
    specs = json.loads((SCHEMAS / "example.node-specs.json").read_text())
    for spec in specs.values():
        validate_node_spec(spec)
    graph = json.loads((SCHEMAS / "example.beam-graph.json").read_text())
    validate_graph(graph)
