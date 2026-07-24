"""Tests for the ``capacity_check`` example (two CSV arcs → one calc card).

Covers, in order:

* the graph's shape — five nodes, "read → select → calc", with both extremes
  wired into the ``sheet.calc_card`` node's *derived* symbol sockets;
* the graph end-to-end: correct extremes (max force 120, min capacity 210) and
  a self-contained HTML card carrying ``r = 0.571``, ``U = 57.1 %``, one PASS
  and one FAIL check, and an overall FAIL verdict;
* that a false check is **card content, not an error**: the run stays green;
* the symbols are single-sourced — declared once, in the ``formulas`` literal.

Run with:  uv run --extra dev --extra sym python -m pytest -q
"""

from __future__ import annotations

import pytest

from engine import run, to_python, validate_graph

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


# -- the graph's shape (no heavy deps needed) ---------------------------------


def test_graph_is_five_nodes_read_select_calc():
    """Two reads, two reductions, one card — no example-local glue nodes."""
    from capacity_check import build_graph

    doc = build_graph().to_dict()
    assert [n["type"] for n in doc["nodes"]] == [
        "sources.read_csv",
        "sources.read_csv",
        "calc.maximum",
        "calc.minimum",
        "sheet.calc_card",
    ]
    # Each read names the column it pulls; read_csv yields bare floats.
    columns = {n["inputs"]["column"] for n in doc["nodes"] if n["type"] == "sources.read_csv"}
    assert columns == {"force", "capacity"}


def test_extremes_are_wired_into_the_calc_cards_derived_sockets():
    """`F_max`/`C_min` are derived from the formulas and fed by the reductions.

    They are input sockets only because the formulas *read* them before any
    formula defines them (ADR 0007) — so the wires prove the derivation.
    """
    from capacity_check import build_graph

    edges = _edge_set(build_graph())
    assert ("maximum", "result", "calc_card", "F_max") in edges
    assert ("minimum", "result", "calc_card", "C_min") in edges
    # The reductions read the CSVs, not each other.
    assert ("read_csv", "result", "maximum", "values") in edges
    assert ("read_csv_2", "result", "minimum", "values") in edges


def test_the_card_is_the_graph_output():
    from capacity_check import build_graph

    assert build_graph().output == {"node": "calc_card", "socket": "result"}


def test_formulas_and_checks_carry_their_references_and_unit():
    """The mini-syntax is authored in the literal: `# ref`, `[unit]`, `# text`."""
    from capacity_check import build_graph

    card = next(n for n in build_graph().to_dict()["nodes"] if n["type"] == "sheet.calc_card")
    assert card["inputs"]["formulas"] == (
        "r = F_max / C_min  # demand / capacity\nU = 100 * r [%]  # utilisation"
    )
    assert card["inputs"]["checks"] == (
        "U < 100  # capacity not exceeded\nU < 50  # utilisation target"
    )
    # `as_of` is authored, never taken from the clock.
    assert card["inputs"]["as_of"] == "2026-07-24"


def test_example_source_single_sources_the_symbols():
    """The symbols are declared exactly once — inside the `formulas` literal.

    No example-local node re-implements selection or judgement any more: the
    reductions come from the `calc` pack and the verdict from the calc itself.
    """
    import capacity_check

    with open(capacity_check.__file__, encoding="utf-8") as fh:
        source = fh.read()

    assert "@node" not in source  # no example-local node definitions
    assert "select_extreme" not in source and "check_verdict" not in source
    # The old handcalc → latex_to_mathml → calc_notes → render_math_card chain
    # is gone: nothing from the `sym` pack is imported any more.
    assert "from sym import" not in source
    # `F_max`/`C_min` appear as the formulas' symbols and as variable names —
    # never as re-declared string labels.
    assert '"F_max"' not in source and '"C_min"' not in source


# -- the example graph, end-to-end --------------------------------------------


