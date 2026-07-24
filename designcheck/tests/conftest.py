"""Shared fixtures: the ADR's worked example, assembled once."""

from __future__ import annotations

from pathlib import Path

import pytest

from designcheck import (
    DesignConfig,
    KbRef,
    KnowledgeBase,
    RectSection,
    ScrewConnection,
    StructuralMember,
    Timber,
    get_code,
    get_fastener,
    get_material,
    governing_action,
    load_kb,
    read_fem_actions,
)

FEM_CSV = Path(__file__).parent / "data" / "fem_forces.csv"


@pytest.fixture
def kb() -> KnowledgeBase:
    return load_kb()


@pytest.fixture
def code(kb):
    return get_code(kb, "codes/ec5")


@pytest.fixture
def timber(kb):
    return get_material(kb, "materials/timber/C24")


@pytest.fixture
def screw(kb):
    return get_fastener(kb, "fasteners/screw/csk-6.0x120")


@pytest.fixture
def column(timber) -> StructuralMember:
    return StructuralMember(
        name="col-B2", role="column", section=RectSection(120, 120), material=timber, length=2800
    )


@pytest.fixture
def beam(timber) -> StructuralMember:
    return StructuralMember(
        name="beam-B2-4", role="beam", section=RectSection(60, 180), material=timber, length=4200
    )


@pytest.fixture
def connection(screw, column, beam) -> ScrewConnection:
    return ScrewConnection(
        name="conn-01",
        fastener=screw,
        members=(column, beam),
        n=4,
        shear_planes=1,
        spacing=60,
        angle_to_grain=90,
    )


@pytest.fixture
def demand():
    return governing_action(read_fem_actions(FEM_CSV), element="conn-01", component="V_z")


@pytest.fixture
def config() -> DesignConfig:
    return DesignConfig(
        code="codes/ec5",
        service_class=2,
        load_duration="medium",
        target_utilisation=0.833,  # SF 1.2
        as_of="2026-07-24",
        project="Demo hall — beam B2-4 support",
    )


@pytest.fixture
def other_timber() -> Timber:
    """A second grade, so "the members disagree" has something to disagree about."""
    return Timber(
        ref=KbRef(address="materials/timber/C16", version="2024.1", source="EN 338:2016 Table 1"),
        grade="C16",
        rho_k=310.0,
        f_mk=16.0,
        f_c0k=17.0,
        E_mean=8000.0,
    )
