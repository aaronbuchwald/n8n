"""Tests for the ``capacity_check`` example (two-CSV "does it hold up?" check).

Covers, in order:

* the example-local nodes in isolation (plain Python, always run) —
  ``select_extreme`` picking the right row, ``check_capacity`` building a
  PASS/FAIL verdict for both outcomes;
* the graph end-to-end: correct extremes (max force, min capacity), the
  verdict matching ``force < capacity``, and a self-contained HTML card
  (native MathML present, no ``http``/``<script>`` references).

Run with:  uv run --extra dev --extra sym python -m pytest -q
"""

from __future__ import annotations

import pytest

from engine import UserError, run, to_python, validate_graph

HEAVY_DEPS = ("sympy", "handcalcs", "forallpeople", "latex2mathml")


def _sym_deps_available() -> bool:
    for name in HEAVY_DEPS:
        try:
            __import__(name)
        except ImportError:
            return False
    return True


needs_sym_extra = pytest.mark.skipif(
    not _sym_deps_available(), reason="sym extra not installed"
)


# -- example-local nodes, in isolation ----------------------------------------


def test_select_extreme_picks_the_max_row():
    from capacity_check import select_extreme

    table = {"columns": ["name", "force"], "rows": [["F1", 80.0], ["F2", 120.0], ["F3", 45.0]]}
    out = select_extreme(table, column="force", mode="max")
    assert out == {"name": "F2", "value": 120.0}


def test_select_extreme_picks_the_min_row():
    from capacity_check import select_extreme

    table = {
        "columns": ["name", "capacity"],
        "rows": [["M1", 300.0], ["M2", 210.0], ["M3", 275.0]],
    }
    out = select_extreme(table, column="capacity", mode="min")
    assert out == {"name": "M2", "value": 210.0}


def test_select_extreme_rejects_bad_mode():
    from capacity_check import select_extreme

    table = {"columns": ["name", "force"], "rows": [["F1", 1.0]]}
    with pytest.raises(UserError, match="mode"):
        select_extreme(table, column="force", mode="sideways")


def test_select_extreme_rejects_missing_column():
    from capacity_check import select_extreme

    table = {"columns": ["name", "force"], "rows": [["F1", 1.0]]}
    with pytest.raises(UserError, match="capacity"):
        select_extreme(table, column="capacity", mode="max")


def test_check_capacity_pass_verdict():
    from capacity_check import check_capacity

    out = check_capacity(force=120.0, capacity=210.0)
    assert out == {"ok": True, "text": "PASS — 120 < 210"}


def test_check_capacity_fail_verdict():
    from capacity_check import check_capacity

    out = check_capacity(force=300.0, capacity=210.0)
    assert out["ok"] is False
    assert out["text"] == "FAIL — 300 ≥ 210"


def test_pack_values_bundles_the_handcalcs_substitution_map():
    from capacity_check import pack_values

    assert pack_values(force=120.0, capacity=210.0) == {"F_max": 120.0, "C_min": 210.0}


# -- the example graph, end-to-end --------------------------------------------


@needs_sym_extra
def test_graph_loads_binds_and_runs_end_to_end():
    from capacity_check import build_graph

    graph = build_graph()
    validate_graph(graph.to_dict())  # loads/binds structurally
    result = run(graph)  # binds + executes

    # Arc 1: highest force is F2 at 120.
    assert result.outputs["select_extreme"] == {"name": "F2", "value": 120.0}
    # Arc 2: lowest capacity is M2 at 210.
    assert result.outputs["select_extreme_2"] == {"name": "M2", "value": 210.0}


@needs_sym_extra
def test_verdict_matches_force_less_than_capacity():
    from capacity_check import build_graph

    result = run(build_graph())
    force = result.value("select_extreme", "value")
    capacity = result.value("select_extreme_2", "value")
    verdict = result.outputs["check_capacity"]

    assert verdict["ok"] == (force < capacity)
    assert verdict["ok"] is True  # true for this example's mock data
    assert f"{force:g}" in verdict["text"] and f"{capacity:g}" in verdict["text"]


@needs_sym_extra
def test_output_html_shows_values_and_verdict_and_is_self_contained():
    from capacity_check import build_graph

    graph = build_graph()
    result = run(graph)
    html = result.value(graph.output["node"], graph.output["socket"])

    assert isinstance(html, str) and html.startswith("<div")
    # handcalcs display: the substituted numbers are typeset as native MathML.
    assert "<math" in html and "</math>" in html
    assert "210.000" in html and "120.000" in html and "90.000" in html  # C_min, F_max, margin
    # The separate check node's verdict is shown too (not just the numbers).
    assert "PASS" in html and "120 &lt; 210" in html
    # Self-contained: no external/CDN references, no script.
    assert "http" not in html
    assert "<script" not in html and "<link" not in html and "@import" not in html


@needs_sym_extra
def test_graph_declares_environment_dependencies():
    from capacity_check import DEPENDENCIES, build_graph

    graph = build_graph()
    assert graph.environment is not None
    assert graph.environment["network"] == "none"
    declared = {d["name"] for d in graph.environment["dependencies"]}
    assert declared == set(HEAVY_DEPS)
    assert graph.environment["dependencies"] == DEPENDENCIES


@needs_sym_extra
def test_graph_exports_python():
    from capacity_check import build_graph

    script = to_python(build_graph())
    namespace: dict = {}
    exec(compile(script, "<exported>", "exec"), namespace)  # noqa: S102 - trusted, generated
    graph = build_graph()
    assert namespace["_render_math_card"] == run(graph).value(
        graph.output["node"], graph.output["socket"]
    )
