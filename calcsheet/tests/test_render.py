"""Rendering: the four-slot card, its guarantees, and determinism."""

from __future__ import annotations

import re

import pytest

from calcsheet import Calc, CalcError, Check, Formula, Input, Result, Row, render_html
from calcsheet.mathml import assert_plain_mathml, expression_mathml, parse_expression
from calcsheet.examples.capacity import build_calc


@pytest.fixture(scope="module")
def html() -> str:
    return render_html(build_calc().evaluate())


def test_header_carries_title_as_of_and_the_overall_status(html: str):
    assert "Capacity check" in html
    assert "AS_OF 2026-07-24" in html
    # the pill itself, not the stylesheet rule that defines both variants.
    # The verdict is the WORD, seconded by a glyph that differs between the two
    # (&#10003; check / &#10007; cross) — so PASS and FAIL are still told apart
    # with the colour removed.
    assert '<span class="status status--fail">FAIL &#10007;</span>' in html
    assert '<span class="status status--pass"' not in html


def test_rows_render_symbols_and_definitions_as_mathml(html: str):
    assert "<math" in html
    # F_max renders as F with a "max" subscript, and r = F_max / C_min as a
    # fraction — both straight from sympy's LaTeX.
    assert "<msub><mi>F</mi>" in html
    assert "<mfrac>" in html


def test_equations_are_display_style_and_symbols_are_not(html: str):
    # WHY the attribute is what it is: MathML's inline style shrinks every
    # nested level to 0.71em, so `F_max / C_min` rendered its numerator and
    # denominator at 9.9px inside a 14px row. Display style typesets them at
    # the row's own size. It belongs to the EQUATION, not to this card's CSS —
    # a Result's MathML is handed to whatever renders it.
    for equation in ('<span class="def">', '<span class="chk__eq">'):
        for fragment in html.split(equation)[1:]:
            assert fragment.startswith('<math display="block">')
    # A symbol is not an equation: it stands in the row's running text, and its
    # subscript shrinks under either style, which is what a subscript is for.
    for fragment in html.split('<span class="sym">')[1:]:
        assert fragment.startswith('<math display="inline">')


def test_display_style_changes_the_style_and_nothing_else():
    # The whole cost of the fix, stated: `display=` moves ONE attribute. Same
    # elements, same order, same entities — so nothing downstream (the plain-
    # markup guard, the serializer, another renderer) sees a new shape.
    expr = parse_expression("F_max / C_min", ["F_max", "C_min"], what="expr")
    block = expression_mathml(expr, "block")
    inline = expression_mathml(expr, "inline")

    assert block.startswith('<math display="block">')
    assert inline.startswith('<math display="inline">')
    assert block.replace('display="block"', "") == inline.replace(
        'display="inline"', ""
    )
    assert_plain_mathml(block)


def test_an_equation_never_gets_a_scroller_or_a_height_of_its_own(html: str):
    # "Auto-expand, don't scroll": the equation's own cells carry no overflow
    # and no height, so the row grows to the equation. `.sec` stays the single
    # horizontal scrollport — and it must stay a DIFFERENT element from the
    # `min-width:max-content` grid inside it, or it would grow instead of
    # scrolling and its parent would clip (the original unreachable-content
    # bug). Vertically nothing scrolls at all; the card grows.
    stylesheet = html.split("<style>")[1].split("</style>")[0]
    naked = re.sub(r"/\*.*?\*/", "", stylesheet, flags=re.DOTALL)
    rules = {
        rule.split("{", 1)[0].strip(): rule.split("{", 1)[1]
        for rule in naked.split("}")
        if "{" in rule
    }

    def declarations(selector: str) -> str:
        return rules[selector]

    for selector in (".def", ".chk__eq", ".def math,.chk__eq math"):
        body = declarations(selector)
        assert "overflow" not in body
        assert "height" not in body
    assert "overflow-x:auto" in declarations(".sec")
    assert "min-width:max-content" in declarations(".rows")
    assert "overflow-y" not in stylesheet


def test_input_rows_have_no_definition_slot():
    # A given has no right-hand side, so it gets no definition SLOT at all —
    # not an empty one. Previously the row carried `<span class="def"></span>`
    # plus a placeholder for the second `=`, and because `.def` is the column
    # that absorbs the row's slack, that empty slot flung the value to the far
    # right edge, away from the symbol it belongs to. Now the given's grid has
    # no such column and the row reads `sym = value` as one phrase at the left.
    result = Calc(
        title="inputs only", as_of="2026-07-24", inputs={"a": Input(1, ref="src")}
    ).evaluate()
    markup = render_html(result)
    row = markup.split('<div class="rows rows--given">')[1].split("</div>")[0]

    assert 'class="def"' not in row
    assert row.count('<span class="eq">=</span>') == 1
    # symbol, its `=`, and the value adjacent — nothing between them.
    assert '<span class="eq">=</span><span class="val">1</span>' in row


def test_values_carry_their_unit_and_reference(html: str):
    assert '57.1&nbsp;<span class="unit">%</span>' in html
    assert '<span class="ref">forces.csv · max</span>' in html


def test_checks_render_description_substituted_boolean_and_badges(html: str):
    assert "capacity not exceeded" in html
    assert "utilisation target" in html
    assert "57.1 &lt; 100 = True" in html
    assert "57.1 &lt; 50 = False" in html
    assert '<span class="badge badge--pass">PASS &#10003;</span>' in html
    assert '<span class="badge badge--fail">FAIL &#10007;</span>' in html
    # ...and the failing chip is marked in form as well as colour.
    assert "chk--fail" in html


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
    # Formula rows keep all four slots: sym = definition = value.
    row = render_html(result).split('<div class="rows rows--calc">')[1]

    assert row.count('<span class="eq">=</span>') == 2
