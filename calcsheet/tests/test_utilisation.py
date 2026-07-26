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


def test_the_card_shows_the_margin_next_to_the_verdict():
    markup = render_html(_connection(Check("eta <= 0.833", "target", utilisation="eta")))

    assert '<span class="chk__util">0.759 ≤ 0.833</span>' in markup
    assert '<div class="chk chk--util">' in markup
    # the exact operator and numbers still sit alongside it
    assert "0.759 &lt;= 0.833 = True" in markup


def test_a_margin_without_a_limit_shows_the_utilisation_alone():
    markup = render_html(_connection(Check("Eq(eta, eta)", "identity", utilisation="eta")))

    assert '<span class="chk__util">0.759</span>' in markup


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

    assert "chk--util" not in without
    assert "chk--util{" in with_util


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
