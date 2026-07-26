"""The committed ``export.csv`` reproduces the ``.xlsx`` cell for cell.

``examples/beam_bearing_pressure_rfem/`` ships the RFEM workbook untouched as
the provenance record and a CSV converted from it by ``xlsx_to_csv.py``. The
CSV is what the graph reads, so the thing worth asserting is that converting is
not *editing*: every value in the CSV is the value in the workbook, as stored —
no rounding, no reordering, no reformatting.

Run with:  uv run --extra dev --extra sym python -m pytest -q
"""

from __future__ import annotations

import csv

from xlsx_to_csv import CSV, HEADER, SOURCE_HEADER, XLSX, data_rows, sheet_rows

# The shape the export is known to have — asserted so a silently truncated or
# re-exported workbook cannot pass as the same file.
DATA_ROWS = 1104
MEMBERS = 46
NODES = 58
BLANK_SEPARATOR_ROWS = 45


def _csv_rows() -> list[list[str]]:
    with open(CSV, newline="", encoding="utf-8") as handle:
        return list(csv.reader(handle))


def test_the_workbook_is_committed_beside_the_csv():
    """The provenance record itself, not just what was made from it."""
    assert XLSX.is_file() and XLSX.suffix == ".xlsx"
    assert CSV.is_file()


def test_the_csv_round_trips_against_the_xlsx_cell_for_cell():
    """The whole point: the CSV is the workbook's cells, verbatim."""
    rows = _csv_rows()
    assert rows[0] == HEADER
    assert rows[1:] == data_rows(XLSX)  # every cell, as stored in the workbook


def test_only_the_header_and_the_blank_rows_differ_from_the_workbook():
    """The two permitted changes, and nothing else.

    Flattening the two-row German header into one, and dropping the blank rows
    the export puts between member blocks. Everything between those two edits is
    identical, which is what the reconstruction below proves.
    """
    workbook = sheet_rows(XLSX)
    assert workbook[:2] == SOURCE_HEADER  # the two-row header, flattened to HEADER
    blanks = [row for row in workbook if all(cell == "" for cell in row)]
    assert len(blanks) == BLANK_SEPARATOR_ROWS

    # Rebuild the CSV's data section from the workbook by applying *only* those
    # two edits — it must be what is on disk.
    rebuilt = [row for row in workbook[2:] if any(cell != "" for cell in row)]
    assert _csv_rows()[1:] == rebuilt
    assert len(workbook) == 2 + BLANK_SEPARATOR_ROWS + DATA_ROWS


def test_numbers_keep_every_digit_the_workbook_stored():
    """No rounding on the way out — the governing row's `x` is the proof."""
    rows = _csv_rows()[1:]
    positions = {row[2] for row in rows}
    assert "6.1500000000005" in positions  # not "6.15"
    assert "0.600000000000165" in positions
    assert ["10103", "1578", "6.1500000000005", "Vz", "0.000526", "0.003266",
            "-297.175507", "LK67"] in rows


def test_the_export_has_the_shape_the_example_documents():
    rows = _csv_rows()[1:]
    assert len(rows) == DATA_ROWS
    assert len({row[0] for row in rows}) == MEMBERS
    assert len({row[1] for row in rows}) == NODES
    # 46 members × 2 node locations × 6 extremum types × max/min = 1104.
    assert MEMBERS * 2 * 6 * 2 == DATA_ROWS
    assert sorted({row[3] for row in rows}) == ["MT", "My", "Mz", "N", "Vy", "Vz"]


def test_the_unnamed_fourth_column_is_the_one_the_converter_names():
    """The workbook leaves column D blank in BOTH header rows (hence `Extremum`)."""
    assert SOURCE_HEADER[0][3] == "" and SOURCE_HEADER[1][3] == ""
    assert HEADER[3] == "Extremum"
    # …and only force columns exist, despite the moment extremum rows above.
    assert HEADER[4:7] == ["N_kN", "Vy_kN", "Vz_kN"]
    assert not any(h.startswith(("MT", "My", "Mz")) for h in HEADER)


def test_rerunning_the_converter_reproduces_the_committed_csv(tmp_path):
    """It is a re-runnable script, not a one-off — so the CSV is reproducible."""
    from xlsx_to_csv import convert

    written = convert(XLSX, tmp_path / "again.csv")
    assert written.read_text(encoding="utf-8") == CSV.read_text(encoding="utf-8")
