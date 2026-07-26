"""Tests for the ``beam_bearing_pressure`` example (a real EC5 support check).

Covers, in order:

* the graph's shape — one JSON read fanning out to nine independent ``pick``
  nodes, all meeting at one ``sheet.calc_card``;
* every computed number individually, not just the verdict;
* the empty given ``l_1``: it renders ``–``, the ``MinDefined`` rule is shown in
  full, and the value is the resolved minimum;
* that a failing check is **card content, not an error**: the run stays green;
* the module is a fixed point of the graph⟷source bijection.

Run with:  uv run --extra dev --extra sym python -m pytest -q
"""

from __future__ import annotations

import json

import pytest

from engine import DEFAULT_REGISTRY, from_composite, run, to_python, validate_graph
from server.demo import example_dir
from server.writeback import compute_writeback

ENTRY = "beam_bearing_pressure"
HEAVY_DEPS = ("calcsheet", "sympy", "latex2mathml")

# The numbers the source sheet computes, to full double precision. Asserted one
# by one: a card that agrees only on the verdict is not a reproduction.
SIGMA_C90D = 4.421487603305785  # 107000 N / 24200 mm²
F_C90D = 1.7307692307692306  # 0.90 · 2.50 / 1.30, in IEEE-754 doubles
ETA = 145.97927325200052  # exactly 1112800/7623 %


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


def _module_text() -> str:
    return (example_dir(ENTRY) / f"{ENTRY}.py").read_text(encoding="utf-8")


def _rows(result) -> dict[str, object]:
    return {row.symbol: row for row in (*result.inputs, *result.formulas)}


def _result():
    """The card's own ``Result`` — the graph's numbers, not a re-derivation.

    Fed exactly as the graph feeds it: one ``pick`` per given, in the order the
    card's derived sockets are declared (which is row order on the card).
    """
    import sheet
    import sources
    from beam_bearing_pressure import INPUTS_JSON, build_graph

    card = next(
        n for n in build_graph().to_dict()["nodes"] if n["type"] == "sheet.calc_card"
    )
    data = sources.read_json(str(INPUTS_JSON))
    sockets = [s["name"] for s in sheet.formula_free_symbols(card["inputs"]["formulas"])]
    values = {key: sources.pick(data, key) for key in sockets}
    return sheet.calc(
        title=card["inputs"]["title"],
        as_of=card["inputs"]["as_of"],
        formulas=card["inputs"]["formulas"],
        checks=card["inputs"]["checks"],
        precision=card["inputs"]["precision"],
        **values,
    )


# -- the graph's shape (no heavy deps needed) ---------------------------------


def test_graph_is_one_read_nine_picks_and_one_card():
    from beam_bearing_pressure import build_graph

    doc = build_graph().to_dict()
    assert [n["type"] for n in doc["nodes"]] == [
        "sources.read_json",
        *["sources.pick"] * 9,
        "sheet.calc_card",
    ]
    # Each pick names exactly one given — the fan-out that makes any single
    # value independently re-pointable at another source.
    keys = [n["inputs"]["key"] for n in doc["nodes"] if n["type"] == "sources.pick"]
    assert keys == ["F_c90d", "a_1", "l", "l_1", "b", "k_c90", "k_mod", "f_c90k", "gamma_M"]


# The traced graph mints sequential ids (`pick`, `pick_2`, …); the *served*
# graph is the AST parse, whose ids are the authored variable names (ADR 0004
# D3/D4) — asserted separately, further down.
PICK_IDS = ["pick"] + [f"pick_{n}" for n in range(2, 10)]
GIVENS = ["F_c90d", "a_1", "l", "l_1", "b", "k_c90", "k_mod", "f_c90k", "gamma_M"]


def test_every_given_is_wired_into_the_cards_derived_sockets():
    """The nine symbols are input sockets only because the formulas read them."""
    from beam_bearing_pressure import build_graph

    edges = _edge_set(build_graph())
    for node_id, symbol in zip(PICK_IDS, GIVENS):
        assert ("read_json", "result", node_id, "data") in edges
        assert (node_id, "result", "calc_card", symbol) in edges
    assert len(edges) == 18  # nine reads in, nine values out — nothing else


def test_the_card_is_the_graph_output():
    from beam_bearing_pressure import build_graph

    assert build_graph().output == {"node": "calc_card", "socket": "result"}


