"""Tests for ``sheet.group_card`` — one authored calculation, run for N groups.

The node is where a *population* of groups meets a calculation written **once,
for one group**. What is worth pinning is therefore the expansion rule and what
it puts on the card, not the arithmetic (which is ``sheet.calc``'s, tested
elsewhere and shared here by construction):

* the varying given is discovered from the wire, and exactly one is allowed;
* which formulas are copied per group and which are computed once — the
  "all groups share one geometry" property, as a consequence of the arithmetic
  rather than an assertion;
* symbol renaming preserves the author's expression text byte for byte;
* checks are copied per group, carrying the group's label;
* the card's rows: a count row and a governing-force row per group, the
  governing one citing the member end it came from;
* a mixed verdict — some groups PASS, some FAIL, on one card, run green;
* one group behaves exactly like the single-group card would.

Run with:  uv run --extra dev --extra sym python -m pytest -q
"""

from __future__ import annotations

import pytest

import sheet
from engine import UserError

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

# A miniature of the bearing check: two shared formulas, two that depend on the
# force, one check.
FORMULAS = (
    "A = w * h [mm²]  # geometry\n"
    "f_d = k * f_k [N/mm²]  # material\n"
    "sigma = F * 1000 / A [N/mm²]  # demand\n"
    "eta = sigma / f_d * 100 [%]  # utilisation"
)
CHECKS = "eta < 100 [eta]  # capacity not exceeded"


def group(key: str, label: str, count: int, value: float, ref: str) -> dict:
    return {
        "key": key,
        "label": label,
        "count": count,
        "governing": {"value": value, "unit": "kN", "ref": ref},
    }


def population(*groups: dict, strategy: str = "tiered", params: dict | None = None) -> dict:
    return {
        "strategy": strategy,
        "params": params if params is not None else {"thresholds": [100]},
        "unit": "kN",
        "count": sum(g["count"] for g in groups),
        "groups": list(groups),
    }


TWO = population(
    group("T1", "[100, ∞) kN", 3, 200.0, "RFEM 1/2 @ 0 m · LK1"),
    group("T2", "[0, 100) kN", 7, 40.0, "RFEM 3/4 @ 1.5 m · LK2"),
)

SHARED = {"w": 100.0, "h": 200.0, "k": 0.9, "f_k": 2.5}


def render(groups: dict = TWO, **overrides) -> str:
    values = {**SHARED, "F": groups, **overrides}
    return sheet.group_card(
        title="Miniature check",
        as_of="2026-01-01",
        formulas=FORMULAS,
        checks=CHECKS,
        precision=5,
        **values,
    )


def expand(groups: dict = TWO, formulas: str = FORMULAS, checks: str = CHECKS):
    return sheet._expand_for_groups(
        sheet.parse_formulas(formulas),
        sheet.parse_checks(checks),
        "F",
        list(groups["groups"]),
    )


# -- finding the varying given -------------------------------------------------


def test_the_varying_given_is_the_socket_fed_a_group_population():
    name, record = sheet._varying_socket({**SHARED, "F": TWO})
    assert name == "F" and record is TWO


def test_no_group_population_at_all_says_what_to_wire():
    with pytest.raises(UserError) as caught:
        render(groups={"value": 200.0, "unit": "kN"})
    assert "no input carries a group population" in str(caught.value)


def test_two_group_populations_are_refused():
    with pytest.raises(UserError) as caught:
        sheet._varying_socket({"F": TWO, "G": TWO})
    assert "exactly one given may vary per group" in str(caught.value)


def test_a_malformed_population_is_refused():
    with pytest.raises(UserError, match="must be a non-empty list"):
        sheet._validate_groups({"groups": []})
    with pytest.raises(UserError, match="has no 'label' key"):
        sheet._validate_groups({"groups": [{"key": "a", "count": 1, "governing": {}}]})
    with pytest.raises(UserError, match="not a valid symbol suffix"):
        sheet._validate_groups(
            {"groups": [{"key": "T 1", "label": "x", "count": 1, "governing": {}}]}
        )


# -- the expansion rule --------------------------------------------------------


def test_only_the_formulas_that_depend_on_the_group_are_copied():
    formulas, _, varying = expand()

    assert varying == ["F", "eta", "sigma"]
    assert [f.symbol for f in formulas] == [
        "A", "f_d",                    # shared: computed once
        "sigma_T1", "eta_T1",
        "sigma_T2", "eta_T2",
    ]


def test_the_shared_formulas_keep_their_authored_order_and_text():
    formulas, _, _ = expand()
    shared = {f.symbol: f for f in formulas}
    assert shared["A"].expr == "w * h" and shared["A"].unit == "mm²"
    assert shared["f_d"].expr == "k * f_k" and shared["f_d"].ref == "material"


def test_renaming_preserves_the_authors_expression_text_exactly():
    """The expression is what the card typesets; only identifiers may move."""
    formulas, _, _ = expand()
    by_symbol = {f.symbol: f for f in formulas}
    assert by_symbol["sigma_T1"].expr == "F_T1 * 1000 / A"
    assert by_symbol["eta_T2"].expr == "sigma_T2 / f_d * 100"
    # …including spacing and parentheses a rewrite could normalise away.
    one = population(group("T1", "everything", 1, 1.0, "ref"))
    quirky, _, _ = expand(one, formulas="q = ( F+1 )/2 [kN]  # keep my spacing")
    assert [f.expr for f in quirky] == ["( F_T1+1 )/2"]


def test_a_check_is_copied_per_group_and_carries_the_groups_label():
    _, checks, _ = expand()
    assert [(c.expr, c.utilisation, c.description) for c in checks] == [
        ("eta_T1 < 100", "eta_T1", "[100, ∞) kN — capacity not exceeded"),
        ("eta_T2 < 100", "eta_T2", "[0, 100) kN — capacity not exceeded"),
    ]


