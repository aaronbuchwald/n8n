"""Readings example — the calc + sources node packs wired into a graph.

    source ──> average ─┐
           └─> median ──┴──> render_summary  (HTML card)

The leaves come from two installable packs: :mod:`sources` (``read_csv`` /
``mock_api``) and :mod:`calc` (``average`` / ``median`` / ``render_summary``).
Two composites share the *same downstream graph* and differ by a single node —
the data source:

* ``readings_report``      reads the values from ``readings.csv``.
* ``readings_report_api``  gets the same values from the in-process ``mock_api``.

Swapping ``read_csv`` for ``mock_api`` changes exactly one node's type and leaves
the output identical — that is the CSV↔API source swap. Editing the numbers in
``readings.csv`` and re-running changes the result, demonstrating "read from CSV
as input and re-run".

Pure standard library. Run directly to execute both variants + write the card::

    uv run python examples/readings/readings.py
"""

from __future__ import annotations

from pathlib import Path

from calc import average, median, render_summary
from engine import main
from sources import mock_api, read_csv

HERE = Path(__file__).resolve().parent
CSV_PATH = HERE / "readings.csv"

TITLE = "Readings summary"

# Node types both composites define (for registries / snapshots).
NODES = [read_csv, mock_api, average, median, render_summary]


# -- the graph, as ordinary Python -----------------------------------------


@main
def readings_report(path: str = "readings.csv") -> str:
    """Read the CSV, reduce it two ways, and render the result card."""
    values = read_csv(path)
    return render_summary(TITLE, average(values), median(values))


@main
def readings_report_api(dataset: str = "readings") -> str:
    """Same downstream graph as :func:`readings_report`, sourced from the mock API."""
    values = mock_api(dataset)
    return render_summary(TITLE, average(values), median(values))


def build_csv_graph(csv_path: Path | str = CSV_PATH):
    """Trace the CSV-sourced composite (absolute path so it runs anywhere)."""
    return readings_report.to_graph(path=str(csv_path))


def build_api_graph(dataset: str = "readings"):
    """Trace the mock-API-sourced composite (same downstream graph)."""
    return readings_report_api.to_graph(dataset=dataset)


def main_cli() -> None:
    from engine import run, to_python

    csv_graph = build_csv_graph()
    api_graph = build_api_graph()

    out = csv_graph.output
    csv_html = run(csv_graph).value(out["node"], out["socket"])
    api_out = api_graph.output
    api_html = run(api_graph).value(api_out["node"], api_out["socket"])

    print("CSV-sourced card:")
    print(csv_html)
    print(f"\nCSV == mock-API output: {csv_html == api_html}")

    written = HERE / "result.html"
    written.write_text(csv_html, encoding="utf-8")
    print(f"\nwrote {written}")

    print("\n----- to_python(csv_graph) -----")
    print(to_python(csv_graph))


if __name__ == "__main__":
    main_cli()
