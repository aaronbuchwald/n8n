"""T7: clauses in, one ``calcsheet.Calc`` out — and every refusal on the way."""

from __future__ import annotations

import dataclasses

import pytest

from calcsheet import Calc, Check, Formula, Input

from designcheck import (
    BuildingCode,
    Clause,
    DesignCheckError,
    DesignConfig,
    FastenerSteel,
    KbRef,
    Screw,
    ScrewConnection,
    StructuralMember,
    SymbolSpec,
    footer_text,
    resolve,
)
from designcheck.resolve import Binding, _order


def _clause(id_, defines, requires=(), **extra):
    return Clause(
        id=id_,
        citation=f"cite {id_}",
        title=f"title {id_}",
        kind="formula",
        formula="1",
        defines=defines,
        requires=requires,
        **extra,
    )


# -- what resolution produces -------------------------------------------------


def test_resolution_selects_the_applicable_clauses_in_reading_order(
    code, connection, demand, config
):
    check_set = resolve(code, connection, demand, config)

    assert [clause.id for clause in check_set.clauses] == [
        "ec5-8.15",
        "ec5-8.14",
        "ec5-8.6f",
        "ec5-2.17",
        "designcheck-demand",
        "designcheck-eta",
        "ec5-8.1.1",
        "designcheck-target",
    ]


def test_the_emitted_value_is_a_plain_calcsheet_calc(code, connection, demand, config):
    calc = resolve(code, connection, demand, config).calc

    assert isinstance(calc, Calc)
    assert all(isinstance(row, Input) for row in calc.inputs.values())
    assert all(isinstance(row, Formula) for row in calc.formulas)
    assert all(isinstance(row, Check) for row in calc.checks)
    assert calc.as_of == "2026-07-24"  # the config's pin, never the clock


def test_the_given_rows_are_the_bound_leaves_in_the_codes_own_order(
    code, connection, demand, config
):
    calc = resolve(code, connection, demand, config).calc

    assert list(calc.inputs) == [
        "rho_k",
        "d",
        "f_uk",
        "k_mod",
        "gamma_M",
        "n",
        "V_Ed",
        "eta_max",
    ]


def test_every_given_row_carries_the_ref_its_value_came_from(
    code, connection, demand, config
):
    calc = resolve(code, connection, demand, config).calc

    assert {symbol: row.ref for symbol, row in calc.inputs.items()} == {
        "rho_k": "kb: materials/timber/C24 @2024.1",
        "d": "kb: fasteners/screw/csk-6.0x120 @2024.1",
        "f_uk": "kb: fasteners/screw/csk-6.0x120 @2024.1",
        "k_mod": "EC5 Table 3.1 · SC2, medium-term",
        "gamma_M": "EC5 Table 2.3 · connections",
        "n": "connection conn-01",
        "V_Ed": "fem_forces.csv · V_z · ULS-2",
        "eta_max": "design config · SF 1.2",
    }


def test_a_row_with_an_empty_gutter_can_never_be_emitted(code, connection, demand, config):
    check_set = resolve(code, connection, demand, config)

    assert all(row.ref for row in check_set.calc.inputs.values())
    assert all(row.ref for row in check_set.calc.formulas)
    assert all(check.description for check in check_set.calc.checks)


def test_formula_rows_are_reffed_by_clause_citation(code, connection, demand, config):
    calc = resolve(code, connection, demand, config).calc

    assert [(row.symbol, row.ref, row.unit) for row in calc.formulas] == [
        ("f_hk", "EC5 §8.3.1.1 Eq (8.15) via §8.7.1(3)", "MPa"),
        ("M_yRk", "EC5 §8.3.1.1 Eq (8.14)", "N·mm"),
        ("F_vRk", "EC5 §8.2.2 Eq (8.6f)", "N"),
        ("F_vRd", "EC5 §2.4.3 Eq (2.17)", "N"),
        ("F_vEd", "demand · shared by the fastener group", "N"),
        ("eta", "utilisation", ""),
    ]


def test_both_checks_declare_the_utilisation_symbol(code, connection, demand, config):
    calc = resolve(code, connection, demand, config).calc

    assert [(check.expr, check.utilisation) for check in calc.checks] == [
        ("eta <= 1.0", "eta"),
        ("eta <= eta_max", "eta"),
    ]
    assert calc.checks[1].description == "design config · SF 1.2 — project target safety factor"


def test_characteristic_becomes_design_exactly_once_and_visibly(
    code, connection, demand, config
):
    # k_mod and gamma_M are GIVEN rows with citations; Eq (2.17) is the only
    # place they are applied.
    calc = resolve(code, connection, demand, config).calc
    conversions = [row for row in calc.formulas if "gamma_M" in row.expr]

    assert {"k_mod", "gamma_M"} <= set(calc.inputs)
    assert [row.symbol for row in conversions] == ["F_vRd"]
    assert conversions[0].expr == "k_mod * F_vRk / gamma_M"