@needs_sym_extra
def test_graph_loads_binds_and_runs_end_to_end():
    from capacity_check import build_graph

    graph = build_graph()
    validate_graph(graph.to_dict())  # loads/binds structurally
    result = run(graph)  # binds + executes

    # Arc 1: highest force is 120 (names are deliberately dropped by read_csv).
    assert result.value("maximum") == 120.0
    # Arc 2: lowest capacity is 210.
    assert result.value("minimum") == 210.0


@needs_sym_extra
def test_output_html_carries_the_computed_values_and_verdicts():
    from capacity_check import build_graph

    graph = build_graph()
    result = run(graph)
    html = result.value(graph.output["node"], graph.output["socket"])

    assert isinstance(html, str) and html.startswith("<!doctype html>")
    # Inputs, then the two formula rows, at 3 significant digits.
    assert '<span class="val">120</span>' in html
    assert '<span class="val">210</span>' in html
    assert '<span class="val">0.571</span>' in html
    assert '57.1&nbsp;<span class="unit">%</span>' in html
    # The authored references land in the right-hand gutter.
    assert '<span class="ref">demand / capacity</span>' in html
    assert '<span class="ref">utilisation</span>' in html
    # One check passes, one fails, each with its substituted boolean.
    assert "57.1 &lt; 100 = True" in html and 'badge--pass">PASS' in html
    assert "57.1 &lt; 50 = False" in html and 'badge--fail">FAIL' in html
    # Binary severity: any false check makes the whole card FAIL.
    assert 'class="status status--fail"' in html
    assert "Overall <b>FAIL</b>" in html
    # Math is native MathML — no script, no CDN, no external reference.
    assert "<math" in html and "</math>" in html
    assert "http" not in html
    assert "<script" not in html and "<link" not in html and "@import" not in html


@needs_sym_extra
def test_a_failing_check_does_not_fail_the_run():
    """The verdict is card content: FAIL renders, `run` raises nothing."""
    from capacity_check import build_graph

    # A false check used to raise (the old check_verdict node). It no longer
    # does: `run` completes, every node produced its outputs, and the FAIL
    # lives on the card.
    result = run(build_graph())
    assert set(result.outputs) == {"read_csv", "read_csv_2", "maximum", "minimum", "calc_card"}
    assert "Overall <b>FAIL</b>" in result.value("calc_card", "result")


@needs_sym_extra
def test_card_height_scales_with_the_content():
    """The `height` socket sizes the sandboxed iframe from outside it."""
    from sheet import card_height

    from capacity_check import build_graph

    height = run(build_graph()).value("calc_card", "height")
    # 2 inputs + 2 formulas + 2 described checks — the same arithmetic the
    # renderer trusts, asserted against the pack's own function.
    assert height == card_height(2, 2, ["capacity not exceeded", "utilisation target"])
    # A bigger sheet needs a taller surface; an empty one still has a floor.
    assert card_height(4, 4, ["a", "b", "c"]) > height
    assert card_height(0, 0, []) >= 160


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
    assert namespace["_calc_card"]["result"] == run(graph).value(
        graph.output["node"], graph.output["socket"]
    )


# -- one edit to the calc moves everything ------------------------------------


@needs_sym_extra
def test_one_edit_to_the_formulas_moves_the_values_and_the_verdict():
    """Editing only the `formulas` literal moves the numbers AND the verdict.

    A tighter utilisation formula flips the same check from FAIL to PASS with
    no second edit anywhere: the card is a pure function of the one evaluation.
    """
    import sheet

    def _card(formulas: str) -> str:
        return sheet.calc_card(
            title="Capacity check",
            as_of="2026-07-24",
            formulas=formulas,
            checks="U < 50  # utilisation target",
            F_max=120.0,
            C_min=210.0,
        )["result"]

    fails = _card("r = F_max / C_min\nU = 100 * r [%]")
    assert "57.1 &lt; 50 = False" in fails and "Overall <b>FAIL</b>" in fails

    # Halve the demand: 28.6 % clears the 50 % target, same checks literal.
    passes = _card("r = 0.5 * F_max / C_min\nU = 100 * r [%]")
    assert "28.6 &lt; 50 = True" in passes and "Overall <b>PASS</b>" in passes
