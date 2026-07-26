"""Empty givens and ``MinDefined`` — the "not applicable" case, end to end.

An engineering sheet prints ``l_1 = –`` for a quantity that does not exist for
the member at hand, and still states the whole rule over it
(``l_r = min(30, l, l_1/2)``). What this file pins:

* an argument that depends on an empty given is dropped — as a bare argument
  **and** inside a sub-expression (``l_1/2``), which is the case real sheets
  need;
* dropping *every* argument raises, and so does using an empty given anywhere
  outside ``MinDefined`` — each error naming the symbol and the formula;
* the row shows the **original** rule while its value comes from the
  **resolved** one;
* an empty given renders ``–`` and round-trips ``to_dict``/``from_dict`` as
  JSON ``null``.
"""

from __future__ import annotations

import json

import pytest

from calcsheet import Calc, CalcError, Check, Formula, Input, MinDefined, render_html
from calcsheet.evaluate import EMPTY_VALUE_TEXT
from calcsheet.mathml import expression_mathml, parse_expression, resolve_min_defined


def _calc(**overrides) -> Calc:
    """The bearing-length fragment of the real sheet: ``l_1`` is empty."""
    base = dict(
        title="bearing",
        as_of="2025-07-02",
        inputs={
            "a_1": Input(0.0, unit="mm"),
            "l": Input(80.0, unit="mm"),
            "l_1": Input(None, unit="mm", ref="EN 1995-1-1 6.1.5 (1)"),
        },
        formulas=[
            Formula("l_l", "MinDefined(30, a_1)", unit="mm"),
            Formula("l_r", "MinDefined(30, l, l_1/2)", unit="mm"),
        ],
        checks=[],
    )
    base.update(overrides)
    return Calc(**base)


# -- the evaluation rule ------------------------------------------------------


def test_a_bare_empty_argument_is_dropped():
    """``MinDefined(30, l_1)`` with ``l_1`` empty is just ``30``."""
    result = _calc(
        formulas=[Formula("l_r", "MinDefined(30, l_1)", unit="mm")]
    ).evaluate()

    assert result.values["l_r"] == 30.0


def test_an_empty_inside_a_sub_expression_is_dropped():
    """``l_1/2`` counts: the whole argument goes, not just the bare symbol."""
    result = _calc().evaluate()

    # min(30, 80) — the third argument depended on the empty given.
    assert result.values["l_r"] == 30.0
    # And a defined argument still wins when it is smaller: min(30, 0) = 0.
    assert result.values["l_l"] == 0.0


def test_arguments_that_are_all_defined_behave_as_a_plain_minimum():
    """With nothing empty, ``MinDefined`` is exactly ``min`` over its arguments."""
    result = _calc(
        inputs={"a_1": Input(0.0), "l": Input(80.0), "l_1": Input(50.0)},
        formulas=[Formula("l_r", "MinDefined(30, l, l_1/2)")],
    ).evaluate()

    assert result.values["l_r"] == 25.0  # l_1/2 governs


def test_every_argument_empty_raises_naming_the_symbol_and_the_formula():
    calc = _calc(
        inputs={"l_1": Input(None), "l_2": Input(None)},
        formulas=[Formula("l_r", "MinDefined(l_1, l_2/2)")],
    )
    with pytest.raises(CalcError) as error:
        calc.evaluate()

    message = str(error.value)
    assert "formula 'l_r'" in message
    assert "'l_1'" in message and "'l_2'" in message


def test_an_empty_given_outside_min_defined_raises():
    calc = _calc(formulas=[Formula("l_ef", "l + l_1")])
    with pytest.raises(CalcError) as error:
        calc.evaluate()

    message = str(error.value)
    assert "formula 'l_ef'" in message
    assert "'l_1'" in message and "MinDefined" in message


