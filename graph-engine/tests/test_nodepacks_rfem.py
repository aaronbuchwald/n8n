"""Unit tests for the ``rfem`` node pack — reading an export, choosing a row.

The interesting assertion here is not "it finds a big number": it is that
:func:`rfem.governing_force` **filters to the ``Extremum`` rows first**. On the
shipped export the filtered and unfiltered scans happen to agree, so the filter
is pinned on a synthetic table where they deliberately disagree.

Run with:  uv run --extra dev --extra sym python -m pytest -q
"""

from __future__ import annotations

import pytest

from engine import UserError
from rfem import FORCE_COLUMNS, governing_force, read_extrema
from xlsx_to_csv import CSV

# The row this export governs on, and its number, to full precision.
GOVERNING_REF = "RFEM 10103/1578 @ 6.15 m · LK67"
VZ_SIGNED = -297.175507
VZ_MAGNITUDE = 297.175507

COLUMNS = ["Stab", "Knoten", "x_m", "Extremum", "N_kN", "Vy_kN", "Vz_kN", "Lastfall"]


def _table(rows: list[list]) -> dict:
    return {"columns": list(COLUMNS), "rows": rows, "source": "synthetic.csv"}


# -- read_extrema -------------------------------------------------------------


def test_read_extrema_returns_the_table_packs_shape():
    table = read_extrema(str(CSV))

    assert set(table) == {"columns", "rows", "source"}
    assert table["columns"] == COLUMNS
    assert len(table["rows"]) == 1104
    assert all(len(row) == len(COLUMNS) for row in table["rows"])


def test_read_extrema_parses_cells_the_way_the_table_pack_does():
    """Numbers as floats, load cases as strings — and every digit kept."""
    row = read_extrema(str(CSV))["rows"][0]

    assert row == [10101.0, 1516.0, 0.0, "N", 0.256562, -0.002222, 74.526283, "LK71"]
    positions = {r[2] for r in read_extrema(str(CSV))["rows"]}
    assert 6.1500000000005 in positions


def test_read_extrema_carries_the_file_name_not_the_machine_path():
    """Provenance that survives being written into an artifact."""
    assert read_extrema(str(CSV))["source"] == "export.csv"


def test_read_extrema_refuses_a_csv_that_is_not_an_rfem_export(tmp_path):
    other = tmp_path / "sales.csv"
    other.write_text("region,amount\nnorth,10\n", encoding="utf-8")

    with pytest.raises(UserError) as caught:
        read_extrema(str(other))
    assert "not an RFEM member extrema export" in str(caught.value)
    assert "'Stab'" in str(caught.value) and "'region'" in str(caught.value)


# -- governing_force on the real export ---------------------------------------


def test_the_governing_row_is_the_largest_absolute_vz_extremum():
    record = governing_force(read_extrema(str(CSV)))

    assert record["member"] == 10103.0
    assert record["node"] == 1578.0
    assert record["position"] == 6.1500000000005
    assert record["load_case"] == "LK67"
    assert record["component"] == "Vz"
    assert record["signed"] == VZ_SIGNED


def test_the_record_is_the_envelope_the_sheet_pack_unwraps():
    """`{value, unit, ref}` — the magnitude, in kN, citing its source row."""
    record = governing_force(read_extrema(str(CSV)))

    assert record["value"] == VZ_MAGNITUDE  # |Vz|, not the signed reaction
    assert record["unit"] == "kN"
    assert record["ref"] == GOVERNING_REF
    # The richer provenance rides along; the unwrapper ignores what it does not
    # know, by design.
    assert record["source"] == "export.csv"
    assert set(record) == {
        "value", "unit", "ref", "component", "signed",
        "member", "node", "position", "load_case", "source",
    }


def test_the_ref_names_the_row_a_human_would_look_up():
    """Member/node/position/load case, with the position read as the sheet does."""
    record = governing_force(read_extrema(str(CSV)))

    assert record["ref"] == "RFEM 10103/1578 @ 6.15 m · LK67"
    assert "10103.0" not in record["ref"]  # not the float repr of a member number


