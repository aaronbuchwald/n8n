"""Tests for the ``handcalc_demo`` example — the dynamic-calc reference graph.

``capacity_check`` moved to ``sheet.calc_card``, so this example is what keeps a
served graph carrying a dynamic ``sym.handcalc`` node: derived symbol sockets
wired from two reductions, and a card whose math block *is* the verdict. It is
the target the calc-widget / lines-preview / inspector-value browser specs
drive, so these tests pin the shape those specs depend on.

Run with:  uv run --extra dev --extra sym python -m pytest -q
"""

from __future__ import annotations

import pytest

from engine import run, validate_graph
from server.demo import load_graph, make_workspace

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

# The equation the calc-widget spec types against; a change here is a change to
# that spec's ORIGINAL_EQ.
EQUATION = "margin = C_min - F_max\ncheck = margin > 0"


def test_served_graph_has_the_shape_the_calc_widget_spec_drives():
    """Node ids `steps` + `max_force`, and both derived sockets wired.

    The widget spec targets `steps` and asserts the prune toast names
    `max_force`, so those ids are part of this example's contract.
    """
    graph = load_graph("handcalc_demo", make_workspace("handcalc_demo"))
    by_id = {n["id"]: n for n in graph["nodes"]}
    assert by_id["steps"]["type"] == "sym.handcalc"
    assert by_id["steps"]["inputs"]["lines"] == EQUATION
    assert by_id["max_force"]["type"] == "calc.maximum"
    assert by_id["min_capacity"]["type"] == "calc.minimum"

    wires = {
        (e["source"], e["target"], e["targetInput"])
        for e in graph["edges"]
    }
    assert ("max_force", "steps", "F_max") in wires
    assert ("min_capacity", "steps", "C_min") in wires


def test_the_equations_free_symbols_are_the_derived_sockets():
    from sym import calc_free_symbols

    assert [i["name"] for i in calc_free_symbols(EQUATION)] == ["C_min", "F_max"]


@needs_sym_extra
def test_graph_runs_end_to_end_to_a_self_contained_card():
    from handcalc_demo import build_graph

    graph = build_graph()
    validate_graph(graph.to_dict())
    result = run(graph)

    assert result.value("maximum") == 120.0
    assert result.value("minimum") == 210.0
    # The calc's own results carry the equation's symbols and its verdict.
    results = result.value("handcalc", "results")
    assert set(results) == {"C_min", "F_max", "margin", "check"}
    assert results["margin"] == 90.0 and results["check"] is True

    html = result.value(graph.output["node"], graph.output["socket"])
    # The substituted comparison IS the verdict, typeset as native MathML.
    assert html.count("<math") == 2
    assert "<mi>T</mi><mi>r</mi><mi>u</mi><mi>e</mi>" in html
    assert "http" not in html and "<script" not in html and "<link" not in html


@needs_sym_extra
def test_graph_declares_environment_dependencies():
    from handcalc_demo import DEPENDENCIES, build_graph

    graph = build_graph()
    assert graph.environment is not None
    assert graph.environment["network"] == "none"
    assert {d["name"] for d in graph.environment["dependencies"]} == set(HEAVY_DEPS)
    assert graph.environment["dependencies"] == DEPENDENCIES
