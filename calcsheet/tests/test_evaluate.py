"""Evaluation: ordering, scope threading, formatting, verdicts, errors."""

from __future__ import annotations

import pytest

from calcsheet import Calc, CalcError, Check, Formula, Input
from calcsheet.evaluate import format_value
from calcsheet.examples.capacity import build_calc


def test_formulas_run_in_declaration_order_over_one_scope():
    result = Calc(
        title="chain",
        as_of="2026-07-24",
        inputs={"a": Input(2)},
        formulas=[Formula("b", "a + 1"), Formula("c", "b * 10")],
        checks=[],
    ).evaluate()

    assert [row.symbol for row in result.formulas] == ["b", "c"]
    assert result.values == {"a": 2, "b": 3.0, "c": 30.0}


def test_formula_may_not_reference_a_later_formula():
    calc = Calc(
        title="forward",
        as_of="2026-07-24",
        inputs={},
        formulas=[Formula("a", "b"), Formula("b", "1")],
        checks=[],
    )
    with pytest.raises(CalcError, match="unknown symbol"):
        calc.evaluate()


def test_example_values_and_precision():
    result = build_calc().evaluate()

    assert [(row.symbol, row.value_text) for row in result.inputs] == [
        ("F_max", "120"),
        ("C_min", "210"),
    ]
    assert [(row.symbol, row.value_text, row.unit) for row in result.formulas] == [
        ("r", "0.571", ""),
        ("U", "57.1", "%"),
    ]


def test_format_value_uses_significant_digits():
    assert format_value(120, 3) == "120"
    assert format_value(120.0, 3) == "120"
    assert format_value(120 / 210, 3) == "0.571"
    assert format_value(100 * 120 / 210, 3) == "57.1"
    assert format_value(100 * 120 / 210, 5) == "57.143"


def test_example_fails_because_of_the_second_check():
    result = build_calc().evaluate()

    assert [check.passed for check in result.checks] == [True, False]
    assert [check.substituted for check in result.checks] == [
        "57.1 < 100 = True",
        "57.1 < 50 = False",
    ]
    assert result.passed is False


def test_all_checks_passing_makes_the_calc_pass():
    result = Calc(
        title="ok",
        as_of="2026-07-24",
        inputs={"a": Input(1)},
        formulas=[],
        checks=[Check("a > 0", "positive"), Check("a < 10")],
    ).evaluate()

    assert result.passed is True


def test_a_calc_without_checks_passes_vacuously():
    result = Calc(title="bare", as_of="2026-07-24", inputs={"a": Input(1)}).evaluate()
    assert result.passed is True


def test_unknown_symbol_names_the_symbol_and_the_available_names():
    calc = Calc(
        title="typo",
        as_of="2026-07-24",
        inputs={"F_max": Input(120)},
        formulas=[Formula("r", "F_maxx / 2")],
        checks=[],
    )
    with pytest.raises(CalcError) as error:
        calc.evaluate()

    message = str(error.value)
    assert "'F_maxx'" in message
    assert "F_max" in message


def test_a_formula_may_not_redefine_an_input():
    calc = Calc(
        title="dup",
        as_of="2026-07-24",
        inputs={"a": Input(1)},
        formulas=[Formula("a", "2")],
        checks=[],
    )
    with pytest.raises(CalcError, match="redefines an existing symbol"):
        calc.evaluate()


def test_two_formulas_may_not_share_a_symbol():
    calc = Calc(
        title="dup",
        as_of="2026-07-24",
        inputs={},
        formulas=[Formula("r", "1"), Formula("r", "2")],
        checks=[],
    )
    with pytest.raises(CalcError, match="redefines an existing symbol"):
        calc.evaluate()


def test_unparseable_expression_names_the_expression():
    calc = Calc(
        title="broken",
        as_of="2026-07-24",
        inputs={},
        formulas=[Formula("r", "1 +* 2")],
        checks=[],
    )
    with pytest.raises(CalcError, match="cannot parse expression"):
        calc.evaluate()


def test_a_check_must_be_boolean():
    calc = Calc(
        title="not a verdict",
        as_of="2026-07-24",
        inputs={"U": Input(57.1)},
        formulas=[],
        checks=[Check("U + 1")],
    )
    with pytest.raises(CalcError, match="is not a boolean"):
        calc.evaluate()


def test_a_check_may_not_reference_an_unknown_symbol():
    calc = Calc(
        title="check typo",
        as_of="2026-07-24",
        inputs={"U": Input(57.1)},
        formulas=[],
        checks=[Check("V < 100")],
    )
    with pytest.raises(CalcError, match="unknown symbol"):
        calc.evaluate()


def test_declared_names_shadow_sympy_constants():
    # Without a symbol table, sympy would read `E` as Euler's number and the
    # calc would compute something the author never wrote.
    result = Calc(
        title="shadowing",
        as_of="2026-07-24",
        inputs={"E": Input(4.0)},
        formulas=[Formula("d", "E * 2")],
        checks=[],
    ).evaluate()

    assert result.values["d"] == 8.0


def test_evaluation_is_repeatable():
    first, second = build_calc().evaluate(), build_calc().evaluate()
    assert first == second
