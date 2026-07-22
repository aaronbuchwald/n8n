"""Table pack example — filter -> derive -> aggregate over a mock sales CSV.

    read_table ──> apply_recipe ──> table_summary  (HTML card)

``sales.csv`` is a small, generic, non-domain fixture (``region, amount,
qty``). The recipe (an ordinary dict literal, per ADR 0005 Part C):

1. ``filter``    keep rows where ``qty > 1``
2. ``derive``    add ``total_amount = amount * qty``
3. ``aggregate`` group by ``region``; per group: sum of ``total_amount``, mean
   of ``amount``, count of rows

Pure standard library. Run directly to execute the graph + print the table,
the HTML card, and the ``to_python`` export::

    uv run python examples/table/report.py
"""

from __future__ import annotations

from pathlib import Path

from engine import main
from table import apply_recipe, read_table, table_summary

HERE = Path(__file__).resolve().parent
CSV_PATH = HERE / "sales.csv"

TITLE = "Sales by region"

RECIPE = {
    "version": 1,
    "ops": [
        {"op": "filter", "expr": "qty > 1"},
        {"op": "derive", "name": "total_amount", "expr": "amount * qty"},
        {
            "op": "aggregate",
            "group_by": ["region"],
            "aggs": [
                {"col": "total_amount", "fn": "sum", "as": "total_amount"},
                {"col": "amount", "fn": "mean", "as": "avg_amount"},
                {"col": "qty", "fn": "count", "as": "n"},
            ],
        },
    ],
}

# Node types this example defines (for registries / snapshots).
NODES = [read_table, apply_recipe, table_summary]


@main
def sales_report(path: str = "sales.csv") -> str:
    """Read the CSV, filter/derive/aggregate it, and render the result card."""
    raw = read_table(path)
    summarised = apply_recipe(table=raw, recipe=RECIPE)
    return table_summary(summarised, title=TITLE)


def build_graph(csv_path: Path | str = CSV_PATH):
    """Trace the composite into a :class:`~engine.Graph` (absolute path so it
    runs from any working directory)."""
    return sales_report.to_graph(path=str(csv_path))


def main_cli() -> None:
    from engine import run, to_python

    graph = build_graph()
    result = run(graph)

    table = result.value("apply_recipe")
    print("Aggregated table:")
    print(table)

    html_card = result.value(graph.output["node"], graph.output["socket"])
    print("\nHTML card:")
    print(html_card)

    written = HERE / "result.html"
    written.write_text(html_card, encoding="utf-8")
    print(f"\nwrote {written}")

    print("\n----- to_python(graph) -----")
    print(to_python(graph))


if __name__ == "__main__":
    main_cli()
