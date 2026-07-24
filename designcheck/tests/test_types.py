"""T1–T6, T9: what each domain type refuses, and why it is worth refusing.

Every dataclass here is inert data, so its only behaviour is saying no. These
tests are that vocabulary of refusals.
"""

from __future__ import annotations

import dataclasses

import pytest

from designcheck import (
    ActionRow,
    BuildingCode,
    Clause,
    Concrete,
    Demand,
    DesignCheckError,
    DesignConfig,
    FastenerSteel,
    KbRef,
    RectSection,
    Screw,
    ScrewConnection,
    Steel,
    StructuralMember,
    SymbolSpec,
    Timber,
)

REF = KbRef(address="materials/timber/C24", version="2024.1", source="EN 338:2016 Table 1")
STEEL_REF = KbRef(address="fasteners/screw/x", version="2024.1", source="DoP")


# -- T1 DesignConfig ----------------------------------------------------------


def test_a_config_is_frozen(config):
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.service_class = 3


def test_the_config_reads_its_own_safety_factor(config):
    assert config.safety_factor == pytest.approx(1.2, rel=1e-3)


def test_an_edition_pin_splits_off_the_address():
    pinned = DesignConfig(
        code="codes/ec5@2004-A2-2014",
        service_class=2,
        load_duration="medium",
        target_utilisation=0.833,
        as_of="2026-07-24",
    )

    assert (pinned.code_address, pinned.code_edition) == ("codes/ec5", "2004-A2-2014")


def test_an_unpinned_code_reports_no_edition(config):
    assert (config.code_address, config.code_edition) == ("codes/ec5", "")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("code", "  ", "must be a KB address"),
        ("service_class", 0, "at least 1"),
        ("service_class", 2.5, "whole number"),
        ("load_duration", "eternal", "is not one of"),
        ("target_utilisation", 0.0, r"\(0, 1\]"),
        ("target_utilisation", 1.5, r"\(0, 1\]"),
        ("units", "imperial", "is not one of"),
        ("as_of", "", "not a clock reading"),
    ],
)
def test_a_config_refuses_a_knob_it_cannot_honour(field, value, message):
    good = {
        "code": "codes/ec5",
        "service_class": 2,
        "load_duration": "medium",
        "target_utilisation": 0.833,
        "as_of": "2026-07-24",
    }
    with pytest.raises(DesignCheckError, match=message):
        DesignConfig(**{**good, field: value})


# -- T2 materials -------------------------------------------------------------


def test_a_kb_ref_without_provenance_cannot_be_traced():
    with pytest.raises(DesignCheckError, match="KbRef.source must be non-empty"):
        KbRef(address="materials/timber/C24", version="2024.1", source="")


def test_a_kb_ref_prints_the_gutter_pin():
    assert REF.pin == "materials/timber/C24 @2024.1"


@pytest.mark.parametrize("bad", [0.0, -350.0, float("nan")])
def test_a_material_property_must_be_a_positive_number(bad):
    with pytest.raises(DesignCheckError, match="Timber.rho_k must be a positive number"):
        Timber(ref=REF, grade="C24", rho_k=bad, f_mk=24.0, f_c0k=21.0, E_mean=11000.0)


def test_a_material_needs_a_grade():
    with pytest.raises(DesignCheckError, match="Timber.grade must be non-empty"):
        Timber(ref=REF, grade=" ", rho_k=350.0, f_mk=24.0, f_c0k=21.0, E_mean=11000.0)


def test_every_family_of_the_union_validates_the_same_way():
    with pytest.raises(DesignCheckError, match="Steel.f_yk"):
        Steel(ref=REF, grade="S355", f_yk=-1.0, f_uk=490.0, E=210000.0)
    with pytest.raises(DesignCheckError, match="Concrete.f_ck"):
        Concrete(ref=REF, grade="C30/37", f_ck=0.0, E_cm=33000.0)
    with pytest.raises(DesignCheckError, match="FastenerSteel.f_uk"):
        FastenerSteel(ref=STEEL_REF, f_uk=-600.0)