def test_the_calc_literal_carries_the_code_references_units_and_precision():
    from beam_bearing_pressure import build_graph

    card = next(
        n for n in build_graph().to_dict()["nodes"] if n["type"] == "sheet.calc_card"
    )
    assert card["inputs"]["formulas"] == (
        "l_l = MinDefined(30, a_1) [mm]  # EN 1995-1-1 6.1.5 (1)\n"
        "l_r = MinDefined(30, l, l_1/2) [mm]  # EN 1995-1-1 6.1.5 (1)\n"
        "l_ef = l_l + l + l_r [mm]  # EN 1995-1-1 6.1.5 (1)\n"
        "A_ef = l_ef * b [mm²]  # EN 1995-1-1 6.1.5 (1)\n"
        "sigma_c90d = F_c90d * 1000 / A_ef [N/mm²]  # EN 1995-1-1 6.1.5 (1) (6.4)\n"
        "f_c90d = k_mod * f_c90k / gamma_M [N/mm²]  # EN 1995-1-1 2.4.1 (1)P (2.14)\n"
        "eta = sigma_c90d / (k_c90 * f_c90d) * 100 [%]  # EN 1995-1-1 6.1.5 (1)P (6.3)"
    )
    assert card["inputs"]["checks"] == (
        "eta < 100 [eta]  # reinforcement of the support not required"
    )
    # At the default of 3 the card would read `A_ef = 2.42e+04` and `eta = 146`.
    assert card["inputs"]["precision"] == 5
    # `as_of` is authored, never taken from the clock.
    assert card["inputs"]["as_of"] == "2025-07-02"


def test_the_effective_length_is_l_ef_not_a_redefined_l():
    """The source sheet reuses `l`; calcsheet refuses a redefinition (D-choice 1)."""
    from beam_bearing_pressure import build_graph

    card = next(
        n for n in build_graph().to_dict()["nodes"] if n["type"] == "sheet.calc_card"
    )
    formulas = card["inputs"]["formulas"]
    assert "l_ef = " in formulas
    assert "\nl = " not in formulas and not formulas.startswith("l = ")


def test_the_empty_given_is_authored_as_json_null():
    from beam_bearing_pressure import INPUTS_JSON

    data = json.loads(INPUTS_JSON.read_text(encoding="utf-8"))
    assert data["l_1"]["value"] is None
    # …and it still owns a unit and a code reference, like every other given.
    assert data["l_1"]["unit"] == "mm"
    assert data["l_1"]["ref"] == "EN 1995-1-1 6.1.5 (1)"
    assert set(data) == {
        "F_c90d", "a_1", "l", "l_1", "b", "k_c90", "k_mod", "f_c90k", "gamma_M",
    }


# -- the numbers, one at a time -----------------------------------------------


@needs_sym_extra
def test_graph_loads_binds_and_runs_end_to_end():
    from beam_bearing_pressure import build_graph

    graph = build_graph()
    validate_graph(graph.to_dict())
    result = run(graph)

    # Each pick hands on the whole record — number plus provenance — and the
    # empty given's `value` is `None`, which is what makes `l_1` empty downstream.
    picked = {symbol: result.value(nid) for nid, symbol in zip(PICK_IDS, GIVENS)}
    assert {symbol: entry["value"] for symbol, entry in picked.items()} == {
        "F_c90d": 107.0,
        "a_1": 0,
        "l": 80,
        "l_1": None,
        "b": 220,
        "k_c90": 1.75,
        "k_mod": 0.9,
        "f_c90k": 2.5,
        "gamma_M": 1.3,
    }
    assert picked["F_c90d"] == {
        "value": 107.0,
        "unit": "kN",
        "ref": "EN 1995-1-1 6.1.5 (1)",
    }


@needs_sym_extra
def test_every_computed_value_individually():
    values = _result().values

    assert values["l_l"] == 0.0  # min(30, a_1) with a_1 = 0
    assert values["l_r"] == 30.0  # min(30, l, l_1/2) with l_1 empty -> min(30, 80)
    assert values["l_ef"] == 110.0
    assert values["A_ef"] == 24200.0
    assert values["sigma_c90d"] == SIGMA_C90D
    assert values["f_c90d"] == F_C90D
    assert values["eta"] == ETA


