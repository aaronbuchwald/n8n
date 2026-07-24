"""Tests for the ``table`` node pack and the table example.

Covers, in order:

* :func:`table.read_table` — CSV parsing (path + inline text), float/str cell
  coercion, malformed-CSV rejection;
* each v1 op's correctness on a small fixture (select, rename, filter, derive,
  sort, aggregate, limit) plus their ``UserError`` paths;
* the expression grammar whitelist — valid expressions compute correctly;
  every rejected construct (attribute access, disallowed calls, unknown
  names, comprehensions, lambdas, f-strings, ...) raises ``UserError`` naming
  the construct;
* the recipe envelope (``version``/``ops`` validation);
* the recipe round-trips as an ordinary Python literal (``repr`` /
  ``ast.literal_eval``), matching the ADR 0004 bijection;
* :func:`table.table_summary` renders a self-contained HTML card;
* the example graph runs end-to-end and its ``to_python`` export round-trips.
"""

from __future__ import annotations

import ast

import pytest

import table
from engine import UserError, run, to_python
from table.expr import compile_expr
from table.recipe import StdlibInterpreter, interpret

FIXTURE = {
    "columns": ["region", "amount", "qty"],
    "rows": [
        ["north", 120.0, 3.0],
        ["south", 80.0, 1.0],
        ["north", 45.0, 2.0],
        ["east", 200.0, 5.0],
    ],
}


def _recipe(*ops: dict) -> dict:
    return {"version": 1, "ops": list(ops)}


# -- read_table ---------------------------------------------------------------


def test_read_table_from_path(tmp_path):
    csv_path = tmp_path / "t.csv"
    csv_path.write_text("a,b\n1,x\n2,y\n", encoding="utf-8")
    result = table.read_table(str(csv_path))
    assert result == {"columns": ["a", "b"], "rows": [[1.0, "x"], [2.0, "y"]]}


def test_read_table_from_inline_text():
    result = table.read_table(text="a,b\n1,foo\n2.5,bar\n")
    assert result == {"columns": ["a", "b"], "rows": [[1.0, "foo"], [2.5, "bar"]]}


def test_read_table_keeps_non_numeric_cells_as_str():
    result = table.read_table(text="name,score\nalice,10\nbob,notanumber\n")
    assert result["rows"] == [["alice", 10.0], ["bob", "notanumber"]]


def test_read_table_rejects_empty_csv(tmp_path):
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("", encoding="utf-8")
    with pytest.raises(UserError, match="header"):
        table.read_table(str(csv_path))


def test_read_table_rejects_ragged_rows():
    with pytest.raises(UserError, match="row 1"):
        table.read_table(text="a,b\n1\n")


def test_read_table_rejects_duplicate_columns():
    with pytest.raises(UserError, match="duplicate"):
        table.read_table(text="a,a\n1,2\n")


# -- individual ops -------------------------------------------------------------


def test_select_keeps_only_named_columns_in_order():
    out = table.apply_recipe(FIXTURE, _recipe({"op": "select", "columns": ["qty", "region"]}))
    assert out["columns"] == ["qty", "region"]
    assert out["rows"][0] == [3.0, "north"]


def test_select_unknown_column_raises():
    with pytest.raises(UserError, match="unknown column"):
        table.apply_recipe(FIXTURE, _recipe({"op": "select", "columns": ["nope"]}))


def test_rename_renames_and_preserves_order():
    out = table.apply_recipe(FIXTURE, _recipe({"op": "rename", "columns": {"amount": "amt"}}))
    assert out["columns"] == ["region", "amt", "qty"]
    assert out["rows"][0] == ["north", 120.0, 3.0]


def test_rename_collision_with_existing_column_raises():
    with pytest.raises(UserError, match="collide"):
        table.apply_recipe(FIXTURE, _recipe({"op": "rename", "columns": {"amount": "qty"}}))


def test_filter_keeps_matching_rows():
    out = table.apply_recipe(FIXTURE, _recipe({"op": "filter", "expr": "qty > 1"}))
    assert [r[0] for r in out["rows"]] == ["north", "north", "east"]


def test_derive_adds_computed_column():
    out = table.apply_recipe(
        FIXTURE, _recipe({"op": "derive", "name": "total", "expr": "amount * qty"})
    )
    assert out["columns"] == ["region", "amount", "qty", "total"]
    assert out["rows"][0][-1] == 360.0


def test_derive_overwrites_existing_column_in_place():
    out = table.apply_recipe(
        FIXTURE, _recipe({"op": "derive", "name": "amount", "expr": "amount * 2"})
    )
    assert out["columns"] == ["region", "amount", "qty"]  # no new column appended
    assert out["rows"][0][1] == 240.0


