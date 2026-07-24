"""Applicability: a closed, declarative vocabulary that never executes KB content."""

from __future__ import annotations

import dataclasses

import pytest

from designcheck import (
    DesignCheckError,
    RectSection,
    ScrewConnection,
    Steel,
    StructuralMember,
    applies,
    evaluate_predicate,
    facts,
)
from designcheck.materials import KbRef

WHAT = "clause 'test'"


def _eval(text, known):
    return evaluate_predicate(text, known, what=WHAT)


@pytest.fixture
def known(connection, config):
    return facts(connection, config)


def test_the_fact_table_is_flat_and_finite(known):
    assert known["connection.kind"] == "screw"
    assert known["fastener.d"] == 6.0
    assert known["members.all_timber"] is True
    assert known["members.count"] == 2
    assert known["config.load_duration"] == "medium"


@pytest.mark.parametrize(
    ("predicate", "expected"),
    [
        ("connection.kind == 'screw'", True),
        ('connection.kind == "bolt"', False),
        ("connection.kind != 'bolt'", True),
        ("fastener.d <= 6.0", True),
        ("fastener.d < 6.0", False),
        ("fastener.d >= 6", True),
        ("fastener.d > 8", False),
        ("connection.shear_planes == 1", True),
        ("members.all_timber", True),
        ("not members.all_timber", False),
        ("members.all_timber == true", True),
        ("config.service_class == 2", True),
        ("fastener.f_uk >= 4e2", True),
    ],
)
def test_the_predicate_vocabulary(predicate, expected, known):
    assert _eval(predicate, known) is expected


def test_a_false_flag_flips_under_not(screw, column, timber):
    steel_member = StructuralMember(
        name="plate",
        role="beam",
        section=RectSection(100, 10),
        material=Steel(
            ref=KbRef(address="materials/steel/S355", version="2024.1", source="EN 10025"),
            grade="S355",
            f_yk=355.0,
            f_uk=490.0,
            E=210000.0,
        ),
        length=2000,
    )
    mixed = ScrewConnection(
        name="conn-02",
        fastener=screw,
        members=(column, steel_member),
        n=2,
        shear_planes=1,
        spacing=60,
        angle_to_grain=90,
    )

    assert mixed.all_timber is False


def test_an_empty_predicate_list_always_applies(known):
    assert applies((), known, what=WHAT) is True


def test_every_predicate_must_hold(known):
    assert applies(("fastener.d <= 6.0", "members.all_timber"), known, what=WHAT) is True
    assert applies(("fastener.d <= 6.0", "fastener.d > 8"), known, what=WHAT) is False


def test_an_unknown_fact_is_an_error_not_a_quiet_false(known):
    # A typo in a KB file must not silently drop a clause from a proof.
    with pytest.raises(DesignCheckError, match="unknown fact 'fastener.diameter'"):
        _eval("fastener.diameter <= 6.0", known)


def test_the_error_lists_the_facts_that_do_exist(known):
    with pytest.raises(DesignCheckError) as error:
        _eval("nonsense", known)
    assert "known facts:" in str(error.value)
    assert "members.all_timber" in str(error.value)


def test_an_unreadable_predicate_states_the_grammar(known):
    with pytest.raises(DesignCheckError, match="cannot read predicate"):
        _eval("fastener.d ~= 6.0", known)


def test_a_non_boolean_used_as_a_flag_is_refused(known):
    with pytest.raises(DesignCheckError, match="as a flag, but it is float"):
        _eval("fastener.d", known)


def test_ordering_a_string_against_a_number_is_refused(known):
    with pytest.raises(DesignCheckError, match="need two numbers"):
        _eval("config.load_duration < 3", known)


def test_a_bad_literal_states_what_a_literal_may_be(known):
    with pytest.raises(DesignCheckError, match="a literal must be a number, true/false"):
        _eval("fastener.d == medium", known)


def test_equality_across_types_is_false_rather_than_a_crash(known):
    assert _eval("connection.n == 'screw'", known) is False
    assert _eval("members.all_timber == 1", known) is False


def test_predicates_are_data_and_never_executed(known):
    # The refusal is the proof: this text is not Python that ran, it is text
    # that failed to parse as a predicate.
    with pytest.raises(DesignCheckError, match="cannot read predicate"):
        _eval("__import__('os').system('true')", known)


def test_a_clause_is_filtered_out_when_a_predicate_fails(code, known):
    thick = dataclasses.replace(
        next(clause for clause in code.clauses if clause.id == "ec5-8.15"),
        applies=("fastener.d <= 4.0",),
    )

    assert applies(thick.applies, known, what=WHAT) is False
