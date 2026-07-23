"""Tests for the ``capacity_check`` example (two-CSV "does it hold up?" check).

Covers, in order:

* the example-local nodes in isolation (plain Python, always run) —
  ``select_extreme`` picking the right row, ``check_verdict`` reading the
  calc's own boolean and raising on false / on a missing key (ADR 0016 D2);
* the graph end-to-end: correct extremes (max force, min capacity), the
  verdict agreeing with ``steps.results["check"]``, and a self-contained HTML
  card whose math block *is* the verdict (the substituted ``check`` row), with
  no parallel PASS/FAIL re-derivation.

Run with:  uv run --extra dev --extra sym python -m pytest -q
"""

from __future__ import annotations

import pytest

from engine import Graph, NodeExecutionError, UserError, run, to_python, validate_graph

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


def test_check_verdict_passes_silently_on_true():
    """A True `check` result is a no-op returning {ok: True} — no comparison."""
    from capacity_check import check_verdict

    out = check_verdict(results={"C_min": 210.0, "F_max": 120.0, "margin": 90.0, "check": True})
    assert out == {"ok": True}


def test_check_verdict_raises_on_false():
    """A False `check` result raises — the run reddens this node (ADR 0016 D2)."""
    from capacity_check import check_verdict

    with pytest.raises(UserError, match="Capacity check failed"):
        check_verdict(results={"margin": -20.0, "check": False})


def test_check_verdict_raises_on_missing_key_listing_available_results():
    """Criterion #5 — a missing key raises loudly, naming the available results."""
    from capacity_check import check_verdict

    with pytest.raises(UserError) as excinfo:
        check_verdict(results={"C_min": 210.0, "margin": 90.0})
    message = str(excinfo.value)
    assert "'check'" in message
    # The available result names are listed so a rename fails loudly, not stale.
    assert "C_min" in message and "margin" in message


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
def test_verdict_agrees_with_the_calc_check_result():
    """Criterion #4 — one execution feeds the math block and the verdict.

    The verdict node emits `ok` iff the calc's own `check` result is True;
    there is no second computation to disagree with.
    """
    from capacity_check import build_graph

    result = run(build_graph())
    check = result.value("handcalc", "results")["check"]

    assert check is True  # true for this example's mock data (margin 90)
    # One execution: the verdict node ran without raising (a no-op on pass)
    # precisely because the calc's own `check` is True — nothing recomputed.
    assert bool(result.value("check_verdict", "ok"))


@needs_sym_extra
def test_output_html_shows_the_substituted_check_and_is_self_contained():
    from capacity_check import build_graph

    graph = build_graph()
    result = run(graph)
    html = result.value(graph.output["node"], graph.output["socket"])

    assert isinstance(html, str) and html.startswith("<div")
    # handcalcs display: the substituted numbers are typeset as native MathML.
    assert "<math" in html and "</math>" in html
    assert "210.000" in html and "120.000" in html and "90.000" in html  # C_min, F_max, margin
    # Criterion #3 — the assertion is its own math row (equation row + check
    # row), and its boolean result is typeset (`True` as letter tokens).
    assert html.count("<math") == 2
    assert "<mi>T</mi><mi>r</mi><mi>u</mi><mi>e</mi>" in html
    # The caption (from calc_notes) restates each results symbol as `name = value`,
    # generated from handcalc.results — one source of truth (ADR 0013 Change 2).
    assert "C_min = 210" in html and "F_max = 120" in html and "margin = 90" in html
    # The boolean verdict is visible in the caption too, straight from results.
    assert "check = True" in html
    # No parallel PASS/FAIL re-derivation: neither the word nor the raw-input
    # comparison string survives (ADR 0016 criterion #1).
    assert "PASS" not in html and "FAIL" not in html
    assert "120 &lt; 210" not in html
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


# -- ADR 0016: single source of truth for the verdict -------------------------


def _edge_set(graph) -> set[tuple[str, str, str, str]]:
    return {
        (e["source"], e["sourceOutput"], e["target"], e["targetInput"])
        for e in graph.to_dict()["edges"]
    }


def test_verdict_and_caption_both_hang_off_the_calc_results():
    """The verdict and the caption are both fed from handcalc.results.

    handcalc.results feeds check_verdict (the side-assertion) AND calc_notes,
    whose text reaches render_math_card.caption directly — no join_text, no
    re-derivation over the raw extremes (ADR 0016).
    """
    from capacity_check import build_graph

    edges = _edge_set(build_graph())
    assert ("handcalc", "results", "check_verdict", "results") in edges
    assert ("handcalc", "results", "calc_notes", "results") in edges
    assert ("calc_notes", "result", "render_math_card", "caption") in edges
    # The caption wire is direct: no join_text node stands between them.
    assert not any(target == "join_text" for _, _, target, _ in edges)


