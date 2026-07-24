"""T8: loading the knowledge base, and every way a bad entry must announce itself."""

from __future__ import annotations

from pathlib import Path

import pytest

from designcheck import (
    BUILTIN_KB,
    DesignCheckError,
    KnowledgeBase,
    entries,
    get_code,
    get_fastener,
    get_material,
    load_kb,
)

MANIFEST = 'version = "9.9-test"\nname = "test overlay"\n'


def _overlay(root: Path, relative: str, body: str) -> Path:
    (root / "kb.toml").write_text(MANIFEST, encoding="utf-8")
    file = root / relative
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(body, encoding="utf-8")
    return root


# -- the shipped KB -----------------------------------------------------------


def test_the_shipped_kb_pins_its_snapshot(kb):
    assert kb.version == "2024.1"
    assert kb.pins == ("kb 2024.1",)


def test_every_loaded_value_carries_its_pin(timber, screw, code):
    assert timber.ref.pin == "materials/timber/C24 @2024.1"
    assert screw.ref.pin == "fasteners/screw/csk-6.0x120 @2024.1"
    assert code.ref.pin == "codes/ec5 @2024.1"


def test_the_c24_entry_is_en338_table_1(timber):
    assert (timber.grade, timber.rho_k, timber.f_mk, timber.f_c0k, timber.E_mean) == (
        "C24",
        350.0,
        24.0,
        21.0,
        11000.0,
    )
    assert timber.ref.source == "EN 338:2016 Table 1"


def test_the_screw_arrives_whole_with_its_steel(screw):
    assert (screw.d, screw.L, screw.steel.f_uk) == (6.0, 120.0, 600.0)


def test_the_code_carries_its_tables_clauses_and_symbol_dictionary(code):
    assert code.edition == "2004-A2-2014"
    assert code.k_mod[(2, "medium")] == 0.80
    assert code.gamma_M["connections"] == 1.3
    assert [clause.id for clause in code.clauses] == [
        "ec5-8.15",
        "ec5-8.14",
        "ec5-8.6f",
        "ec5-2.17",
        "ec5-8.1.1",
    ]
    # Declaration order here is the GIVEN order of the emitted proof.
    assert list(code.symbols) == [
        "rho_k",
        "d",
        "f_uk",
        "k_mod",
        "gamma_M",
        "n",
        "V_Ed",
        "eta_max",
    ]


def test_the_kb_lists_what_it_holds(kb):
    assert entries(kb, "materials", "timber") == ("materials/timber/C24",)
    assert entries(kb, "fasteners", "screw") == ("fasteners/screw/csk-6.0x120",)
    assert entries(kb, "codes") == ("codes/ec5",)


def test_loading_the_kb_touches_nothing_until_asked():
    # BUILTIN_KB is a plain directory; import did not read it.
    assert (BUILTIN_KB / "kb.toml").is_file()


# -- addressing failures ------------------------------------------------------


def test_a_missing_entry_names_the_address_and_what_is_there(kb):
    with pytest.raises(DesignCheckError, match="'materials/timber/C99' not found") as error:
        get_material(kb, "materials/timber/C99")
    assert "materials/timber.toml offers: C24" in str(error.value)


def test_a_malformed_address_states_the_shape_it_wanted(kb):
    with pytest.raises(DesignCheckError, match="not of the form 'materials/<family>/<id>'"):
        get_material(kb, "materials/C24")
    with pytest.raises(DesignCheckError, match="not of the form 'codes/<id>'"):
        get_code(kb, "codes/ec5/2004")


def test_an_unknown_family_lists_the_families_there_are(kb):
    with pytest.raises(DesignCheckError, match="unknown family materials/unobtainium"):
        get_material(kb, "materials/unobtainium/X1")


def test_a_missing_code_file_is_a_missing_entry(kb):
    with pytest.raises(DesignCheckError, match="'codes/nds' not found"):
        get_code(kb, "codes/nds")


# -- malformed entries --------------------------------------------------------


def test_a_missing_property_names_the_entry_and_the_field(tmp_path):
    _overlay(
        tmp_path,
        "materials/timber.toml",
        '["C24"]\nsource = "test"\ngrade = "C24"\n"rho_k[kg/m^3]" = 350.0\n',
    )
    kb = load_kb([tmp_path])

    with pytest.raises(DesignCheckError) as error:
        get_material(kb, "materials/timber/C24")
    assert "KB entry 'materials/timber/C24'" in str(error.value)
    assert "missing field(s) 'f_mk', 'f_c0k', 'E_mean'" in str(error.value)


def test_a_property_with_no_unit_is_refused_by_name(tmp_path):
    _overlay(
        tmp_path,
        "materials/timber.toml",
        '["C24"]\nsource = "t"\ngrade = "C24"\nrho_k = 350.0\n'
        '"f_mk[MPa]" = 24.0\n"f_c0k[MPa]" = 21.0\n"E_mean[MPa]" = 11000.0\n',
    )
    kb = load_kb([tmp_path])

    with pytest.raises(DesignCheckError, match="field 'rho_k' declares no unit"):
        get_material(kb, "materials/timber/C24")


