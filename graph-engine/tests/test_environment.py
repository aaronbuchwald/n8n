"""Tests for the optional, declarative graph-level ``environment`` descriptor.

Covers ADR 0003: a present block validates and round-trips through JSON; a
malformed block is rejected by ``validate_graph``; and — critically — a graph
*without* the block is byte-identical before and after a ``to_dict`` →
``from_dict`` round-trip (so existing graphs and the golden snapshots don't
move).

Schema only — nothing here runs a graph or installs anything. Run with:
    uv run --extra dev pytest tests/ -q
"""

import json

import pytest

from engine import Graph, SchemaError, validate_graph


def _graph_with_environment(environment: dict) -> dict:
    return {
        "version": "0.2.0",
        "nodes": [{"id": "a", "type": "pkg.f", "inputs": {}, "position": None}],
        "edges": [],
        "output": None,
        "environment": environment,
    }


# -- present block: validates + round-trips --------------------------------


def test_full_environment_validates():
    env = {
        "dependencies": [{"name": "sympy", "version": "1.13.*"}],
        "mounts": [{"path": "readings.csv", "mode": "ro"}],
        "network": "none",
    }
    graph = _graph_with_environment(env)
    assert validate_graph(graph) is graph


def test_empty_environment_validates():
    # An explicit but empty descriptor (all deny-all defaults) is valid.
    graph = _graph_with_environment({})
    assert validate_graph(graph) is graph


def test_environment_round_trips_through_json():
    env = {
        "dependencies": [{"name": "sympy", "version": "1.13.*"}],
        "mounts": [{"path": "out.csv", "mode": "rw"}, {"path": "in.csv", "mode": "ro"}],
        "network": "none",
    }
    g = Graph.from_dict(_graph_with_environment(env))
    assert g.environment == env

    restored = Graph.from_dict(json.loads(g.to_json()))
    assert restored.environment == env
    assert restored.to_dict() == g.to_dict()


def test_dependency_without_version_is_allowed():
    graph = _graph_with_environment({"dependencies": [{"name": "sympy"}]})
    assert validate_graph(graph) is graph


# -- malformed block: rejected ---------------------------------------------


def test_bad_mount_mode_rejected():
    graph = _graph_with_environment({"mounts": [{"path": "x.csv", "mode": "wx"}]})
    with pytest.raises(SchemaError, match="mode"):
        validate_graph(graph)


def test_network_other_than_none_rejected():
    graph = _graph_with_environment({"network": "full"})
    with pytest.raises(SchemaError, match="network"):
        validate_graph(graph)


def test_dependency_without_name_rejected():
    graph = _graph_with_environment({"dependencies": [{"version": "1.0"}]})
    with pytest.raises(SchemaError, match="name"):
        validate_graph(graph)


def test_mount_without_mode_rejected():
    graph = _graph_with_environment({"mounts": [{"path": "x.csv"}]})
    with pytest.raises(SchemaError, match="mode"):
        validate_graph(graph)


def test_non_object_environment_rejected():
    graph = _graph_with_environment("stdlib")  # type: ignore[arg-type]
    with pytest.raises(SchemaError, match="environment"):
        validate_graph(graph)


# -- absent block: no drift ------------------------------------------------


def test_absent_environment_omitted_from_to_dict():
    g = Graph().add("a", "pkg.f")
    assert g.environment is None
    assert "environment" not in g.to_dict()


def test_graph_without_environment_is_byte_identical_round_trip():
    g = Graph().add("a", "pkg.f", inputs={"x": 1}).add("b", "pkg.f")
    g.connect("a", "result", "b", "x")

    before = g.to_json()
    after = Graph.from_dict(g.to_dict()).to_json()
    assert before == after
    assert "environment" not in json.loads(before)


def test_validate_graph_tolerates_absent_environment():
    graph = {
        "version": "0.2.0",
        "nodes": [{"id": "a", "type": "pkg.f"}],
        "edges": [],
    }
    assert validate_graph(graph) is graph
