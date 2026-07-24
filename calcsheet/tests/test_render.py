"""Rendering: the four-slot card, its guarantees, and determinism."""

from __future__ import annotations

import pytest

from calcsheet import Calc, CalcError, Check, Formula, Input, Result, Row, render_html
from calcsheet.mathml import assert_plain_mathml
from calcsheet.examples.capacity import build_calc


@pytest.fixture(scope="module")
def html() -> str:
    return render_html(build_calc().evaluate())


def test_header_carries_title_as_of_and_the_overall_status(html: str):
    assert "Capacity check" in html
    assert "AS_OF 2026-07-24" in html
    # the pill itself, not the stylesheet rule that defines both variants
    assert '<span class="status status--fail">&#9679; FAIL</span>' in html
    assert '<span class="status status--pass"' not in html


def test_rows_render_symbols_and_definitions_as_mathml(html: str):
    assert "<math" in html
    # F_max renders as F with a "max" subscript, and r = F_max / C_min as a
    # fraction — both straight from sympy's LaTeX.
    assert "<msub><mi>F</mi>" in html
    assert "<mfrac>" in html


def test_input_rows_have_no_definition_slot():
    result = Calc(
        title="inputs only", as_of="2026-07-24", inputs={"a": Input(1, ref="src")}
    ).evaluate()
    markup = render_html(result)

    assert '<span class="def"></span>' in markup


def test_values_carry_their_unit_and_reference(html: str):
    assert '57.1&nbsp;<span class="unit">%</span>' in html
    assert '<span class="ref">forces.csv · max</span>' in html


def test_checks_render_description_substituted_boolean_and_badges(html: str):
    assert "capacity not exceeded" in html
    assert "utilisation target" in html
    assert "57.1 &lt; 100 = True" in html
    assert "57.1 &lt; 50 = False" in html
    assert '<span class="badge badge--pass">PASS</span>' in html
    assert '<span class="badge badge--fail">FAIL</span>' in html


def test_footer_states_the_overall_verdict(html: str):
    assert "Overall <b>FAIL</b>" in html
    assert "every</b> check passes" in html


def test_the_card_is_self_contained(html: str):
    lowered = html.lower()
    for forbidden in ("<script", "http", "onerror", "onload", "src=", "<link"):
        assert forbidden not in lowered


def test_rendering_is_byte_identical_across_builds():
    first = render_html(build_calc().evaluate())
    second = render_html(build_calc().evaluate())
    assert first == second


def test_caller_text_is_escaped():
    result = Calc(
        title="<b>Title</b>",
        as_of="2026-07-24",
        inputs={"a": Input(1, ref="<i>ref</i>", unit="<u>")},
        checks=[Check("a > 0", "<em>why</em>")],
    ).evaluate()
    markup = render_html(result)

    assert "&lt;b&gt;Title&lt;/b&gt;" in markup
    assert "&lt;i&gt;ref&lt;/i&gt;" in markup
    assert "&lt;em&gt;why&lt;/em&gt;" in markup
    assert "<b>Title</b>" not in markup


@pytest.mark.parametrize(
    "markup",
    [
        '<math><mi>x</mi></math><script>alert(1)</script>',
        '<math xmlns="http://www.w3.org/1998/Math/MathML"><mi>x</mi></math>',
        '<img src="x" onerror="alert(1)">',
        '<a href="/nope">x</a>',
    ],
)
def test_the_markup_guard_refuses_non_mathml(markup: str):
    with pytest.raises(CalcError, match="plain MathML"):
        assert_plain_mathml(markup)


def test_the_guard_runs_at_render_time():
    # A hand-built Result must not be able to smuggle markup into the card.
    smuggled = Result(
        title="smuggle",
        as_of="2026-07-24",
        precision=3,
        inputs=(
            Row(
                symbol="a",
                symbol_mathml="<script>alert(1)</script>",
                definition="",
                definition_mathml="",
                value=1,
                value_text="1",
                unit="",
                ref="",
            ),
        ),
        formulas=(),
        checks=(),
    )
    with pytest.raises(CalcError, match="plain MathML"):
        render_html(smuggled)


def test_sections_are_omitted_when_empty():
    markup = render_html(
        Calc(title="empty", as_of="2026-07-24", inputs={"a": Input(1)}).evaluate()
    )
    assert "Inputs" in markup
    assert "Calculation" not in markup
    assert "Design checks" not in markup


def test_formula_rows_get_a_second_equals_sign():
    result = Calc(
        title="two equals",
        as_of="2026-07-24",
        inputs={"a": Input(2)},
        formulas=[Formula("b", "a * 3")],
    ).evaluate()
    row = render_html(result).split('<div class="rows">')[2]

    assert row.count('<span class="eq">=</span>') == 2
