"""Convert the committed RFEM export workbook to the CSV the demo reads.

``260726_GZT_DesignLoadsMembers_Start_End.xlsx`` is an RFEM "design loads,
members, start/end" extremum export, committed **untouched** beside this script
as the provenance record. ``export.csv`` is what the graph actually reads, and
this script is how it is produced — a committed, re-runnable step, so the CSV's
provenance is reproducible rather than a one-off somebody did by hand::

    uv run python examples/beam_bearing_pressure_rfem/xlsx_to_csv.py

**Converting is not editing.** Every value is copied cell for cell, as the
stored string: no rounding, no reordering, no reformatting of numbers. The
workbook stores ``x`` as ``6.1500000000005``, so the CSV says
``6.1500000000005`` — the extra digits are the file's, not a defect to tidy
away, and rounding them here would make the CSV disagree with the export it
claims to reproduce. ``tests/test_rfem_export_csv.py`` asserts the round-trip
cell for cell against the ``.xlsx``.

Exactly two changes are permitted, and both are shape, not content:

1. **The two-row German header becomes one row.** The workbook's header spans
   rows 1-2 (``Stab`` / ``Nr.``, ``Stelle`` / ``x [m]``, ``Kräfte [kN]`` over
   ``N`` / ``Vy`` / ``Vz``, …), which no CSV reader can address. It is replaced
   by the single flat header :data:`HEADER`.
2. **The 45 blank separator rows are dropped.** The export puts an empty row
   between member blocks; they carry no data and would only be noise rows.

**The fourth column has no header at all** — neither header row names it. It
carries the extremum type the row reports (``N``, ``Vy``, ``Vz``, ``MT``,
``My``, ``Mz``), which is exactly the column ``rfem.governing_force`` filters
on, so it has to be named: ``Extremum``. Note also that only ``N``, ``Vy`` and
``Vz`` *force* columns exist in the export — there are no moment columns,
despite the ``MT``/``My``/``Mz`` extremum rows.

Pure standard library on purpose (``zipfile`` + ``xml.etree``): an ``.xlsx`` is
a zip of XML, and reading eight columns out of one sheet does not justify a
dependency the rest of the engine does not have.
"""

from __future__ import annotations

import csv
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
XLSX = HERE / "260726_GZT_DesignLoadsMembers_Start_End.xlsx"
CSV = HERE / "export.csv"

# The flat header. Column 4 is named here and nowhere else — the workbook
# leaves it blank in both header rows (see the module docstring).
HEADER = ["Stab", "Knoten", "x_m", "Extremum", "N_kN", "Vy_kN", "Vz_kN", "Lastfall"]

# The workbook's own two header rows, asserted before anything is converted: if
# the export's layout ever changes, this script must stop rather than quietly
# emit a CSV whose columns mean something else.
SOURCE_HEADER = [
    ["Stab\nNr.", "Knoten", "Stelle", "", "Kräfte [kN]", "", "", ""],
    ["", "Nr.", "x [m]", "", "N", "Vy", "Vz", "Zugehörige Belastung"],
]

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_COLUMNS = "ABCDEFGH"


def _column_letters(ref: str) -> str:
    """``"C12"`` -> ``"C"`` — the column part of an A1-style cell reference."""
    return ref.rstrip("0123456789")


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    """The workbook's shared-string table, one joined string per ``<si>``."""
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(t.text or "" for t in si.iter(f"{_NS}t"))
        for si in root.findall(f"{_NS}si")
    ]


def sheet_rows(xlsx: Path | str = XLSX) -> list[list[str]]:
    """Every row of the workbook's single sheet, as stored strings.

    Eight columns (A-H) per row, blank cells as ``""``. Numbers are handed back
    as the **stored text** of the ``<v>`` element — the canonical value in the
    file — so nothing is parsed, rounded, or re-formatted on the way out.
    Shared-string cells (``t="s"``) are resolved through the string table.
    """
    with zipfile.ZipFile(xlsx) as archive:
        strings = _shared_strings(archive)
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))

    rows: list[list[str]] = []
    for row in sheet.find(f"{_NS}sheetData").findall(f"{_NS}row"):
        cells = {}
        for cell in row.findall(f"{_NS}c"):
            value = cell.find(f"{_NS}v")
            text = "" if value is None or value.text is None else value.text
            if text and cell.get("t") == "s":
                text = strings[int(text)]
            cells[_column_letters(cell.get("r", ""))] = text
        rows.append([cells.get(letter, "") for letter in _COLUMNS])
    return rows


def data_rows(xlsx: Path | str = XLSX) -> list[list[str]]:
    """The export's data rows: header rows verified and dropped, blanks dropped.

    Raises :class:`ValueError` when the workbook's own header is not the one
    this converter was written against — a layout change must be loud.
    """
    rows = sheet_rows(xlsx)
    if rows[:2] != SOURCE_HEADER:
        raise ValueError(
            f"unexpected header in {xlsx}: {rows[:2]!r}; expected {SOURCE_HEADER!r}"
        )
    return [row for row in rows[2:] if any(cell != "" for cell in row)]


def convert(xlsx: Path | str = XLSX, destination: Path | str = CSV) -> Path:
    """Write ``destination`` from ``xlsx`` and return the path written."""
    rows = data_rows(xlsx)
    destination = Path(destination)
    with open(destination, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(HEADER)
        writer.writerows(rows)
    return destination


def main() -> None:
    rows = data_rows()
    written = convert()
    members = len({row[0] for row in rows})
    nodes = len({row[1] for row in rows})
    print(f"{written}: {len(rows)} data rows · {members} members · {nodes} nodes")


if __name__ == "__main__":
    sys.exit(main())
