"""Utilisation: a margin an engineer can read, layered over the binary verdict."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from calcsheet import Calc, CalcError, Check, Formula, Input, Result, render_html
from calcsheet.examples.capacity import build_calc

GOLDEN = Path(__file__).parent / "golden" / "capacity-check.html"


def _connection(*checks: Check) -> Result:
    """A utilisation calc shaped like a real design check (eta = demand/capacity)."""
    return Calc(
        title="Screw connection conn-01",
        as_of="2026-07-24",
        inputs={
            "F_vEd": Input(1050.0, ref="fem.csv · V_z", unit="N"),
            "F_vRd": Input(1383.0, ref="EC5 Eq (2.17)", unit="N"),
        },
        formulas=[Formula("eta", "F_vEd / F_vRd", ref="utilisation")],
        checks=checks,
    ).evaluate()


def test_a_check_without_a_utilisation_is_exactly_what_it_always_was():
    result = build_calc().evaluate()

    assert [check.utilisation for check in result.checks] == [None, None]
    assert [check.limit for check in result.checks] == [None, None]
    assert result.governing is None
    assert result.passed is False


def test_the_shipped_example_renders_the_pinned_card():
    # The whole feature is opt-in: unused, it costs zero bytes of output. The
    # golden it is checked against is the one pinned in test_options.py.
    assert render_html(build_calc().evaluate()) == GOLDEN.read_text(encoding="utf-8")


def test_a_declared_utilisation_resolves_to_its_symbol_and_limit():
    result = _connection(Check("eta <= 0.833", "target", utilisation="eta"))
    (check,) = result.checks

    assert check.utilisation == pytest.approx(0.759219, rel=1e-5)
    assert check.limit == 0.833
    assert check.passed is True


def test_the_binary_verdict_stays_authoritative():
    # Utilisation is reported for a failing check too; it does not soften it.
    result = _connection(Check("eta <= 0.5", "unreachable target", utilisation="eta"))
    (check,) = result.checks

    assert check.utilisation == pytest.approx(0.759219, rel=1e-5)
    assert check.passed is False
    assert result.passed is False


def test_a_reversed_inequality_still_finds_the_limit():
    result = _connection(Check("1.0 >= eta", "resistance", utilisation="eta"))
    (check,) = result.checks

    assert check.limit == 1.0


def test_a_check_that_is_not_a_bound_reports_the_utilisation_alone():
    # "geometry checks are naturally boolean" — there is no comparable ceiling.
    result = _connection(Check("Eq(eta, eta)", "identity", utilisation="eta"))
    (check,) = result.checks

    assert check.utilisation == pytest.approx(0.759219, rel=1e-5)
    assert check.limit is None


def test_a_limit_is_only_claimed_when_the_symbol_itself_is_bounded():
    result = _connection(Check("2 * eta <= 2.0", "scaled", utilisation="eta"))
    (check,) = result.checks

    assert check.utilisation == pytest.approx(0.759219, rel=1e-5)
    assert check.limit is None


def test_an_undefined_utilisation_symbol_is_named_and_refused():
    with pytest.raises(CalcError, match="utilisation symbol 'zeta' is not defined"):
        _connection(Check("eta <= 1.0", "typo", utilisation="zeta"))


def test_governing_is_the_worst_utilisation_and_the_check_it_came_from():
    result = _connection(
        Check("eta <= 1.0", "resistance", utilisation="eta"),
        Check("F_vRd > 0", "capacity is positive"),
    )

    assert result.governing == ("eta <= 1.0", result.checks[0].utilisation)


def test_governing_ignores_checks_that_report_no_utilisation():
    result = _connection(Check("F_vRd > 0", "capacity is positive"))

    assert result.governing is None


def test_the_tighter_limit_governs_when_utilisations_tie():
    # Same eta, two ceilings: the 0.833 target is what actually binds.
    result = _connection(
        Check("eta <= 1.0", "resistance", utilisation="eta"),
        Check("eta <= 0.833", "target", utilisation="eta"),
    )

    assert result.governing[0] == "eta <= 0.833"


def test_governing_picks_the_highest_utilisation_across_symbols():
    result = Calc(
        title="two utilisations",
        as_of="2026-07-24",
        inputs={"a": Input(4.0), "b": Input(9.0)},
        formulas=[Formula("u1", "a / 10"), Formula("u2", "b / 10")],
        checks=[
            Check("u1 <= 1.0", "first", utilisation="u1"),
            Check("u2 <= 1.0", "second", utilisation="u2"),
        ],
    ).evaluate()

    assert result.governing == ("u2 <= 1.0", 0.9)


def test_the_card_states_the_measured_value_and_its_limit_as_facts():
    # NOT `0.759 ≤ 0.833`, and NOT the check substituted and evaluated. Both
    # were inequalities printed as though they were statements, and on a
    # failing check the first one is simply untrue. Two named facts instead.
    markup = render_html(_connection(Check("eta <= 0.833", "target", utilisation="eta")))

    assert '<span class="chk__tag">actual</span> 0.759' in markup
    assert '<span class="chk__tag">limit</span> 0.833' in markup
    assert "≤" not in markup
    assert "= True" not in markup


def test_a_failing_check_states_the_value_that_failed_and_asserts_nothing_else():
    markup = render_html(_connection(Check("eta <= 0.5", "unreachable", utilisation="eta")))

    assert '<span class="chk__tag">actual</span> 0.759' in markup
    assert '<span class="chk__tag">limit</span> 0.5' in markup
    assert 'badge badge--fail">FAIL &#10007;' in markup
    # the two false statements the old chip printed about this very check
    assert "0.759 ≤ 0.5" not in markup
    assert "= False" not in markup


def test_a_check_with_a_unit_carries_it_onto_the_chip():
    # The same unit the defining row shows, from the same field — a chip that
    # said `145.98` where the row says `145.98 %` would be a second, lossier
    # rendering of one number.
    result = Calc(
        title="utilisation in percent",
        as_of="2026-07-24",
        inputs={"a": Input(4.0)},
        formulas=[Formula("u", "a * 10", unit="%")],
        checks=[Check("u < 100", "target", utilisation="u")],
    ).evaluate()
    (check,) = result.checks
    markup = render_html(result)

    assert check.utilisation_unit == "%"
    assert '<span class="chk__tag">actual</span> 40&nbsp;<span class="unit">%</span>' in markup
    assert '<span class="chk__tag">limit</span> 100&nbsp;<span class="unit">%</span>' in markup


def test_a_value_without_a_limit_stands_alone():
    # "geometry checks are naturally boolean": there is a value but no
    # comparable ceiling, so the chip shows the value and stops.
    markup = render_html(_connection(Check("Eq(eta, eta)", "identity", utilisation="eta")))

    assert '<span class="chk__tag">actual</span> 0.759' in markup
    # the cell, not the rule that would style it — the two quantity cells share
    # one CSS block, emitted whenever any check reports a value at all.
    assert '<span class="chk__limit">' not in markup


def test_a_check_with_no_utilisation_is_rule_and_verdict_alone():
    # The empty state must not look broken: no quantity cells at all, and the
    # chip is still a rule, a description and a badge.
    markup = render_html(_connection(Check("F_vRd > 0", "capacity is positive")))

    assert "chk__actual" not in markup
    assert "chk__limit" not in markup
    assert '<span class="chk__what">capacity is positive</span>' in markup
    assert 'badge badge--pass">PASS &#10003;' in markup


def test_the_card_names_the_governing_check_in_the_footer():
    markup = render_html(
        _connection(
            Check("eta <= 1.0", "resistance", utilisation="eta"),
            Check("eta <= 0.833", "target", utilisation="eta"),
        )
    )

    assert "Governing check <b>eta &lt;= 0.833</b> at <b>0.759</b>." in markup


def test_utilisation_css_is_emitted_only_when_a_check_reports_one():
    without = render_html(_connection(Check("eta <= 1.0", "resistance")))
    with_util = render_html(_connection(Check("eta <= 1.0", "r", utilisation="eta")))

    assert "chk__actual" not in without
    assert ".chk__actual{" in with_util


def test_a_utilisation_card_stays_self_contained_and_deterministic():
    result = _connection(Check("eta <= 0.833", "target", utilisation="eta"))

    assert render_html(result) == render_html(result)
    lowered = render_html(result).lower()
    for forbidden in ("<script", "http", "onerror", "onload", "src=", "<link"):
        assert forbidden not in lowered


def test_the_margin_survives_the_archival_round_trip():
    result = _connection(
        Check("eta <= 1.0", "resistance", utilisation="eta"),
        Check("eta <= 0.833", "target", utilisation="eta"),
    )

    restored = Result.from_dict(json.loads(json.dumps(result.to_dict())))

    assert restored == result
    assert restored.governing == result.governing
    assert restored.checks[0].limit == 1.0