def test_sort_ascending_and_descending():
    asc = table.apply_recipe(FIXTURE, _recipe({"op": "sort", "by": ["amount"]}))
    assert [r[1] for r in asc["rows"]] == [45.0, 80.0, 120.0, 200.0]

    desc = table.apply_recipe(
        FIXTURE, _recipe({"op": "sort", "by": ["amount"], "descending": True})
    )
    assert [r[1] for r in desc["rows"]] == [200.0, 120.0, 80.0, 45.0]


def test_aggregate_group_by_with_sum_mean_count():
    out = table.apply_recipe(
        FIXTURE,
        _recipe(
            {
                "op": "aggregate",
                "group_by": ["region"],
                "aggs": [
                    {"col": "amount", "fn": "sum", "as": "amount_sum"},
                    {"col": "amount", "fn": "mean", "as": "amount_mean"},
                    {"col": "amount", "fn": "count", "as": "n"},
                ],
            }
        ),
    )
    assert out["columns"] == ["region", "amount_sum", "amount_mean", "n"]
    rows_by_region = {r[0]: r[1:] for r in out["rows"]}
    assert rows_by_region["north"] == [165.0, 82.5, 2]
    assert rows_by_region["south"] == [80.0, 80.0, 1]
    assert rows_by_region["east"] == [200.0, 200.0, 1]


def test_aggregate_without_group_by_reduces_whole_table():
    out = table.apply_recipe(
        FIXTURE,
        _recipe(
            {
                "op": "aggregate",
                "group_by": [],
                "aggs": [{"col": "amount", "fn": "sum", "as": "total"}],
            }
        ),
    )
    assert out == {"columns": ["total"], "rows": [[445.0]]}


def test_aggregate_unknown_fn_raises():
    with pytest.raises(UserError, match="unknown fn"):
        table.apply_recipe(
            FIXTURE,
            _recipe(
                {
                    "op": "aggregate",
                    "group_by": [],
                    "aggs": [{"col": "amount", "fn": "stddev", "as": "x"}],
                }
            ),
        )


def test_limit_keeps_first_n_rows():
    out = table.apply_recipe(FIXTURE, _recipe({"op": "limit", "n": 2}))
    assert len(out["rows"]) == 2
    assert out["rows"] == FIXTURE["rows"][:2]


def test_limit_rejects_negative_n():
    with pytest.raises(UserError, match="non-negative"):
        table.apply_recipe(FIXTURE, _recipe({"op": "limit", "n": -1}))


def test_full_pipeline_filter_derive_sort_limit():
    out = table.apply_recipe(
        FIXTURE,
        _recipe(
            {"op": "filter", "expr": "qty > 1"},
            {"op": "derive", "name": "total", "expr": "amount * qty"},
            {"op": "sort", "by": ["total"], "descending": True},
            {"op": "limit", "n": 1},
        ),
    )
    assert out["columns"] == ["region", "amount", "qty", "total"]
    assert out["rows"] == [["east", 200.0, 5.0, 1000.0]]


# -- recipe envelope ------------------------------------------------------------


def test_unsupported_version_raises():
    with pytest.raises(UserError, match="version"):
        table.apply_recipe(FIXTURE, {"version": 2, "ops": []})


def test_unknown_op_raises():
    with pytest.raises(UserError, match="unknown op"):
        table.apply_recipe(FIXTURE, _recipe({"op": "pivot"}))


def test_missing_ops_key_raises():
    with pytest.raises(UserError, match="ops"):
        table.apply_recipe(FIXTURE, {"version": 1})


def test_default_recipe_is_identity():
    out = table.apply_recipe(FIXTURE, None)
    assert out == FIXTURE


def test_error_names_the_offending_op_index():
    with pytest.raises(UserError, match=r"ops\[1\]"):
        table.apply_recipe(
            FIXTURE, _recipe({"op": "limit", "n": 100}, {"op": "select", "columns": ["nope"]})
        )


# -- the expression grammar: accept path -----------------------------------------


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("amount + qty", 123.0),
        ("amount - qty", 117.0),
        ("amount * qty", 360.0),
        ("amount / qty", 40.0),
        ("qty % 2", 1.0),
        ("qty ** 2", 9.0),
        ("-qty", -3.0),
        ("amount > 100 and qty > 1", True),
        ("amount > 1000 or qty > 1", True),
        ("not (qty > 1)", False),
        ("amount == 120.0", True),
        ("amount != 120.0", False),
        ("1 < qty < 10", True),
        ("abs(-qty)", 3.0),
        ("round(amount / qty, 1)", 40.0),
        ("min(amount, qty)", 3.0),
        ("max(amount, qty)", 120.0),
        ("'a' + 'b' == 'ab'", True),
        ("True and not False", True),
    ],
)
def test_expression_whitelist_accepts_and_computes(expr, expected):
    compiled = compile_expr(expr, ["amount", "qty"])
    assert compiled({"amount": 120.0, "qty": 3.0}) == expected