def test_a_different_component_governs_a_different_row():
    table = read_extrema(str(CSV))

    axial = governing_force(table, component="N")
    assert axial["component"] == "N" and axial["unit"] == "kN"
    assert axial["ref"] != GOVERNING_REF
    assert axial["value"] == abs(axial["signed"])


def test_the_filter_actually_filters():
    """Only `Extremum == component` rows are candidates."""
    table = read_extrema(str(CSV))
    vz_rows = [r for r in table["rows"] if r[3] == "Vz"]

    assert len(vz_rows) == 184 < len(table["rows"])
    record = governing_force(table)
    assert [record["member"], record["node"], record["position"]] in [
        [r[0], r[1], r[2]] for r in vz_rows
    ]


# -- the filter, pinned where it changes the answer ----------------------------


def test_the_filter_changes_the_answer_when_the_data_disagrees():
    """A table whose biggest |Vz| sits on a row that is NOT a Vz extremum.

    On the shipped export both scans return the same number — a coincidence of
    that file. Here they cannot: the largest |Vz| in the whole table belongs to
    a `My` extremum row (the Vz merely *accompanying* a moment extremum), so a
    scan that skipped the filter would pick it.
    """
    table = _table([
        [1.0, 10.0, 0.0, "Vz", 0.0, 0.0, -120.0, "LK1"],
        [1.0, 10.0, 0.0, "My", 0.0, 0.0, -900.0, "LK2"],  # bigger, but not a Vz extremum
        [2.0, 20.0, 1.5, "Vz", 0.0, 0.0, 80.0, "LK3"],
    ])

    record = governing_force(table)
    assert record["signed"] == -120.0
    assert record["load_case"] == "LK1"
    assert record["ref"] == "RFEM 1/10 @ 0 m · LK1"

    # The unfiltered scan — what the node deliberately does NOT do.
    unfiltered = max(table["rows"], key=lambda r: abs(r[6]))
    assert unfiltered[7] == "LK2" and record["load_case"] != unfiltered[7]


def test_the_largest_magnitude_wins_regardless_of_sign():
    table = _table([
        [1.0, 10.0, 0.0, "Vz", 0.0, 0.0, 50.0, "LK1"],
        [2.0, 20.0, 0.0, "Vz", 0.0, 0.0, -70.0, "LK2"],
    ])

    record = governing_force(table)
    assert record["signed"] == -70.0 and record["value"] == 70.0


# -- refusals -----------------------------------------------------------------


def test_a_component_with_no_force_column_is_refused():
    """The export reports MT/My/Mz extrema but carries no moment columns."""
    with pytest.raises(UserError) as caught:
        governing_force(_table([[1.0, 10.0, 0.0, "My", 0.0, 0.0, 1.0, "LK1"]]), component="My")
    message = str(caught.value)
    assert "unknown component 'My'" in message
    assert "no moment columns" in message
    assert set(FORCE_COLUMNS) == {"N", "Vy", "Vz"}


def test_a_component_no_row_reports_is_refused_with_what_is_there():
    with pytest.raises(UserError) as caught:
        governing_force(_table([[1.0, 10.0, 0.0, "N", 1.0, 0.0, 2.0, "LK1"]]), component="Vy")
    assert "no row has Extremum == 'Vy'" in str(caught.value)
    assert "the table reports: N" in str(caught.value)


def test_something_that_is_not_a_table_is_refused():
    with pytest.raises(UserError) as caught:
        governing_force([1, 2, 3])
    assert "wire it from rfem.read_extrema" in str(caught.value)


def test_a_table_without_the_force_column_is_refused():
    with pytest.raises(UserError) as caught:
        governing_force({"columns": ["Extremum"], "rows": [["Vz"]]})
    assert "'Vz_kN'" in str(caught.value)


def test_a_non_numeric_force_cell_is_refused():
    with pytest.raises(UserError) as caught:
        governing_force(_table([[1.0, 10.0, 0.0, "Vz", 0.0, 0.0, "n/a", "LK1"]]))
    assert "is not a force" in str(caught.value)
