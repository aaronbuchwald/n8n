"""T9: unit slips die at the file boundary, and the governing case is recorded."""

from __future__ import annotations

from pathlib import Path

import pytest

from designcheck import (
    ActionRow,
    DesignCheckError,
    governing_action,
    parse_fem_actions,
    read_fem_actions,
)

FEM_CSV = Path(__file__).parent / "data" / "fem_forces.csv"

HEADER = "element,case,N[kN],V_y[kN],V_z[kN],M_y[kNm],M_z[kNm]"
BODY = "conn-01,ULS-1,1.2,0.1,3.1,0.0,0.0\nconn-01,ULS-2,1.4,0.2,4.2,0.0,0.0\n"


def test_the_demo_file_reads_as_three_rows():
    rows = read_fem_actions(FEM_CSV)

    assert [row.case for row in rows] == ["ULS-1", "ULS-2", "ULS-3"]
    assert [row.V_z for row in rows] == [3.1, 4.2, 2.8]
    assert rows[0].source == "fem_forces.csv"


def test_a_column_in_another_unit_of_the_same_dimension_converts():
    text = (
        "element,case,N[kN],V_y[kN],V_z[N],M_y[kNm],M_z[kNm]\n"
        "conn-01,ULS-2,1.4,0.2,4200,0.0,0.0\n"
    )

    (row,) = parse_fem_actions(text, source="alt.csv")

    assert row.V_z == pytest.approx(4.2)


def test_a_column_in_the_wrong_dimension_dies_at_ingest():
    text = HEADER.replace("V_z[kN]", "V_z[mm]") + "\n" + BODY

    with pytest.raises(DesignCheckError, match="column 'V_z': expected force"):
        parse_fem_actions(text, source="fem.csv")


def test_a_column_with_no_unit_states_the_one_it_wanted():
    text = HEADER.replace("V_z[kN]", "V_z") + "\n" + BODY

    with pytest.raises(DesignCheckError, match="write 'V_z\\[kN\\]'"):
        parse_fem_actions(text, source="fem.csv")


def test_a_missing_column_names_it():
    text = HEADER.replace(",M_z[kNm]", "") + "\n" + "conn-01,ULS-1,1.2,0.1,3.1,0.0\n"

    with pytest.raises(DesignCheckError, match="missing column\\(s\\) 'M_z'"):
        parse_fem_actions(text, source="fem.csv")


def test_a_non_numeric_cell_names_the_line_and_the_column():
    text = HEADER + "\nconn-01,ULS-1,1.2,0.1,heavy,0.0,0.0\n"

    with pytest.raises(DesignCheckError, match="fem.csv line 2: column 'V_z' is not a number"):
        parse_fem_actions(text, source="fem.csv")


def test_a_short_row_is_refused():
    text = HEADER + "\nconn-01,ULS-1,1.2\n"

    with pytest.raises(DesignCheckError, match="line 2: expected 7 fields, got 3"):
        parse_fem_actions(text, source="fem.csv")


def test_a_duplicate_column_is_refused():
    text = HEADER + ",V_z[kN]\n" + "conn-01,ULS-1,1.2,0.1,3.1,0.0,0.0,3.1\n"

    with pytest.raises(DesignCheckError, match="duplicate column 'V_z'"):
        parse_fem_actions(text, source="fem.csv")


def test_a_header_only_file_has_nothing_to_check():
    with pytest.raises(DesignCheckError, match="no action rows after the header"):
        parse_fem_actions(HEADER + "\n", source="fem.csv")


def test_an_empty_file_is_refused():
    with pytest.raises(DesignCheckError, match="the file is empty"):
        parse_fem_actions("", source="fem.csv")


def test_an_unreadable_path_names_the_file(tmp_path):
    with pytest.raises(DesignCheckError, match="cannot read FEM actions"):
        read_fem_actions(tmp_path / "absent.csv")


def test_blank_lines_are_skipped():
    rows = parse_fem_actions(HEADER + "\n\n" + BODY + "\n", source="fem.csv")

    assert len(rows) == 2


# -- reduction ----------------------------------------------------------------


def test_the_governing_action_records_which_case_governed(demand):
    assert (demand.value, demand.case, demand.unit) == (4.2, "ULS-2", "kN")
    assert demand.source == "fem_forces.csv"


def test_the_governing_action_is_a_magnitude():
    rows = parse_fem_actions(
        HEADER + "\nconn-01,ULS-4,0,0,-9.5,0,0\nconn-01,ULS-5,0,0,4.2,0,0\n", source="f.csv"
    )

    reduced = governing_action(rows, element="conn-01", component="V_z")

    assert reduced.value == pytest.approx(9.5)
    assert reduced.case == "ULS-4"


def test_other_elements_do_not_leak_into_the_reduction():
    rows = parse_fem_actions(
        HEADER + "\nconn-01,ULS-1,0,0,4.2,0,0\nconn-02,ULS-1,0,0,99.0,0,0\n", source="f.csv"
    )

    assert governing_action(rows, element="conn-01", component="V_z").value == 4.2


def test_an_element_with_no_rows_is_named():
    rows = parse_fem_actions(HEADER + "\n" + BODY, source="f.csv")

    with pytest.raises(DesignCheckError, match="no FEM rows for element 'conn-77'"):
        governing_action(rows, element="conn-77", component="V_z")


def test_an_unknown_component_lists_the_ones_there_are():
    rows = parse_fem_actions(HEADER + "\n" + BODY, source="f.csv")

    with pytest.raises(DesignCheckError, match="unknown action component 'V_x'"):
        governing_action(rows, element="conn-01", component="V_x")


def test_a_row_without_provenance_still_yields_a_traceable_demand():
    rows = (ActionRow(element="conn-01", case="ULS-1", N=0, V_y=0, V_z=4.2, M_y=0, M_z=0),)

    assert governing_action(rows, "conn-01", "V_z").source == "(unknown source)"