@pytest.mark.parametrize(
    "expr",
    [
        "amount.bit_length()",  # attribute access
        "amount[0]",  # subscript
        "__import__('os')",  # unknown name / call
        "os.system('x')",  # attribute access + unknown name
        "[x for x in [1, 2]]",  # comprehension
        "(lambda x: x)(1)",  # lambda
        "f'{amount}'",  # f-string
        "amount if qty else 0",  # ternary
        "sum([amount, qty])",  # call outside whitelist
        "open('x')",  # call outside whitelist
        "unknown_column + 1",  # unknown name
        "amount; qty",  # not a single expression at all
        "None",  # disallowed literal
        "amount = 1",  # assignment (not even a valid `eval` expr, still must raise UserError not SyntaxError leak)
    ],
)
def test_expression_whitelist_rejects_unsafe_constructs(expr):
    with pytest.raises(UserError):
        compile_expr(expr, ["amount", "qty"])


def test_expression_rejects_keyword_and_star_args_in_calls():
    with pytest.raises(UserError, match="keyword"):
        compile_expr("round(amount, ndigits=1)", ["amount"])
    with pytest.raises(UserError, match=r"\*args"):
        compile_expr("max(*[1, 2])", ["amount"])


def test_expression_division_by_zero_raises_usererror_not_zerodivisionerror():
    compiled = compile_expr("amount / qty", ["amount", "qty"])
    with pytest.raises(UserError):
        compiled({"amount": 1.0, "qty": 0.0})


def test_filter_and_derive_route_bad_expressions_through_usererror():
    with pytest.raises(UserError):
        table.apply_recipe(FIXTURE, _recipe({"op": "filter", "expr": "region.upper()"}))
    with pytest.raises(UserError):
        table.apply_recipe(FIXTURE, _recipe({"op": "derive", "name": "x", "expr": "nope + 1"}))


# -- recipe as a literal (ADR 0004 bijection) ------------------------------------


def test_recipe_round_trips_as_a_python_literal():
    recipe = _recipe(
        {"op": "filter", "expr": "qty > 1"},
        {"op": "derive", "name": "total", "expr": "amount * qty"},
        {
            "op": "aggregate",
            "group_by": ["region"],
            "aggs": [{"col": "total", "fn": "sum", "as": "total_sum"}],
        },
    )
    literal_text = repr(recipe)
    round_tripped = ast.literal_eval(literal_text)
    assert round_tripped == recipe
    # And it computes the same result either way.
    assert table.apply_recipe(FIXTURE, recipe) == table.apply_recipe(FIXTURE, round_tripped)


def test_interpreter_class_is_a_swappable_backend_seam():
    # apply_recipe's default backend is StdlibInterpreter; interpret() also
    # accepts one explicitly -- the seam a future polars backend plugs into.
    out = interpret(FIXTURE, _recipe({"op": "limit", "n": 1}), interpreter=StdlibInterpreter())
    assert out["rows"] == FIXTURE["rows"][:1]


# -- table_summary: self-contained HTML ------------------------------------------


def test_table_summary_is_self_contained_html():
    out = table.table_summary(FIXTURE, title="Fixture")
    assert out.startswith("<div")
    assert "Fixture" in out
    assert "region" in out and "north" in out
    assert "4 row(s)" in out and "3 column(s)" in out
    assert "http://" not in out and "https://" not in out
    assert "<link" not in out and "<script" not in out


def test_table_summary_escapes_title_and_cells():
    out = table.table_summary(
        {"columns": ["x"], "rows": [["</h1><script>alert(1)</script>"]]},
        title="</h1><script>alert(1)</script>",
    )
    assert "<script>alert(1)</script>" not in out
    assert out.count("&lt;script&gt;") >= 2


def test_table_summary_notes_truncation_of_long_tables():
    big = {"columns": ["n"], "rows": [[float(i)] for i in range(25)]}
    out = table.table_summary(big)
    assert "+5 more row(s)" in out


# -- the example graph, end-to-end -----------------------------------------------


def test_example_graph_runs_and_aggregates_correctly():
    from sales_report import build_graph

    graph = build_graph()
    result = run(graph)

    aggregated = result.value("apply_recipe")
    rows_by_region = {r[0]: r[1:] for r in aggregated["rows"]}
    assert aggregated["columns"] == ["region", "total_amount", "avg_amount", "n"]
    assert rows_by_region["north"] == [450.0, 82.5, 2]
    assert rows_by_region["east"] == [1180.0, 145.0, 2]
    assert rows_by_region["south"] == [600.0, 150.0, 1]

    html = result.value(graph.output["node"], graph.output["socket"])
    assert html.startswith("<div")
    assert "Sales by region" in html
    assert "http" not in html and "<script" not in html


def test_example_graph_exports_python():
    from sales_report import build_graph

    script = to_python(build_graph())
    assert "from table import" in script
    assert "apply_recipe" in script
    assert "'version': 1" in script
