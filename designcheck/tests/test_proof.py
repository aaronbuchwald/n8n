"""The headless proof: resolve -> evaluate -> assert the governing utilisation.

This is the deliverable of ADR 0022 phase 2 — the whole pipeline reduced to one
number, with every intermediate pinned so a wrong step cannot hide behind a
right answer. The ADR states eta = 0.759 for this scenario; the arithmetic is
reproduced in the assertions below.

    f_hk  = 0.082 · 350 · 6.0^-0.3          = 16.766   MPa
    M_yRk = 0.3 · 600 · 6.0^2.6             = 18987.4  N·mm
    F_vRk = 1.15 · sqrt(2 · M_yRk · f_hk · d) = 2247.71 N
    F_vRd = 0.80 · F_vRk / 1.3              = 1383.20  N
    F_vEd = 1000 · 4.2 / 4                  = 1050     N
    eta   = F_vEd / F_vRd                   = 0.75911  -> 0.759 (3 s.f.)
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from calcsheet import Result, render_html

from designcheck import (
    DesignConfig,
    RectSection,
    ScrewConnection,
    StructuralMember,
    footer_text,
    get_code,
    get_fastener,
    get_material,
    governing_action,
    load_kb,
    read_fem_actions,
    resolve,
)

FEM_CSV = Path(__file__).parent / "data" / "fem_forces.csv"

#: The ADR's number, to the precision it states it.
EXPECTED_ETA = 0.759


def _proof():
    """The ADR's straight-line flow, as library calls."""
    kb = load_kb()
    code = get_code(kb, "codes/ec5")
    timber = get_material(kb, "materials/timber/C24")
    screw = get_fastener(kb, "fasteners/screw/csk-6.0x120")
    column = StructuralMember("col-B2", "column", RectSection(120, 120), timber, 2800)
    beam = StructuralMember("beam-B2-4", "beam", RectSection(60, 180), timber, 4200)
    connection = ScrewConnection(
        name="conn-01",
        fastener=screw,
        members=(column, beam),
        n=4,
        shear_planes=1,
        spacing=60,
        angle_to_grain=90,
    )
    demand = governing_action(read_fem_actions(FEM_CSV), element="conn-01", component="V_z")
    config = DesignConfig(
        code="codes/ec5@2004-A2-2014",
        service_class=2,
        load_duration="medium",
        target_utilisation=0.833,
        as_of="2026-07-24",
        project="Demo hall — beam B2-4 support",
    )
    check_set = resolve(code, connection, demand, config, subject="conn-01 — vertical shear")
    return check_set, check_set.calc.evaluate()


def test_the_governing_utilisation_is_the_number_the_adr_states():
    _, result = _proof()
    _, utilisation = result.governing

    assert f"{utilisation:.3g}" == f"{EXPECTED_ETA:.3g}"
    assert utilisation == pytest.approx(0.7591071152, rel=1e-9)


def test_the_governing_check_is_the_project_target_because_it_binds_tighter():
    _, result = _proof()

    # Both checks report the same eta; 0.833 is the ceiling that actually binds.
    assert result.governing[0] == "eta <= eta_max"


def test_every_step_of_the_chain_lands_where_the_adr_says():
    _, result = _proof()
    values = result.values

    assert values["rho_k"] == 350.0
    assert values["d"] == 6.0
    assert values["f_uk"] == 600.0
    assert values["k_mod"] == 0.80
    assert values["gamma_M"] == 1.3
    assert values["n"] == 4.0
    assert values["V_Ed"] == 4.2
    assert values["eta_max"] == 0.833

    assert values["f_hk"] == pytest.approx(0.082 * 350 * 6.0**-0.3)
    assert values["f_hk"] == pytest.approx(16.7663, rel=1e-5)
    assert values["M_yRk"] == pytest.approx(0.3 * 600 * 6.0**2.6)
    assert values["M_yRk"] == pytest.approx(18987.4, rel=1e-5)
    assert values["F_vRk"] == pytest.approx(
        1.15 * math.sqrt(2 * values["M_yRk"] * values["f_hk"] * values["d"])
    )
    assert values["F_vRk"] == pytest.approx(2247.71, rel=1e-5)
    assert values["F_vRd"] == pytest.approx(0.80 * values["F_vRk"] / 1.3)
    assert values["F_vRd"] == pytest.approx(1383.20, rel=1e-5)
    assert values["F_vEd"] == 1050.0
    assert values["eta"] == pytest.approx(values["F_vEd"] / values["F_vRd"])


