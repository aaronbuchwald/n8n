"""Tests for the ``sheet`` node pack (calcsheet as one node).

Covers the three things the pack owns on top of :mod:`calcsheet`: the
formulas/checks **mini-syntax** (including every way it can be malformed), the
**derived symbol sockets** (ADR 0007), and the **card height** the frontend
sizes its sandboxed iframe from. The evaluation and rendering themselves belong
to calcsheet and are tested there.

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


# -- the mini-syntax ----------------------------------------------------------


def test_parse_formulas_splits_symbol_expression_unit_and_reference():
    formulas = sheet.parse_formulas(
        "r = F_max / C_min  # demand / capacity\nU = 100 * r [%]  # utilisation"
    )
    assert [(f.symbol, f.expr, f.unit, f.ref) for f in formulas] == [
        ("r", "F_max / C_min", "", "demand / capacity"),
        ("U", "100 * r", "%", "utilisation"),
    ]


def test_parse_formulas_tolerates_blank_lines_whole_line_comments_and_no_annotations():
    formulas = sheet.parse_formulas("\n# a heading\n\nr = a / b\n")
    assert [(f.symbol, f.expr, f.unit, f.ref) for f in formulas] == [("r", "a / b", "", "")]


def test_parse_checks_splits_expression_and_description():
    checks = sheet.parse_checks("U < 100  # capacity not exceeded\nU < 50")
    assert [(c.expr, c.description) for c in checks] == [
        ("U < 100", "capacity not exceeded"),
        ("U < 50", ""),
    ]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("r F_max / C_min", "no '='"),
        ("2r = a", "not a valid symbol name"),
        ("r = a\nr = b", "defined twice"),
        ("r = [%]", "no right-hand side"),
        ("r = a +", "cannot parse expression"),
    ],
)
def test_malformed_formula_lines_raise_user_errors_naming_the_line(text, message):
    with pytest.raises(UserError) as excinfo:
        sheet.parse_formulas(text)
    assert message in str(excinfo.value)
    assert "line 1" in str(excinfo.value) or "line 2" in str(excinfo.value)


def test_an_indented_whole_line_comment_is_a_comment_not_an_entry():
    assert [f.symbol for f in sheet.parse_formulas("r = a\n   # indented comment")] == ["r"]


def test_a_check_that_is_an_assignment_is_rejected_with_a_hint():
    with pytest.raises(UserError, match="looks like an assignment"):
        sheet.parse_checks("U = 100")


def test_a_check_may_use_equality_and_other_relations():
    checks = sheet.parse_checks("U == 100\nU >= 50\nU != 0")
    assert [c.expr for c in checks] == ["U == 100", "U >= 50", "U != 0"]


def test_overlong_text_is_refused_before_parsing():
    with pytest.raises(UserError, match="too long"):
        sheet.parse_formulas("r = a\n" * 4000)


def test_non_string_input_is_refused():
    with pytest.raises(UserError, match="must be a string"):
        sheet.parse_formulas(["r = a"])


# -- derived input sockets (ADR 0007) -----------------------------------------


def test_free_symbols_become_sockets_in_first_appearance_order():
    derived = sheet.formula_free_symbols(
        "r = F_max / C_min  # demand / capacity\nU = 100 * r [%]  # utilisation"
    )
    assert [d["name"] for d in derived] == ["F_max", "C_min"]
    assert all(d["derived"] is True and d["required"] is True for d in derived)
    assert all(d["widget"] == {"kind": "number", "subtype": "float"} for d in derived)


def test_a_symbol_a_previous_formula_defined_is_not_a_socket():
    """`r` is computed, so only `F_max`/`C_min` are inputs."""
    derived = sheet.formula_free_symbols("r = F_max / C_min\nU = 100 * r")
    assert [d["name"] for d in derived] == ["F_max", "C_min"]


def test_math_names_sympy_resolves_are_never_sockets():
    """`sqrt`/`pi` keep their sympy meaning, so they must not become inputs."""
    derived = sheet.formula_free_symbols("h = sqrt(x**2 + y**2)\na = pi * r**2")
    assert [d["name"] for d in derived] == ["x", "y", "r"]


def test_a_derived_symbol_colliding_with_a_static_param_is_refused():
    with pytest.raises(UserError, match="rename the symbol 'precision'"):
        sheet.formula_free_symbols("r = precision * 2")


def test_the_spec_declares_the_dynamic_seam_and_the_renderer():
    spec = sheet.calc_card.spec
    assert spec["id"] == "sheet.calc_card"
    assert spec["dynamicInputs"] == {"param": "formulas"}
    assert spec["renderer"] == {
        "kind": "html-card",
        "config": {
            "socket": "result",
            "height": sheet.DEFAULT_CARD_HEIGHT,
        },
    }
    # ONE output: the card. A frame's pixel height is presentation, not
    # dataflow, so it is never published as a socket.
    assert [o["name"] for o in spec["outputs"]] == ["result"]


def test_the_multi_line_literals_declare_the_calc_widget_with_the_sheet_dialect():
    """ADR 0018 D2: `formulas`/`checks` opt into the line-oriented calc editor.

    Both are inherently multi-line (one entry per line), so neither may fall
    through to the type-derived single-line text widget. The placeholder carries
    the mini-syntax skeleton — the syntax is taught where it is used (D4).
    """
    widgets = {i["name"]: i["widget"] for i in sheet.calc_card.spec["inputs"]}
    assert widgets["formulas"] == {
        "kind": "calc",
        "config": {
            "language": "calcsheet",
            "multiline": True,
            "placeholder": "symbol = expression [unit]  # reference",
        },
    }
    assert widgets["checks"] == {
        "kind": "calc",
        "config": {
            "language": "calcsheet",
            "multiline": True,
            "placeholder": "expression  # description",
        },
    }
    # The other string param keeps the type-derived single-line text widget.
    assert widgets["title"] == {"kind": "text"}


# -- the node itself ----------------------------------------------------------


@needs_sym_extra
def test_calc_card_renders_a_self_contained_card():
    out = sheet.calc_card(
        title="Capacity check",
        as_of="2026-07-24",
        formulas="r = F_max / C_min  # demand / capacity\nU = 100 * r [%]  # utilisation",
        checks="U < 100  # capacity not exceeded\nU < 50  # utilisation target",
        F_max=120.0,
        C_min=210.0,
    )
    html = out
    assert html.startswith("<!doctype html>")
    assert '<span class="val">0.571</span>' in html
    assert '57.1&nbsp;<span class="unit">%</span>' in html
    assert 'badge--pass">PASS' in html and 'badge--fail">FAIL' in html
    assert "Overall <b>FAIL</b>" in html
    # Self-contained: no script, no stylesheet link, no network reference.
    assert "http" not in html and "<script" not in html and "<link" not in html


@needs_sym_extra
def test_a_whitelisted_math_name_evaluates_instead_of_needing_a_socket():
    out = sheet.calc_card(formulas="h = sqrt(x**2 + y**2)", checks="h > 0", x=3.0, y=4.0)
    assert '<span class="val">5</span>' in out


@needs_sym_extra
def test_a_false_check_returns_a_card_instead_of_raising():
    out = sheet.calc_card(formulas="U = 100 * x", checks="U < 50", x=1.0)
    assert "Overall <b>FAIL</b>" in out


@needs_sym_extra
def test_an_unknown_symbol_raises_a_user_error_listing_what_is_available():
    with pytest.raises(UserError) as excinfo:
        sheet.calc_card(formulas="r = F_max / C_min", F_max=1.0)
    message = str(excinfo.value)
    assert "C_min" in message and "F_max" in message


@needs_sym_extra
def test_a_check_that_is_a_quantity_not_a_verdict_raises():
    """A number is not a verdict — calcsheet's rule, surfaced as a UserError."""
    with pytest.raises(UserError, match="not a boolean"):
        sheet.calc_card(formulas="U = x", checks="2 * U", x=1.0)


@needs_sym_extra
def test_a_non_numeric_socket_value_raises_naming_the_input():
    with pytest.raises(UserError, match="input 'x' must be a number"):
        sheet.calc_card(formulas="U = x", x="not a number")
