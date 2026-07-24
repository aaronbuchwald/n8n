"""The dimensional tripwire: it must fire on the slip and stay out of the way otherwise."""

from __future__ import annotations

import math

import pytest

from designcheck import DesignCheckError, convert, parse_unit, split_unit


@pytest.mark.parametrize(
    ("text", "name", "unit"),
    [
        ("rho_k[kg/m^3]", "rho_k", "kg/m^3"),
        ("V_z[kN]", "V_z", "kN"),
        ("n", "n", ""),
        ("  d [ mm ] ", "d", "mm"),
        ("k_mod[]", "k_mod", ""),
    ],
)
def test_a_bracketed_name_splits_into_name_and_unit(text, name, unit):
    assert split_unit(text) == (name, unit)


def test_a_declaration_with_no_name_is_refused():
    with pytest.raises(DesignCheckError, match="not a 'name' or 'name\\[unit\\]'"):
        split_unit("[kN]")


@pytest.mark.parametrize("text", ["", "-", "1"])
def test_the_empty_unit_is_dimensionless(text):
    assert parse_unit(text).dimension == (0, 0, 0, 0)


@pytest.mark.parametrize(
    ("text", "factor"),
    [
        ("mm", 1e-3),
        ("kN", 1e3),
        ("MPa", 1e6),
        ("N/mm^2", 1e6),  # the same dimension by two spellings
        ("kg/m^3", 1.0),
        ("kNm", 1e3),
        ("N·mm", 1e-3),
    ],
)
def test_a_compound_unit_reduces_to_its_si_factor(text, factor):
    assert parse_unit(text).factor == pytest.approx(factor)


def test_superscripts_read_as_exponents():
    # A KB file should be able to say kg/m³ and still be machine-checked.
    assert parse_unit("kg/m³").dimension == parse_unit("kg/m^3").dimension


def test_mpa_and_n_per_mm2_are_the_same_dimension():
    assert parse_unit("MPa").dimension == parse_unit("N/mm^2").dimension == (1, -1, -2, 0)


def test_an_angle_is_not_a_bare_ratio():
    # Its own dimension slot, so a dimensionless number cannot bind to a degree symbol.
    assert parse_unit("deg").dimension != parse_unit("").dimension
    assert convert(180.0, "deg", "rad", what="test") == pytest.approx(math.pi)


def test_an_unknown_unit_names_itself():
    with pytest.raises(DesignCheckError, match="unknown unit 'furlong'"):
        parse_unit("furlong")


def test_an_unreadable_part_names_itself():
    with pytest.raises(DesignCheckError, match="cannot read the part"):
        parse_unit("kg/m^^3")


def test_two_slashes_are_refused():
    with pytest.raises(DesignCheckError, match="more than one '/'"):
        parse_unit("kg/m/s")


@pytest.mark.parametrize(
    ("value", "source", "target", "expected"),
    [
        (4.2, "kN", "N", 4200.0),
        (1050.0, "N", "kN", 1.05),
        (6.0, "mm", "m", 0.006),
        (350.0, "kg/m^3", "kg/m^3", 350.0),
        (600.0, "MPa", "N/mm^2", 600.0),
    ],
)
def test_conversion_scales_within_a_dimension(value, source, target, expected):
    assert convert(value, source, target, what="test") == pytest.approx(expected)


def test_a_wrong_dimension_is_refused_by_name():
    # The whole point: a shear column labelled in mm dies here, not six rows later.
    with pytest.raises(DesignCheckError, match="expected force \\(kN\\), got length \\(mm\\)"):
        convert(4.2, "mm", "kN", what="column 'V_z'")


def test_dimensionless_is_named_in_the_refusal():
    with pytest.raises(DesignCheckError, match="got dimensionless"):
        convert(1.0, "", "kN", what="symbol 'V_Ed'")