def test_the_displayed_values_are_the_adrs_three_significant_figures():
    _, result = _proof()
    shown = {row.symbol: (row.value_text, row.unit) for row in result.formulas}

    assert shown == {
        "f_hk": ("16.8", "MPa"),
        "M_yRk": ("1.9e+04", "N·mm"),
        "F_vRk": ("2.25e+03", "N"),
        "F_vRd": ("1.38e+03", "N"),
        "F_vEd": ("1.05e+03", "N"),
        "eta": ("0.759", ""),
    }


def test_both_checks_pass_and_the_verdict_stays_binary():
    _, result = _proof()

    assert [check.substituted for check in result.checks] == [
        "0.759 <= 1.0 = True",
        "0.759 <= 0.833 = True",
    ]
    assert [check.passed for check in result.checks] == [True, True]
    assert [check.limit for check in result.checks] == [1.0, 0.833]
    assert result.passed is True


def test_a_tighter_target_fails_the_proof_without_changing_the_utilisation():
    # The margin is a fact about the design; the verdict is a fact about the project.
    kb = load_kb()
    code = get_code(kb, "codes/ec5")
    check_set, baseline = _proof()
    strict = DesignConfig(
        code="codes/ec5",
        service_class=2,
        load_duration="medium",
        target_utilisation=0.5,  # SF 2.0
        as_of="2026-07-24",
    )
    connection = _rebuild_connection(kb)
    demand = governing_action(read_fem_actions(FEM_CSV), element="conn-01", component="V_z")

    result = resolve(code, connection, demand, strict).calc.evaluate()

    assert result.values["eta"] == pytest.approx(baseline.values["eta"])
    assert result.passed is False
    assert result.governing == ("eta <= eta_max", pytest.approx(baseline.values["eta"]))
    assert check_set.calc.inputs["eta_max"].ref == "design config · SF 1.2"


def _rebuild_connection(kb):
    timber = get_material(kb, "materials/timber/C24")
    screw = get_fastener(kb, "fasteners/screw/csk-6.0x120")
    return ScrewConnection(
        name="conn-01",
        fastener=screw,
        members=(
            StructuralMember("col-B2", "column", RectSection(120, 120), timber, 2800),
            StructuralMember("beam-B2-4", "beam", RectSection(60, 180), timber, 4200),
        ),
        n=4,
        shear_planes=1,
        spacing=60,
        angle_to_grain=90,
    )


def test_the_proof_is_deterministic():
    # Same module, same KB version, byte-identical artifact — twice.
    first, second = _proof()[1], _proof()[1]

    assert first == second
    assert render_html(first) == render_html(second)


def test_the_proof_survives_the_archival_round_trip():
    _, result = _proof()

    restored = Result.from_dict(json.loads(json.dumps(result.to_dict())))

    assert restored == result
    assert restored.governing == result.governing


def test_the_rendered_card_shows_the_margin_and_its_provenance():
    check_set, result = _proof()

    markup = render_html(result)

    assert '<span class="chk__util">0.759 ≤ 0.833</span>' in markup
    assert "Governing check <b>eta &lt;= eta_max</b> at <b>0.759</b>." in markup
    # the gutter carries the KB pin, so a reviewer can reproduce the run
    assert "materials/timber/C24 @2024.1" in markup
    assert "EC5 §8.2.2 Eq (8.6f)" in markup
    assert footer_text(check_set).startswith("kb 2024.1 · codes/ec5 @2004-A2-2014")


def test_nothing_in_the_proof_lacks_provenance():
    check_set, result = _proof()

    for row in (*result.inputs, *result.formulas):
        assert row.ref, f"{row.symbol} has an empty gutter"
    for check in result.checks:
        assert check.description
    assert set(check_set.bindings) == set(result.values)