def test_a_property_in_the_wrong_dimension_cannot_load_silently(tmp_path):
    # The tripwire the ADR asks for: a density shipped as a stress dies at load.
    _overlay(
        tmp_path,
        "materials/timber.toml",
        '["C24"]\nsource = "t"\ngrade = "C24"\n"rho_k[MPa]" = 350.0\n'
        '"f_mk[MPa]" = 24.0\n"f_c0k[MPa]" = 21.0\n"E_mean[MPa]" = 11000.0\n',
    )
    kb = load_kb([tmp_path])

    with pytest.raises(DesignCheckError, match="expected density .* got stress"):
        get_material(kb, "materials/timber/C24")


def test_an_unknown_field_is_a_typo_worth_reporting(tmp_path):
    _overlay(
        tmp_path,
        "materials/timber.toml",
        '["C24"]\nsource = "t"\ngrade = "C24"\n"rho_kk[kg/m^3]" = 350.0\n'
        '"f_mk[MPa]" = 24.0\n"f_c0k[MPa]" = 21.0\n"E_mean[MPa]" = 11000.0\n',
    )
    kb = load_kb([tmp_path])

    with pytest.raises(DesignCheckError, match="unknown numeric field 'rho_kk' for a Timber"):
        get_material(kb, "materials/timber/C24")


def test_a_missing_provenance_string_is_refused(tmp_path):
    _overlay(
        tmp_path,
        "materials/timber.toml",
        '["C24"]\ngrade = "C24"\n"rho_k[kg/m^3]" = 350.0\n'
        '"f_mk[MPa]" = 24.0\n"f_c0k[MPa]" = 21.0\n"E_mean[MPa]" = 11000.0\n',
    )
    kb = load_kb([tmp_path])

    with pytest.raises(DesignCheckError, match="missing field\\(s\\) 'source'"):
        get_material(kb, "materials/timber/C24")


def test_invalid_toml_names_the_file(tmp_path):
    _overlay(tmp_path, "materials/timber.toml", '["C24"\nsource = "t"\n')
    kb = load_kb([tmp_path])

    with pytest.raises(DesignCheckError, match="not valid TOML"):
        get_material(kb, "materials/timber/C24")


def test_a_bad_clause_names_the_code_entry(tmp_path):
    _overlay(
        tmp_path,
        "codes/ec5.toml",
        'name = "test"\nedition = "1"\nsource = "s"\n'
        "[gamma_M]\nconnections = 1.3\n[k_mod]\n\"2/medium\" = 0.8\n"
        '[[clauses]]\nid = "x"\ncitation = "c"\ntitle = "t"\nkind = "formula"\n',
    )
    kb = load_kb([tmp_path])

    with pytest.raises(DesignCheckError, match="needs both 'formula' and 'defines'") as error:
        get_code(kb, "codes/ec5")
    assert "KB entry 'codes/ec5'" in str(error.value)


def test_a_bad_k_mod_key_states_the_shape(tmp_path):
    _overlay(
        tmp_path,
        "codes/ec5.toml",
        'name = "t"\nedition = "1"\nsource = "s"\n'
        "[gamma_M]\nconnections = 1.3\n[k_mod]\nmedium = 0.8\n",
    )
    kb = load_kb([tmp_path])

    with pytest.raises(DesignCheckError, match="must read '<service class>/<load duration>'"):
        get_code(kb, "codes/ec5")


# -- roots and overlays -------------------------------------------------------


def test_a_root_without_a_manifest_cannot_pin_anything(tmp_path):
    (tmp_path / "materials").mkdir()
    with pytest.raises(DesignCheckError, match="has no kb.toml"):
        load_kb([tmp_path])


def test_a_root_that_does_not_exist_is_refused(tmp_path):
    with pytest.raises(DesignCheckError, match="does not exist"):
        load_kb([tmp_path / "nowhere"])


def test_a_manifest_without_a_version_is_refused(tmp_path):
    (tmp_path / "kb.toml").write_text('name = "no version"\n', encoding="utf-8")
    with pytest.raises(DesignCheckError, match="'version' must be a non-empty string"):
        load_kb([tmp_path])


def test_an_overlay_wins_by_address_and_carries_its_own_version(tmp_path):
    _overlay(
        tmp_path,
        "materials/timber.toml",
        '["C24"]\nsource = "our lab report 2026-03"\ngrade = "C24"\n'
        '"rho_k[kg/m^3]" = 365.0\n"f_mk[MPa]" = 24.0\n"f_c0k[MPa]" = 21.0\n'
        '"E_mean[MPa]" = 11000.0\n',
    )
    kb = load_kb([tmp_path])

    timber = get_material(kb, "materials/timber/C24")

    assert timber.rho_k == 365.0
    assert timber.ref.version == "9.9-test"
    assert timber.ref.source == "our lab report 2026-03"
    # Addresses the overlay does not hold still fall through to the shipped KB.
    assert get_fastener(kb, "fasteners/screw/csk-6.0x120").d == 6.0
    assert kb.pins == ("kb 9.9-test", "kb 2024.1")


def test_a_knowledge_base_needs_at_least_one_root():
    with pytest.raises(DesignCheckError, match="needs at least one root"):
        KnowledgeBase(roots=())
