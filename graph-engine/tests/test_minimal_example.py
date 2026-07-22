"""Tests for the smallest example graph (examples/minimal/minimal.py)."""

from __future__ import annotations

from minimal import build_graph, build_registry

from engine import run, to_python


def test_runs_and_renders():
    result = run(build_graph(), build_registry())
    assert result.value("sum") == 100.0
    assert result.value("avg") == 25.0
    html = result.value("card")
    assert "Total: <b>100</b>" in html
    assert "Average: <b>25</b>" in html


def test_export_round_trips():
    reg = build_registry()
    g = build_graph()
    script = to_python(g, reg)
    namespace: dict = {}
    exec(compile(script, "<exported>", "exec"), namespace)  # noqa: S102 - trusted, generated
    assert namespace["_card"] == run(g, reg).value("card")