def test_a_material_never_stores_a_design_value(timber):
    # Characteristic values only: k_mod and gamma_M belong to the sheet's rows.
    fields = {field.name for field in dataclasses.fields(timber)}
    assert not fields & {"k_mod", "gamma_M", "f_md", "rho_d"}


# -- T3 members ---------------------------------------------------------------


def test_a_section_must_have_positive_dimensions():
    with pytest.raises(DesignCheckError, match="RectSection.h must be a positive number"):
        RectSection(b=120.0, h=0.0)


def test_a_section_reports_its_area():
    assert RectSection(60, 180).area == 10800.0


def test_a_member_needs_a_name_that_matches_the_fem_model(timber):
    with pytest.raises(DesignCheckError, match="ties the member to the FEM element id"):
        StructuralMember(
            name="", role="beam", section=RectSection(60, 180), material=timber, length=4200
        )


def test_a_member_role_is_closed(timber):
    with pytest.raises(DesignCheckError, match="role 'strut' is not one of column, beam"):
        StructuralMember(
            name="s1", role="strut", section=RectSection(60, 60), material=timber, length=1000
        )


def test_a_member_knows_whether_it_is_timber(beam, timber):
    assert beam.is_timber is True
    steel_member = StructuralMember(
        name="s1",
        role="column",
        section=RectSection(100, 100),
        material=Steel(ref=REF, grade="S355", f_yk=355.0, f_uk=490.0, E=210000.0),
        length=3000,
    )
    assert steel_member.is_timber is False


def test_a_screw_shorter_than_it_is_thick_is_not_a_screw():
    steel = FastenerSteel(ref=STEEL_REF, f_uk=600.0)
    with pytest.raises(DesignCheckError, match="must exceed diameter"):
        Screw(ref=STEEL_REF, d=6.0, L=5.0, steel=steel)


def test_a_screw_surfaces_its_steel_strength(screw):
    assert screw.f_uk == 600.0


# -- T4 connection ------------------------------------------------------------


def test_shear_planes_and_member_count_must_agree(screw, column, beam, timber):
    # n shear planes need n+1 members; nothing else on the object can catch this.
    with pytest.raises(DesignCheckError, match="2 shear plane\\(s\\) need 3 members, got 2"):
        ScrewConnection(
            name="conn-01",
            fastener=screw,
            members=(column, beam),
            n=4,
            shear_planes=2,
            spacing=60,
            angle_to_grain=90,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("name", "", "ties the connection to the FEM element id"),
        ("n", 0, "at least 1"),
        ("n", True, "at least 1"),
        ("spacing", -60.0, "spacing must be positive"),
        ("angle_to_grain", 270.0, "angle_to_grain must be 0..180"),
    ],
)
def test_a_connection_refuses_impossible_layout(screw, column, beam, field, value, message):
    good = {
        "name": "conn-01",
        "fastener": screw,
        "members": (column, beam),
        "n": 4,
        "shear_planes": 1,
        "spacing": 60.0,
        "angle_to_grain": 90.0,
    }
    with pytest.raises(DesignCheckError, match=message):
        ScrewConnection(**{**good, field: value})


def test_a_connection_reports_whether_all_its_members_are_timber(connection):
    assert connection.all_timber is True
    assert connection.kind == "screw"


# -- T5/T6 code and clauses ---------------------------------------------------


def test_a_formula_clause_needs_a_formula_and_a_symbol():
    with pytest.raises(DesignCheckError, match="needs both 'formula' and 'defines'"):
        Clause(id="x", citation="c", title="t", kind="formula", formula="1 + 1")


def test_a_formula_clause_must_not_also_be_a_check():
    with pytest.raises(DesignCheckError, match="split it into two clauses"):
        Clause(
            id="x",
            citation="c",
            title="t",
            kind="formula",
            formula="a",
            defines="b",
            check="b <= 1",
        )


def test_a_check_clause_needs_a_check():
    with pytest.raises(DesignCheckError, match="a check clause needs 'check'"):
        Clause(id="x", citation="c", title="t", kind="check")