def test_a_check_that_mentions_no_varying_symbol_stays_a_single_row():
    _, checks, _ = expand(checks="A > 0 [A]  # the bearing has an area\neta < 100  # ok")
    assert [c.expr for c in checks] == ["A > 0", "eta_T1 < 100", "eta_T2 < 100"]


def test_a_symbol_the_expansion_would_collide_with_is_refused():
    with pytest.raises(UserError, match="already define"):
        expand(formulas="sigma = F * 2\nsigma_T1 = 5")


# -- what the card shows -------------------------------------------------------


@needs_sym_extra
def test_each_group_gets_a_count_row_and_a_governing_force_row():
    values = sheet._group_values({**SHARED, "F": TWO}, "F", TWO["groups"])
    formulas, checks, _ = expand()
    result = sheet._evaluate_parsed("t", "d", formulas, checks, 5, values)

    rows = [(r.symbol, r.value_text, r.unit, r.ref) for r in result.inputs]
    assert ("n_T1", "3", "ends", "[100, ∞) kN") in rows
    assert ("F_T1", "200", "kN", "RFEM 1/2 @ 0 m · LK1") in rows
    assert ("n_T2", "7", "ends", "[0, 100) kN") in rows
    assert ("F_T2", "40", "kN", "RFEM 3/4 @ 1.5 m · LK2") in rows


@needs_sym_extra
def test_the_group_rows_sit_where_the_varying_given_sat():
    """The grouped card reads like the single one with a row opened out."""
    values = sheet._group_values(
        {"w": 1.0, "F": TWO, "k": 2.0}, "F", TWO["groups"]
    )
    assert list(values) == ["w", "n_T1", "F_T1", "n_T2", "F_T2", "k"]


@needs_sym_extra
def test_the_shared_geometry_appears_once_and_the_per_group_work_per_group():
    values = sheet._group_values({**SHARED, "F": TWO}, "F", TWO["groups"])
    formulas, checks, _ = expand()
    result = sheet._evaluate_parsed("t", "d", formulas, checks, 5, values)

    computed = {r.symbol: r.value for r in result.formulas}
    assert list(computed) == ["A", "f_d", "sigma_T1", "eta_T1", "sigma_T2", "eta_T2"]
    assert computed["A"] == 20000.0 and computed["f_d"] == 2.25
    assert computed["sigma_T1"] == 10.0 and computed["eta_T1"] == pytest.approx(444.44, abs=0.01)
    assert computed["sigma_T2"] == 2.0 and computed["eta_T2"] == pytest.approx(88.888, abs=0.01)


@needs_sym_extra
def test_a_mixed_verdict_lands_on_one_card_and_the_run_stays_green():
    html = render()

    assert html.startswith("<!doctype html>")
    assert 'badge--fail">FAIL' in html and 'badge--pass">PASS' in html
    assert "444.44 &lt; 100 = False" in html and "88.889 &lt; 100 = True" in html
    # A calc is valid only when every check passes, so overall is FAIL.
    assert "Overall <b>FAIL</b>" in html


@needs_sym_extra
def test_the_fine_print_names_the_strategy_and_its_parameters():
    """A reviewer must be able to check the division, not only read it."""
    html = render()
    assert "Grouped by &#x27;tiered&#x27; (thresholds=[100]) — 10 member ends in 2 groups." in html


@needs_sym_extra
def test_a_parameterless_strategy_gets_a_footnote_without_an_empty_bracket():
    one = population(
        group("all", "all member ends", 4, 200.0, "RFEM 1/2 @ 0 m · LK1"),
        strategy="single",
        params={},
    )
    assert "Grouped by &#x27;single&#x27; — 4 member ends in 1 group." in render(one)


@needs_sym_extra
def test_the_card_is_self_contained_like_every_other_card_here():
    html = render()
    assert "http" not in html
    assert "<script" not in html and "<link" not in html and "@import" not in html


@needs_sym_extra
def test_one_group_produces_the_same_numbers_as_the_single_group_card():
    """No privileged path: N=1 is the same machinery, not a bypass."""
    one = population(
        group("all", "all member ends", 4, 200.0, "RFEM 1/2 @ 0 m · LK1"),
        strategy="single",
        params={},
    )
    grouped = sheet._evaluate_parsed(
        "t", "d", *expand(one)[:2], 5,
        sheet._group_values({**SHARED, "F": one}, "F", one["groups"]),
    )
    plain = sheet._evaluate(
        "t", "d", FORMULAS, CHECKS, 5,
        {**SHARED, "F": {"value": 200.0, "unit": "kN", "ref": "RFEM 1/2 @ 0 m · LK1"}},
    )
    assert grouped.values["eta_all"] == plain.values["eta"]
    assert grouped.values["A"] == plain.values["A"]
    assert grouped.passed == plain.passed


@needs_sym_extra
def test_the_declared_card_height_is_taller_than_the_single_group_card():
    """A group card always has more rows; the frame scrolls when it has many."""
    assert sheet.GROUP_CARD_HEIGHT > sheet.DEFAULT_CARD_HEIGHT
    renderer = sheet.group_card.spec["renderer"]
    assert renderer["config"]["height"] == sheet.GROUP_CARD_HEIGHT


def test_the_node_derives_the_same_sockets_as_the_single_group_card():
    """Same authoring surface: ADR 0007 derived symbols, unchanged."""
    assert [i["name"] for i in sheet.group_card.spec["inputs"]] == [
        "title", "as_of", "formulas", "checks", "precision",
    ]
    derived = sheet.formula_free_symbols(FORMULAS)
    assert [d["name"] for d in derived] == ["w", "h", "k", "f_k", "F"]