def test_an_empty_given_outside_min_defined_raises_in_a_check_too():
    calc = _calc(checks=[Check("l_1 < 100", "second bearing length")])
    with pytest.raises(CalcError, match="check 'l_1 < 100'"):
        calc.evaluate()


def test_a_formula_may_still_use_a_result_that_came_from_a_min_defined():
    """Formulas are never empty — a resolved ``MinDefined`` is an ordinary number."""
    result = _calc(
        formulas=[
            Formula("l_l", "MinDefined(30, a_1)"),
            Formula("l_r", "MinDefined(30, l, l_1/2)"),
            Formula("l_ef", "l_l + l + l_r", unit="mm"),
        ]
    ).evaluate()

    assert result.values["l_ef"] == 110.0


def test_an_empty_utilisation_symbol_raises():
    calc = _calc(checks=[Check("l < 100", "", utilisation="l_1")])
    with pytest.raises(CalcError, match="empty given"):
        calc.evaluate()


# -- render: the original rule, the resolved value ----------------------------


def test_the_row_shows_the_original_rule_and_the_resolved_value():
    """The whole point: the card states the rule, the value reflects the case."""
    result = _calc().evaluate()
    row = next(row for row in result.formulas if row.symbol == "l_r")

    # The definition is the author's own text — every argument still there.
    assert row.definition == "MinDefined(30, l, l_1/2)"
    # …and so is the typeset form: `l_1` is visible in the markup.
    assert "<mo>min</mo>" in row.definition_mathml
    assert row.definition_mathml.count("<mo>&#x0002C;</mo>") == 2  # three arguments
    # The value is the resolved one.
    assert row.value == 30.0 and row.value_text == "30"


def test_the_latex_is_built_by_the_printer_not_patched_afterwards():
    """`MinDefined` prints through sympy, so its arguments print by sympy's rules."""
    expr = parse_expression("MinDefined(30, l, l_1/2)", ["l", "l_1"], what="probe")
    assert isinstance(expr, MinDefined)

    import sympy

    # `\min\left(…\right)`, with each argument in sympy's own LaTeX (the
    # fraction is a `\frac`, the subscript a `_{1}`) — not a re-spelling of the
    # source text.
    assert sympy.latex(expr) == r"\min\left(30, l, \frac{l_{1}}{2}\right)"
    assert "<mfrac>" in expression_mathml(expr)


def test_resolve_min_defined_leaves_the_original_expression_untouched():
    expr = parse_expression("MinDefined(30, l, l_1/2)", ["l", "l_1"], what="probe")
    resolved = resolve_min_defined(expr, {"l_1"}, what="probe")

    assert str(resolved) == "Min(30, l)"
    assert isinstance(expr, MinDefined)  # sympy objects are immutable — proven


def test_an_empty_given_renders_as_a_dash_keeping_its_unit_and_reference():
    result = _calc().evaluate()
    row = next(row for row in result.inputs if row.symbol == "l_1")

    assert row.value is None
    assert row.value_text == EMPTY_VALUE_TEXT == "–"
    assert row.unit == "mm"
    assert row.ref == "EN 1995-1-1 6.1.5 (1)"

    html = render_html(result)
    assert '<span class="val">–&nbsp;<span class="unit">mm</span></span>' in html
    assert '<span class="ref">EN 1995-1-1 6.1.5 (1)</span>' in html
    assert "None" not in html


# -- serialization ------------------------------------------------------------


def test_an_empty_value_round_trips_as_json_null():
    from calcsheet import Result

    result = _calc().evaluate()
    payload = result.to_dict()

    empty_row = next(row for row in payload["inputs"] if row["symbol"] == "l_1")
    assert empty_row["value"] is None
    assert empty_row["value_text"] == "–"
    assert payload["values"]["l_1"] is None
    # Really JSON `null`, and really lossless back.
    assert json.loads(json.dumps(payload))["values"]["l_1"] is None
    assert Result.from_dict(json.loads(json.dumps(payload))) == result