@needs_sym_extra
def test_the_rows_render_at_five_significant_digits():
    rows = _rows(_result())

    assert [(s, rows[s].value_text, rows[s].unit) for s in
            ("l_l", "l_r", "l_ef", "A_ef", "sigma_c90d", "f_c90d", "eta")] == [
        ("l_l", "0", "mm"),
        ("l_r", "30", "mm"),
        ("l_ef", "110", "mm"),
        ("A_ef", "24200", "mm²"),
        ("sigma_c90d", "4.4215", "N/mm²"),
        ("f_c90d", "1.7308", "N/mm²"),
        ("eta", "145.98", "%"),
    ]


@needs_sym_extra
def test_all_nine_givens_carry_their_unit_and_reference_from_inputs_json():
    """The provenance in the JSON reaches the card's given rows, unaltered."""
    from beam_bearing_pressure import INPUTS_JSON

    source = json.loads(INPUTS_JSON.read_text(encoding="utf-8"))
    rows = _result().inputs

    assert [row.symbol for row in rows] == [
        "a_1", "l", "l_1", "b", "F_c90d", "k_mod", "f_c90k", "gamma_M", "k_c90",
    ]
    # Every row's unit and reference are exactly the JSON's, for all nine.
    assert {row.symbol: (row.unit, row.ref) for row in rows} == {
        symbol: (entry["unit"], entry["ref"]) for symbol, entry in source.items()
    }
    # Spot-check the two the source sheet is most specific about.
    given = {row.symbol: row for row in rows}
    assert (given["F_c90d"].value_text, given["F_c90d"].unit) == ("107", "kN")
    assert (given["l_1"].value_text, given["l_1"].unit) == ("–", "mm")
    assert given["f_c90k"].unit == "N/mm²"
    assert given["gamma_M"].ref == "DIN EN 1995-1-1/NA NDP 2.4.1(1)P"


@needs_sym_extra
def test_the_empty_given_shows_a_dash_while_its_rule_stays_whole():
    """`l_r = min(30, l, l_1/2) = 30` — the rule in full, the value for this case."""
    rows = _rows(_result())

    assert rows["l_1"].value is None and rows["l_1"].value_text == "–"
    # The row states every argument, including the one that dropped out…
    assert rows["l_r"].definition == "MinDefined(30, l, l_1/2)"
    assert "<mo>min</mo>" in rows["l_r"].definition_mathml
    # …and the value is the resolved minimum.
    assert rows["l_r"].value == 30.0


@needs_sym_extra
def test_the_check_fails_and_reports_its_utilisation():
    result = _result()

    (check,) = result.checks
    assert check.expr == "eta < 100"
    assert check.description == "reinforcement of the support not required"
    assert check.passed is False
    assert check.substituted == "145.98 < 100 = False"
    # The trailing `[eta]` in the checks literal is what fills the chip.
    assert check.utilisation == ETA and check.limit == 100.0
    assert result.passed is False
    assert result.governing == ("eta < 100", ETA)


@needs_sym_extra
def test_output_html_carries_the_values_the_verdict_and_the_references():
    from beam_bearing_pressure import build_graph

    graph = build_graph()
    html = run(graph).value(graph.output["node"], graph.output["socket"])

    assert isinstance(html, str) and html.startswith("<!doctype html>")
    assert "Support pressure without reinforcement" in html
    assert '110&nbsp;<span class="unit">mm</span>' in html
    assert '24200&nbsp;<span class="unit">mm²</span>' in html
    assert '4.4215&nbsp;<span class="unit">N/mm²</span>' in html
    assert '145.98&nbsp;<span class="unit">%</span>' in html
    # The given rows carry their unit and reference from inputs.json.
    assert '107&nbsp;<span class="unit">kN</span>' in html
    assert '<span class="ref">DIN EN 1995-1-1/NA NCI 6.1.5 (NA.5)</span>' in html
    # The empty given renders as a dash — still with its unit — never as "None".
    assert '–&nbsp;<span class="unit">mm</span>' in html
    assert "None" not in html
    # Authored code references land in the right-hand gutter.
    assert '<span class="ref">EN 1995-1-1 6.1.5 (1)P (6.3)</span>' in html
    assert '<span class="ref">EN 1995-1-1 2.4.1 (1)P (2.14)</span>' in html
    # FAIL, with the governing chip.
    assert "145.98 &lt; 100 = False" in html and 'badge--fail">FAIL' in html
    assert "145.98 ≤ 100" in html
    assert 'class="status status--fail"' in html and "Overall <b>FAIL</b>" in html
    # Math is native MathML — no script, no CDN, no external reference.
    assert "<math" in html and "</math>" in html
    assert "http" not in html
    assert "<script" not in html and "<link" not in html and "@import" not in html


