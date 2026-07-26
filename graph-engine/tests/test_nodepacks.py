"""Tests for the calc + sources node packs and the readings example.

Covers: node outputs, CSV reading, the generic JSON pair (``read_json`` +
``pick``, including the missing-key error and the ``null`` empty given), graph
run + HTML render, the CSV↔mock-API source swap (identical output, one
differing node), and re-running after editing the CSV values.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import calc
import sources
from engine import UserError, run

from readings import (
    CSV_PATH,
    build_api_graph,
    build_csv_graph,
    readings_report,
)

VALUES = [10.0, 20.0, 30.0, 40.0]


# -- calc pack: plain node outputs -----------------------------------------


def test_calc_reductions():
    assert calc.total(VALUES) == 100.0
    assert calc.average(VALUES) == 25.0
    assert calc.median(VALUES) == 25.0
    assert calc.minimum(VALUES) == 10.0
    assert calc.maximum(VALUES) == 40.0


def test_median_of_odd_length():
    assert calc.median([1.0, 5.0, 2.0]) == 2.0


def test_render_summary_is_self_contained_html():
    html = calc.render_summary("Readings summary", 25.0, 25.0)
    assert html.startswith("<div")
    assert "Readings summary" in html
    assert "Average" in html and "Median" in html
    assert "25" in html
    # Self-contained: inline styling only, no external/CDN assets.
    assert "http://" not in html and "https://" not in html
    assert "<link" not in html and "<script" not in html


# -- sources pack: CSV read + mock API -------------------------------------


def test_read_csv_yields_expected_values():
    assert sources.read_csv(str(CSV_PATH)) == VALUES


def test_read_csv_unknown_column_raises():
    with pytest.raises(ValueError):
        sources.read_csv(str(CSV_PATH), column="nope")


def test_mock_api_matches_csv_shape():
    assert sources.mock_api("readings") == VALUES
    assert sources.read_csv(str(CSV_PATH)) == sources.mock_api("readings")


def test_mock_api_is_network_free_by_default():
    with pytest.raises(ValueError):
        sources.mock_api("readings", offline=False)


# -- sources pack: JSON object + one named value ---------------------------


def _write_json(tmp_path: Path, text: str) -> str:
    path = tmp_path / "inputs.json"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_read_json_returns_the_object_unchanged(tmp_path: Path):
    path = _write_json(tmp_path, '{"a": 1, "b": {"value": 2, "unit": "mm"}}')
    assert sources.read_json(path) == {"a": 1, "b": {"value": 2, "unit": "mm"}}


def test_read_json_refuses_a_non_object_document(tmp_path: Path):
    path = _write_json(tmp_path, "[1, 2, 3]")
    with pytest.raises(UserError, match="JSON object"):
        sources.read_json(path)


def test_read_json_reports_a_missing_file_and_bad_syntax(tmp_path: Path):
    with pytest.raises(UserError, match="no such JSON file"):
        sources.read_json(str(tmp_path / "absent.json"))
    with pytest.raises(UserError, match="not valid JSON"):
        sources.read_json(_write_json(tmp_path, "{oops"))


def test_pick_reads_a_bare_number_and_a_record_carrying_one():
    """Both spellings mean the same number — the record just adds provenance."""
    assert sources.pick({"b": 220}, "b") == 220.0
    assert sources.pick({"b": {"value": 220, "unit": "mm", "ref": "EN 1995"}}, "b") == 220.0
    assert isinstance(sources.pick({"b": 220}, "b"), float)


def test_pick_yields_none_for_json_null():
    """`null` is a value: the given is empty (not applicable), not missing."""
    assert sources.pick({"l_1": None}, "l_1") is None
    assert sources.pick({"l_1": {"value": None, "unit": "mm"}}, "l_1") is None


def test_pick_missing_key_names_it_and_lists_what_is_there():
    with pytest.raises(UserError) as error:
        sources.pick({"a_1": 0, "l": 80}, "l_1")

    message = str(error.value)
    assert "'l_1'" in message  # the key that was asked for
    assert "'a_1'" in message and "'l'" in message  # what the object does have


def test_pick_refuses_a_non_numeric_value():
    with pytest.raises(UserError, match="number or null"):
        sources.pick({"a": "eighty"}, "a")
    # A flag is not a quantity, even though bool is an int subclass.
    with pytest.raises(UserError, match="number or null"):
        sources.pick({"a": True}, "a")


def test_pick_refuses_data_that_is_not_an_object():
    with pytest.raises(UserError, match="JSON object"):
        sources.pick([1, 2], "a")


# -- the graph: run + render -----------------------------------------------


def test_csv_graph_runs_and_renders_numbers():
    g = build_csv_graph()
    result = run(g)
    assert result.value("average") == 25.0
    assert result.value("median") == 25.0
    html = result.value(g.output["node"], g.output["socket"])
    assert "25" in html
    assert html.startswith("<div")


def test_composite_runs_eagerly():
    html = readings_report(path=str(CSV_PATH))
    assert "Readings summary" in html
    assert "25" in html


# -- the source swap: CSV vs mock API --------------------------------------


def _output_html(graph):
    return run(graph).value(graph.output["node"], graph.output["socket"])


def test_source_swap_produces_identical_output():
    assert _output_html(build_csv_graph()) == _output_html(build_api_graph())


def test_source_swap_differs_by_exactly_one_node_type():
    csv_graph = build_csv_graph().to_dict()
    api_graph = build_api_graph().to_dict()

    csv_types = sorted(n["type"] for n in csv_graph["nodes"])
    api_types = sorted(n["type"] for n in api_graph["nodes"])

    # Same node count, and every downstream node type is shared.
    assert len(csv_types) == len(api_types)
    shared = set(csv_types) & set(api_types)
    csv_only = set(csv_types) - shared
    api_only = set(api_types) - shared

    # Exactly one node type differs on each side — the source node.
    assert csv_only == {"sources.read_csv"}
    assert api_only == {"sources.mock_api"}
    # All other node types identical.
    assert shared == {"calc.average", "calc.median", "calc.render_summary"}


# -- editing the CSV and re-running ----------------------------------------


def test_editing_csv_changes_the_result(tmp_path: Path):
    edited = tmp_path / "readings.csv"
    edited.write_text("value\n10\n20\n30\n40\n60\n", encoding="utf-8")

    result = run(build_csv_graph(edited))
    # New values [10,20,30,40,60]: average 32, median 30 (vs 25/25 before).
    assert result.value("average") == 32.0
    assert result.value("median") == 30.0
    html = result.value("render_summary", "result")
    assert "32" in html and "30" in html


def test_render_summary_escapes_title():
    # A user/upstream-controlled title must not inject markup (HTML escaping).
    from calc import render_summary

    out = render_summary("</h1><script>alert(1)</script>", 1.0, 2.0)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