# -- the bindings ledger ------------------------------------------------------


def test_every_leaf_binding_records_value_unit_ref_and_origin(
    code, connection, demand, config
):
    bindings = resolve(code, connection, demand, config).bindings

    assert (bindings["rho_k"].value, bindings["rho_k"].unit) == (350.0, "kg/m³")
    assert bindings["rho_k"].origin == "material"
    assert bindings["d"].origin == "product"
    assert bindings["k_mod"].origin == "code"
    assert bindings["n"].origin == "connection"
    assert bindings["V_Ed"].origin == "demand"
    assert bindings["eta_max"].origin == "config"


def test_a_computed_symbol_is_ledgered_without_inventing_a_value(
    code, connection, demand, config
):
    # Resolution happens before evaluation; a number here would be a guess.
    binding = resolve(code, connection, demand, config).bindings["F_vRk"]

    assert binding.origin == "clause"
    assert binding.clause == "ec5-8.6f"
    assert binding.value is None


def test_the_ledger_and_the_gutter_say_the_same_thing(code, connection, demand, config):
    check_set = resolve(code, connection, demand, config)

    for symbol, row in check_set.calc.inputs.items():
        assert check_set.bindings[symbol].ref == row.ref


def test_a_binding_may_not_be_built_without_a_ref():
    with pytest.raises(DesignCheckError, match="cannot emit a row with an empty gutter"):
        Binding(symbol="x", origin="material", ref="")


# -- pins and notes -----------------------------------------------------------


def test_the_run_is_pinned_by_snapshot_edition_and_as_of(code, connection, demand, config):
    check_set = resolve(code, connection, demand, config)

    assert check_set.pins == ("kb 2024.1", "codes/ec5 @2004-A2-2014", "as_of 2026-07-24")


def test_the_fine_print_names_every_neglect(code, connection, demand, config):
    notes = footer_text(resolve(code, connection, demand, config))

    assert "rope effect" in notes
    assert "§8.7.2" in notes
    assert notes.startswith("kb 2024.1 · codes/ec5 @2004-A2-2014 · as_of 2026-07-24 — ")


def test_the_subject_can_be_named_by_the_caller(code, connection, demand, config):
    check_set = resolve(code, connection, demand, config, subject="conn-01 — vertical shear")

    assert check_set.subject == "conn-01 — vertical shear"
    assert check_set.calc.title.startswith("conn-01 — vertical shear · EN 1995-1-1")


# -- ordering -----------------------------------------------------------------


def test_dependencies_are_emitted_before_their_dependents():
    ordered = _order(
        [_clause("late", "z", requires=("y",)), _clause("early", "y")]
    )

    assert [clause.id for clause in ordered] == ["early", "late"]


def test_independent_clauses_keep_their_declaration_order():
    ordered = _order([_clause("a", "x"), _clause("b", "y")])

    assert [clause.id for clause in ordered] == ["a", "b"]


def test_a_cycle_names_the_clauses_in_it():
    with pytest.raises(DesignCheckError, match="cycle: a -> b -> a"):
        _order([_clause("a", "x", requires=("y",)), _clause("b", "y", requires=("x",))])


def test_a_clause_that_needs_its_own_output_is_a_cycle():
    with pytest.raises(DesignCheckError, match="cycle: a -> a"):
        _order([_clause("a", "x", requires=("x",))])


def test_two_clauses_cannot_define_the_same_symbol():
    with pytest.raises(DesignCheckError, match="both define 'x'"):
        _order([_clause("a", "x"), _clause("b", "x")])


# -- refusals -----------------------------------------------------------------


def _minimal_code(code, **overrides):
    fields = {
        "ref": code.ref,
        "name": code.name,
        "edition": code.edition,
        "gamma_M": code.gamma_M,
        "k_mod": code.k_mod,
        "clauses": code.clauses,
        "symbols": code.symbols,
    }
    return BuildingCode(**{**fields, **overrides})


def test_an_unsatisfiable_symbol_names_the_clause_that_wanted_it(
    code, connection, demand, config
):
    orphan = Clause(
        id="ec5-orphan",
        citation="c",
        title="t",
        kind="formula",
        formula="mystery * 2",
        defines="q",
        requires=("mystery",),
    )
    broken = _minimal_code(code, clauses=(*code.clauses, orphan))

    with pytest.raises(DesignCheckError, match="unsatisfiable symbol"):
        resolve(broken, connection, demand, config)