@needs_sym_extra
def test_a_failing_check_does_not_fail_the_run():
    """ADR 0016: the verdict is card content; `run` raises nothing (D-choice 3)."""
    from beam_bearing_pressure import build_graph

    result = run(build_graph())
    assert set(result.outputs) == {"read_json", *PICK_IDS, "calc_card"}
    assert "Overall <b>FAIL</b>" in result.value("calc_card", "result")


@needs_sym_extra
def test_graph_declares_environment_dependencies():
    from beam_bearing_pressure import DEPENDENCIES, build_graph

    graph = build_graph()
    assert graph.environment is not None
    assert graph.environment["network"] == "none"
    assert graph.environment["dependencies"] == DEPENDENCIES


@needs_sym_extra
def test_graph_exports_python():
    from beam_bearing_pressure import build_graph

    script = to_python(build_graph())
    namespace: dict = {}
    exec(compile(script, "<exported>", "exec"), namespace)  # noqa: S102 - trusted, generated
    graph = build_graph()
    assert namespace["_calc_card"] == run(graph).value(
        graph.output["node"], graph.output["socket"]
    )


# -- served + the bijection ---------------------------------------------------


def test_the_entry_is_discoverable_by_the_picker():
    """ADR 0009: a bundled `<name>/<name>.py` is a viewable entry, no registration."""
    from server.entries import EntryCatalog

    entries = {e["id"]: e for e in EntryCatalog().discover().entries()}
    assert entries[ENTRY]["status"] == "ok", entries[ENTRY].get("error")
    assert entries[ENTRY]["title"] == "Beam bearing pressure"


def test_served_node_ids_are_the_authored_variable_names():
    """Node id = the `@main` variable name (ADR 0004 D3)."""
    from server.demo import load_graph, make_workspace

    graph = load_graph(ENTRY, make_workspace(ENTRY))
    assert [n["id"] for n in graph["nodes"]] == [
        "inputs", "F_c90d", "a_1", "l", "l_1", "b", "k_c90", "k_mod",
        "f_c90k", "gamma_M", "card",
    ]
    assert graph["output"] == {"node": "card", "socket": "result"}
    # Served pristine: the relative filename, no absolute machine path.
    assert graph["nodes"][0]["inputs"]["path"] == "inputs.json"


def test_the_module_is_a_byte_exact_fixed_point_of_the_bijection():
    """Parsing and saving it unedited rewrites nothing (ADR 0004 D5 / 0020)."""
    import beam_bearing_pressure  # noqa: F401 - registers the node types

    text = _module_text()
    graph = from_composite(text, DEFAULT_REGISTRY, module_name=ENTRY)
    written = compute_writeback(text, graph, DEFAULT_REGISTRY, ENTRY)
    assert written.strategy == "unchanged"
    assert written.text == text


def test_the_card_statement_is_already_in_the_emitters_canonical_form():
    """The block-form calc literals are exactly what a UI save would write."""
    import ast

    import beam_bearing_pressure  # noqa: F401 - registers the node types
    from engine.composite import composite_call_names, wiring_lines

    text = _module_text()
    graph = from_composite(text, DEFAULT_REGISTRY, module_name=ENTRY)
    call_names = composite_call_names(ast.parse(text), ENTRY)

    emitted = wiring_lines(graph, DEFAULT_REGISTRY, call_names=call_names)
    card = next(line for line in emitted if line.lstrip().startswith("card = "))
    assert card in text
    # …and so is every `pick` statement.
    for line in emitted:
        if "pick(" in line:
            assert line in text


def test_an_edit_and_its_revert_restore_the_file_byte_for_byte():
    import beam_bearing_pressure  # noqa: F401 - registers the node types

    text = _module_text()

    edited = from_composite(text, DEFAULT_REGISTRY, module_name=ENTRY)
    next(n for n in edited.nodes if n.id == "card").inputs["precision"] = 4
    patched = compute_writeback(text, edited, DEFAULT_REGISTRY, ENTRY)
    assert patched.strategy == "patched" and patched.changed_ids == ["card"]
    assert "precision=4," in patched.text

    reverted = from_composite(patched.text, DEFAULT_REGISTRY, module_name=ENTRY)
    next(n for n in reverted.nodes if n.id == "card").inputs["precision"] = 5
    assert compute_writeback(patched.text, reverted, DEFAULT_REGISTRY, ENTRY).text == text