def test_example_source_single_sources_the_judgment():
    """Criterion #1 — no describe(), no re-declared labels, no parallel check.

    The only comparison text in the module is the `check` calc line; the old
    `force < capacity` re-derivation and its PASS/FAIL string are gone.
    """
    import capacity_check

    with open(capacity_check.__file__, encoding="utf-8") as fh:
        source = fh.read()

    assert "describe(" not in source
    assert "sym.describe" not in source
    # The symbols are declared exactly once — inside the lines= literal. No
    # double-quoted "F_max"/"C_min" string literals (the old describe labels).
    assert '"F_max"' not in source and '"C_min"' not in source
    # No parallel re-derivation node and no joined PASS/FAIL caption fragment:
    # the old force-vs-capacity check and the join_text wire are both gone.
    assert "check_capacity" not in source
    assert "join_text" not in source
    # Sanity: the equation AND the assertion live in one two-line lines= literal.
    assert 'lines="margin = C_min - F_max\\ncheck = margin > 0"' in source


@needs_sym_extra
def test_one_edit_to_the_lines_updates_math_and_verdict_coherently():
    """Criterion #2 — editing only the `lines` literal moves everything.

    A safety factor that keeps the margin positive still passes; one that
    drives it negative flips the same `check` result to False and the verdict
    raises — no second edit, math block and judgment cannot disagree.
    """
    import capacity_check  # noqa: F401 - registers capacity_check.check_verdict

    def _run_with_factor(factor: float):
        g = Graph()
        g.add(
            "steps",
            "sym.handcalc",
            inputs={"lines": f"margin = {factor} * C_min - F_max\ncheck = margin > 0", "C_min": 210.0, "F_max": 120.0},
        )
        g.add("verdict", "capacity_check.check_verdict")
        g.add("notes", "sym.calc_notes")
        g.connect("steps", "results", "verdict", "results")
        g.connect("steps", "results", "notes", "results")
        g.output = {"node": "notes", "socket": "result"}
        return g

    # 0.9 * 210 - 120 = 69 > 0 → passes; notes reflect the new margin.
    caption = run(_run_with_factor(0.9)).value("notes")
    assert "margin = 69" in caption and "check = True" in caption

    # 0.5 * 210 - 120 = -15 → check flips to False and the verdict raises.
    with pytest.raises(NodeExecutionError, match="is False"):
        run(_run_with_factor(0.5))


@needs_sym_extra
def test_renaming_the_check_symbol_fails_loudly_through_run():
    """Criterion #5 — rename the assertion symbol and forget the param → loud.

    The calc names its boolean `verdict_flag`; check_verdict still reads
    `check` and raises, listing the available results — never a stale verdict.
    """
    import capacity_check  # noqa: F401 - registers capacity_check.check_verdict

    g = Graph()
    g.add(
        "steps",
        "sym.handcalc",
        inputs={"lines": "margin = C_min - F_max\nverdict_flag = margin > 0", "C_min": 210.0, "F_max": 120.0},
    )
    g.add("verdict", "capacity_check.check_verdict")
    g.connect("steps", "results", "verdict", "results")
    g.output = {"node": "verdict", "socket": "ok"}

    with pytest.raises(NodeExecutionError) as excinfo:
        run(g)
    message = str(excinfo.value)
    assert "'check'" in message and "verdict_flag" in message


@needs_sym_extra
def test_caption_follows_a_renamed_symbol_with_no_further_edits():
    """Rename F_max → F_app in the equation and the caption follows.

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
    """Every results symbol appears as `symbol = value`; none is absent.

    With the assertion line, `check` is one of the results — so the caption
    carries it too, straight from the calc.
    """
    from capacity_check import build_graph

    result = run(build_graph())
    results = result.value("handcalc", "results")
    caption = result.value("calc_notes")

    assert "check" in results  # the assertion is a computed result now
    for symbol in results:
        assert f"{symbol} = " in caption
    # No symbol in the caption that is absent from results: the caption's LHS
    # tokens are exactly the results keys.
    caption_symbols = {part.split(" = ")[0] for part in caption.split(" · ")}
    assert caption_symbols == set(results)
