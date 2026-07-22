"""Widget showcase — every editable widget kind on one canvas (ADR 0005).

This is the graph the server serves as ``--demo``. Where the *minimal* example
exists to be the smallest end-to-end graph, this one exists to make the
node-declared editing widgets **visible**: opening the app shows a math editor,
a table-recipe editor, and plain text/number editors, all live.

Two independent chains meet at one output card:

    read_table ─> apply_recipe ─> table_summary ─┐
                                                 ├─> dashboard  (HTML card)
    parse_expr ─> solve_for ─> pick ─> describe ─┤
    latex_to_mathml ─> render_math_card ─────────┘

The editable widgets it surfaces (all round-trip through the ADR 0004 composite
as ordinary literals):

* ``parse_expr.text``          — the **math** widget (SymPy string + KaTeX preview)
* ``apply_recipe.recipe``      — the **table-recipe** widget (op-list grid editor)
* ``read_table.path`` / titles / labels / ``symbol`` — **text** widgets
* ``pick.index``               — a **number** widget

Simple, generic mock math only — a quadratic's roots and a filter/derive/
aggregate over a tiny ``region,amount,qty`` CSV. No domain content, no CDN
(the sym card emits native MathML; the table card is inline-CSS HTML).

Run directly (the ``sym`` extra provides SymPy et al.)::

    uv run --extra sym python examples/showcase/showcase.py
"""

from __future__ import annotations

import html
from pathlib import Path

from engine import main, node
from sym import (
    describe,
    join_text,
    latex_to_mathml,
    parse_expr,
    pick,
    render_math_card,
    solve_for,
)
from table import apply_recipe, read_table, table_summary

HERE = Path(__file__).resolve().parent
CSV_PATH = HERE / "showcase.csv"


# -- a local composing node (its own @node, so it is source-editable too) ------


@node
def dashboard(table_html: str = "", math_html: str = "", title: str = "Widget showcase") -> str:
    """Compose the table card and the math card into one self-contained page.

    Both inputs are already-rendered HTML fragments (inline CSS, no scripts);
    this only frames them under a shared heading, so the whole graph still
    returns a single HTML string with no external assets.
    """
    return (
        '<div style="font-family:system-ui,-apple-system,sans-serif;'
        'display:flex;flex-direction:column;gap:1rem;padding:1rem;max-width:44rem">'
        f'<h1 style="font-size:1.15rem;margin:0">{html.escape(title)}</h1>'
        '<div style="display:flex;flex-wrap:wrap;gap:1rem;align-items:flex-start">'
        f"{table_html}{math_html}"
        "</div></div>"
    )


# -- the graph, as ordinary Python (ADR 0004 straight-line form) ---------------
# One single-assignment call per node; every variable name is that node's id on
# the canvas. Literal arguments (the recipe dict, the SymPy string, titles) are
# the editable widget values; Name arguments are wiring edges.


@main
def showcase_report() -> str:
    """Filter/aggregate a tiny CSV and solve a quadratic — one showcase card."""
    # Table chain: read -> recipe (filter/derive/aggregate) -> HTML card.
    raw = read_table(path="showcase.csv")
    sales = apply_recipe(
        table=raw,
        recipe={
            "version": 1,
            "ops": [
                {"op": "filter", "expr": "qty > 1"},
                {"op": "derive", "name": "total", "expr": "amount * qty"},
                {
                    "op": "aggregate",
                    "group_by": ["region"],
                    "aggs": [
                        {"col": "total", "fn": "sum", "as": "total"},
                        {"col": "amount", "fn": "mean", "as": "avg_amount"},
                        {"col": "qty", "fn": "count", "as": "n"},
                    ],
                },
            ],
        },
    )
    table_card = table_summary(sales, title="Sales by region")

    # Symbolic chain: parse -> solve -> pick a root -> describe -> math card.
    expr = parse_expr(text="x**2 - 5*x + 6")
    roots = solve_for(expr, symbol="x")
    first = pick(roots, index=0)
    roots_note = describe(roots, label="roots")
    first_note = describe(first, label="first root")
    caption = join_text(roots_note, first_note)
    mathml = latex_to_mathml(latex="x^{2} - 5 x + 6 = 0")
    math_card = render_math_card(title="Quadratic roots", mathml=mathml, caption=caption)

    # Compose both into one output card.
    report = dashboard(table_html=table_card, math_html=math_card, title="Widget showcase")
    return report


# Node types this example defines / uses (for registries / snapshots).
NODES = [read_table, apply_recipe, table_summary, dashboard]


def build_graph(csv_path: Path | str = CSV_PATH):
    """Trace the composite into a Graph, with an absolute CSV path so it runs
    from any working directory."""
    graph = showcase_report.to_graph()
    for graph_node in graph.nodes:
        if graph_node.type == "table.read_table" and "path" in graph_node.inputs:
            graph_node.inputs["path"] = str(csv_path)
    return graph


def main_cli() -> None:
    from engine import run, to_python

    graph = build_graph()
    out = graph.output
    print(run(graph).value(out["node"], out["socket"]))
    print("\n----- to_python(graph) -----")
    print(to_python(graph))


if __name__ == "__main__":
    main_cli()
