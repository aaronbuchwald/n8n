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

from engine import Graph, UserError, run, to_python, validate_graph

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
    # The caption (from calc_notes) restates each results symbol as `name = value`,
    # generated from handcalc.results — one source of truth (ADR 0013 Change 2).
    assert "C_min = 210" in html and "F_max = 120" in html and "margin = 90" in html
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


# -- ADR 0013 Change 2: single source of truth for the caption ----------------


def _edge_set(graph) -> set[tuple[str, str, str, str]]:
    return {
        (e["source"], e["sourceOutput"], e["target"], e["targetInput"])
        for e in graph.to_dict()["edges"]
    }


def test_caption_is_wired_from_handcalc_results_through_calc_notes():
    """2.1 — the handcalc → caption dependency is now an explicit wire.

    handcalc.results feeds calc_notes, whose text reaches
    render_math_card.caption via join_text — the diamond the ADR made honest.
    """
    from capacity_check import build_graph

    edges = _edge_set(build_graph())
    assert ("handcalc", "results", "calc_notes", "results") in edges
    assert ("calc_notes", "result", "join_text", "a") in edges
    assert ("join_text", "result", "render_math_card", "caption") in edges


def test_example_source_no_longer_redeclares_the_symbols():
    """2.2 — no describe() and no re-declared symbol labels outside the equation."""
    import capacity_check

    with open(capacity_check.__file__, encoding="utf-8") as fh:
        source = fh.read()

    assert "describe(" not in source
    assert "sym.describe" not in source
    # The symbols are declared exactly once — inside the lines= equation. No
    # double-quoted "F_max"/"C_min" string literals (the old describe labels).
    assert '"F_max"' not in source and '"C_min"' not in source
    # Sanity: the equation itself still carries the symbols.
    assert 'lines="margin = C_min - F_max"' in source


@needs_sym_extra
def test_caption_follows_a_renamed_symbol_with_no_further_edits():
    """2.3 — rename F_max → F_app in the equation and the caption follows.

    Nothing else changes: calc_notes reads whatever keys results carries.
    """
    import sym  # noqa: F401 - registers sym.* into the default registry

    g = Graph()
    g.add(
        "steps",
        "sym.handcalc",
        inputs={"lines": "margin = C_min - F_app", "C_min": 210.0, "F_app": 120.0},
    )
    g.add("notes", "sym.calc_notes")
    g.connect("steps", "results", "notes", "results")
    g.output = {"node": "notes", "socket": "result"}

    caption = run(g).value("notes")
    assert "F_app = 120" in caption
    assert "F_max" not in caption
    assert "C_min = 210" in caption and "margin = 90" in caption


@needs_sym_extra
def test_caption_covers_exactly_the_results_symbols():
    """2.4 — every results symbol appears as `symbol = value`; none is absent."""
    from capacity_check import build_graph

    result = run(build_graph())
    results = result.value("handcalc", "results")
    caption = result.value("calc_notes")

    for symbol in results:
        assert f"{symbol} = " in caption
    # No symbol in the caption that is absent from results: the caption's LHS
    # tokens are exactly the results keys.
    caption_symbols = {part.split(" = ")[0] for part in caption.split(" · ")}
    assert caption_symbols == set(results)