def test_a_binding_outside_the_closed_vocabulary_is_refused_with_the_vocabulary(
    code, connection, demand, config
):
    broken = _minimal_code(
        code, symbols={**code.symbols, "rho_k": SymbolSpec(symbol="rho_k", bind="weather.today")}
    )

    with pytest.raises(DesignCheckError) as error:
        resolve(broken, connection, demand, config)
    assert "unknown binding source" in str(error.value)
    assert "material.rho_k" in str(error.value)
    assert "code.gamma_M.<domain>" in str(error.value)


def test_a_property_this_material_family_does_not_have_is_refused(
    code, connection, demand, config
):
    # `material.f_ck` is in the vocabulary — but the connection joins timber.
    broken = _minimal_code(
        code,
        symbols={
            **code.symbols,
            "rho_k": SymbolSpec(symbol="rho_k", bind="material.f_ck", unit="MPa"),
        },
    )

    with pytest.raises(DesignCheckError, match="Timber has no property 'f_ck'"):
        resolve(broken, connection, demand, config)


def test_a_symbol_declared_in_the_wrong_dimension_is_refused(
    code, connection, demand, config
):
    broken = _minimal_code(
        code,
        symbols={
            **code.symbols,
            "rho_k": SymbolSpec(symbol="rho_k", bind="material.rho_k", unit="MPa"),
        },
    )

    with pytest.raises(DesignCheckError, match="expected stress .* got density"):
        resolve(broken, connection, demand, config)


def test_a_config_pinning_another_code_is_refused(code, connection, demand):
    other = DesignConfig(
        code="codes/nds",
        service_class=2,
        load_duration="medium",
        target_utilisation=0.833,
        as_of="2026-07-24",
    )

    with pytest.raises(DesignCheckError, match="pins code 'codes/nds'"):
        resolve(code, connection, demand, other)


def test_a_config_pinning_another_edition_is_refused(code, connection, demand):
    stale = DesignConfig(
        code="codes/ec5@2023",
        service_class=2,
        load_duration="medium",
        target_utilisation=0.833,
        as_of="2026-07-24",
    )

    with pytest.raises(DesignCheckError, match="KB holds edition '2004-A2-2014'"):
        resolve(code, connection, demand, stale)


def test_actions_from_another_element_are_refused(code, connection, demand, config):
    foreign = dataclasses.replace(demand, element="conn-99")

    with pytest.raises(DesignCheckError, match="checking one connection with another's actions"):
        resolve(code, connection, foreign, config)


def test_a_service_class_the_code_has_no_cell_for_is_refused(code, connection, demand, config):
    exotic = dataclasses.replace(config, service_class=4)

    with pytest.raises(DesignCheckError, match="no k_mod for service class 4"):
        resolve(code, connection, demand, exotic)


def test_members_of_different_materials_are_refused_rather_than_guessed(
    code, screw, column, beam, demand, config, other_timber
):
    mixed = ScrewConnection(
        name="conn-01",
        fastener=screw,
        members=(column, dataclasses.replace(beam, material=other_timber)),
        n=4,
        shear_planes=1,
        spacing=60,
        angle_to_grain=90,
    )

    with pytest.raises(DesignCheckError, match="members of different materials"):
        resolve(code, mixed, demand, config)


def test_a_code_whose_clauses_all_filter_out_cannot_reach_a_resistance(
    code, connection, demand, config
):
    unreachable = tuple(
        dataclasses.replace(clause, applies=("fastener.d > 99",)) for clause in code.clauses
    )
    broken = _minimal_code(code, clauses=unreachable)
    # The resolver's own clauses need F_vRd, which nothing now defines.
    with pytest.raises(DesignCheckError, match="unsatisfiable symbol"):
        resolve(broken, connection, demand, config)


def test_a_thicker_screw_drops_the_nail_rule_clauses(code, column, beam, demand, config):
    thick = Screw(
        ref=KbRef(address="fasteners/screw/csk-8.0x160", version="2024.1", source="DoP"),
        d=8.0,
        L=160.0,
        steel=FastenerSteel(
            ref=KbRef(address="fasteners/screw/csk-8.0x160", version="2024.1", source="DoP"),
            f_uk=600.0,
        ),
    )
    connection = ScrewConnection(
        name="conn-01",
        fastener=thick,
        members=(column, beam),
        n=4,
        shear_planes=1,
        spacing=60,
        angle_to_grain=90,
    )

    # d > 6 mm leaves this subset with no embedment clause, so it refuses to
    # produce a proof rather than quietly proving less than it claims.
    with pytest.raises(DesignCheckError, match="unsatisfiable symbol"):
        resolve(code, connection, demand, config)


def test_the_check_set_can_evaluate_itself(code, connection, demand, config):
    assert resolve(code, connection, demand, config).evaluate().passed is True


def test_a_member_is_still_a_structural_member_after_replace(beam, other_timber):
    # guards the fixture surgery the mixed-material test relies on
    assert isinstance(dataclasses.replace(beam, material=other_timber), StructuralMember)
