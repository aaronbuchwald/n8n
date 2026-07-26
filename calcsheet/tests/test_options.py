"""Renderer options: defaults change nothing, filled slots change only themselves."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from calcsheet import CalcError, HtmlOptions, render_html
from calcsheet.examples.capacity import build_calc

GOLDEN = Path(__file__).parent / "golden" / "capacity-check.html"


@pytest.fixture(scope="module")
def result():
    return build_calc().evaluate()


def test_the_shipped_example_renders_the_pinned_card(result):
    # The regression fence for every change in this package: no edit may move a
    # byte of the default card without saying so here.
    #
    # Recaptured once, deliberately, for the light-by-default redesign — the
    # only intentional break of this fence. What moved: the light ramp is now
    # white paper / black ink, the givens grid dropped its definition column,
    # PASS/FAIL gained a distinguishing glyph, and the type scale collapsed to
    # four roles. What did NOT move: the numbers, the MathML, the section
    # order, or any value+unit markup.
    assert render_html(result) == GOLDEN.read_text(encoding="utf-8")


def test_default_options_are_the_no_options_render(result):
    assert render_html(result, HtmlOptions()) == render_html(result)


def test_options_default_to_the_light_theme_and_empty_slots():
    # A card is a document, so its default is a document's: white paper, black
    # ink, whoever opens it. `auto` and `dark` stay available — the card may be
    # handed to another viewer or a PDF path, so the theme is stated in the
    # file rather than inferred from wherever it happens to land.
    assert HtmlOptions() == HtmlOptions(theme="light", header="", footer="")
    assert "prefers-color-scheme" not in render_html(build_calc().evaluate())


def test_the_theme_is_a_choice_of_three_and_auto_is_still_one_of_them():
    for theme in ("auto", "light", "dark"):
        assert HtmlOptions(theme=theme).theme == theme


def test_options_are_json_round_trippable():
    # Same guard the engine runs on widget/renderer config: an options value
    # must survive being a graph literal.
    assert json.loads(json.dumps(asdict(HtmlOptions(theme="dark", header="Acme")))) == {
        "theme": "dark",
        "header": "Acme",
        "footer": "",
    }


def test_an_unknown_theme_is_named_and_refused():
    with pytest.raises(CalcError, match="unknown theme 'neon'"):
        HtmlOptions(theme="neon")


def test_the_header_slot_renders_a_banner_above_the_card(result):
    markup = render_html(result, HtmlOptions(header="Acme Corp"))

    assert '<div class="card__banner">Acme Corp</div>' in markup
    assert markup.index('<div class="card__banner">') < markup.index(
        '<div class="card__head">'
    )


def test_the_footer_slot_renders_fine_print_under_the_verdict(result):
    markup = render_html(result, HtmlOptions(footer="kb 2024.1 · codes/ec5 @2004"))

    assert '<div class="foot foot--note">kb 2024.1 · codes/ec5 @2004</div>' in markup
    assert markup.index('<div class="foot foot--note">') > markup.index(
        "a calc is valid only when"
    )


def test_slot_text_is_escaped_like_every_other_caller_string(result):
    markup = render_html(
        result, HtmlOptions(header="<b>hi</b>", footer="<script>x</script>")
    )

    assert "&lt;b&gt;hi&lt;/b&gt;" in markup
    assert "<b>hi</b>" not in markup
    assert "<script" not in markup.lower()


def test_slot_css_is_emitted_only_when_a_slot_is_filled(result):
    assert "card__banner" not in render_html(result)
    assert "foot--note" not in render_html(result)
    assert "card__banner{" in render_html(result, HtmlOptions(header="Acme"))


def test_the_light_theme_drops_the_dark_ramp(result):
    markup = render_html(result, HtmlOptions(theme="light"))

    assert "prefers-color-scheme" not in markup
    assert "--bg:#0e1117" not in markup


def test_the_dark_theme_applies_the_dark_ramp_unconditionally(result):
    markup = render_html(result, HtmlOptions(theme="dark"))

    assert "prefers-color-scheme" not in markup
    assert "--bg:#0e1117" in markup


def test_every_theme_stays_self_contained_and_deterministic(result):
    for theme in ("auto", "light", "dark"):
        options = HtmlOptions(theme=theme, header="Acme", footer="pinned")
        markup = render_html(result, options)

        assert markup == render_html(result, options)
        lowered = markup.lower()
        for forbidden in ("<script", "http", "onerror", "onload", "src=", "<link"):
            assert forbidden not in lowered