def test_a_check_clause_must_not_define_a_symbol():
    with pytest.raises(DesignCheckError, match="must not carry 'formula' or 'defines'"):
        Clause(id="x", citation="c", title="t", kind="check", check="a <= 1", defines="a")


def test_a_clause_kind_is_closed():
    with pytest.raises(DesignCheckError, match="kind 'guideline' is not one of"):
        Clause(id="x", citation="c", title="t", kind="guideline")


def test_a_clause_needs_a_citation_because_the_gutter_is_the_carrier():
    with pytest.raises(DesignCheckError, match="citation must be non-empty"):
        Clause(id="x", citation="", title="t", kind="formula", formula="1", defines="a")


@pytest.mark.parametrize("symbol", ["2bad", "with space", "f-hk"])
def test_a_clause_refuses_a_symbol_that_is_not_a_name(symbol):
    with pytest.raises(DesignCheckError, match="not a valid symbol name"):
        Clause(id="x", citation="c", title="t", kind="formula", formula="1", defines=symbol)


def test_a_clause_composes_its_check_description():
    clause = Clause(
        id="ec5-8.1.1", citation="EC5 §8.1.1", title="resistance", kind="check", check="eta <= 1.0"
    )

    assert clause.description == "EC5 §8.1.1 — resistance"
    assert clause.expression == "eta <= 1.0"


def test_a_symbol_spec_needs_a_binding_source():
    with pytest.raises(DesignCheckError, match="'bind' must name a binding source"):
        SymbolSpec(symbol="rho_k", bind="")


def test_a_code_refuses_duplicate_clause_ids():
    clause = Clause(id="dup", citation="c", title="t", kind="formula", formula="1", defines="a")
    with pytest.raises(DesignCheckError, match="duplicate clause id 'dup'"):
        BuildingCode(
            ref=REF,
            name="A code",
            edition="2024",
            gamma_M={"connections": 1.3},
            k_mod={},
            clauses=(clause, dataclasses.replace(clause, defines="b")),
        )


def test_a_code_needs_at_least_one_partial_factor():
    with pytest.raises(DesignCheckError, match="gamma_M must declare at least one domain"):
        BuildingCode(ref=REF, name="A code", edition="2024", gamma_M={}, k_mod={})


def test_a_code_names_the_cell_it_does_not_have(code):
    with pytest.raises(DesignCheckError, match="no k_mod for service class 9"):
        code.modification_factor(9, "medium")
    with pytest.raises(DesignCheckError, match="no gamma_M for domain 'masonry'"):
        code.partial_factor("masonry")


def test_a_code_pins_itself_by_edition(code):
    assert code.pin == "codes/ec5 @2004-A2-2014"
    assert code.modification_factor(2, "medium") == 0.80
    assert code.partial_factor("connections") == 1.3


# -- T9 actions ---------------------------------------------------------------


def test_an_action_row_needs_an_element_and_a_case():
    with pytest.raises(DesignCheckError, match="ActionRow.case must be non-empty"):
        ActionRow(element="conn-01", case="", N=0, V_y=0, V_z=0, M_y=0, M_z=0)


def test_an_action_row_refuses_a_non_finite_component():
    with pytest.raises(DesignCheckError, match="V_z is not finite"):
        ActionRow(element="conn-01", case="ULS-1", N=0, V_y=0, V_z=float("inf"), M_y=0, M_z=0)


def test_an_action_row_names_the_components_it_has():
    row = ActionRow(element="conn-01", case="ULS-1", N=1.2, V_y=0.1, V_z=3.1, M_y=0, M_z=0)

    assert row.component("V_z") == 3.1
    with pytest.raises(DesignCheckError, match="unknown action component 'V_x'"):
        row.component("V_x")


def test_a_demand_must_be_traceable():
    with pytest.raises(DesignCheckError, match="Demand.source must be non-empty"):
        Demand(element="conn-01", component="V_z", value=4.2, unit="kN", case="ULS-2", source="")


def test_a_demand_prints_its_gutter_ref(demand):
    assert demand.ref == "fem_forces.csv · V_z · ULS-2"
