"""Tests for ``beam_bearing_pressure_rfem`` — the same EC5 check, force from RFEM.

Covers, in order:

* the graph's shape — the export arc (read → select → write) beside the JSON
  arc (read → eight picks), meeting at one ``sheet.calc_card``;
* that ``F_c90d`` is **derived**: it comes off ``governing``, and ``inputs.json``
  no longer holds a copy of it;
* the governing row, and the given row that cites it;
* every computed number individually, and η ≈ 405 % — a FAILING check on a
  **green** run (ADR 0016);
* the written artifact — a run output, not a committed file;
* the module is a byte-exact fixed point of the graph⟷source bijection;
* the JSON-only example beside it is untouched by any of this.

Run with:  uv run --extra dev --extra sym python -m pytest -q
"""

from __future__ import annotations

import json

import pytest

from engine import DEFAULT_REGISTRY, from_composite, run, to_python, validate_graph
from server.demo import example_dir
from server.writeback import compute_writeback

ENTRY = "beam_bearing_pressure_rfem"
HEAVY_DEPS = ("calcsheet", "sympy", "latex2mathml")

# The row RFEM's own extremum search reports as governing, and its number.
GOVERNING_REF = "RFEM 10103/1578 @ 6.15 m · LK67"
VZ_SIGNED = -297.175507
F_C90D = 297.175507  # |Vz|

# The numbers this force produces, to full double precision.
SIGMA_C90D = 12.279979628099174  # 297175.507 N / 24200 mm²
F_C90D_STRENGTH = 1.7307692307692306  # 0.90 · 2.50 / 1.30
ETA = 405.4342480388299

GIVENS = ["a_1", "l", "l_1", "b", "k_c90", "k_mod", "f_c90k", "gamma_M"]


def _calc_deps_available() -> bool:
    for name in HEAVY_DEPS:
        try:
            __import__(name)
        except ImportError:
            return False
    return True


needs_sym_extra = pytest.mark.skipif(
    not _calc_deps_available(), reason="sym extra not installed"
)


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    """A scratch run directory — the artifact must never land in the checkout."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _edge_set(graph) -> set[tuple[str, str, str, str]]:
    return {
        (e["source"], e["sourceOutput"], e["target"], e["targetInput"])
        for e in graph.to_dict()["edges"]
    }


def _module_text() -> str:
    return (example_dir(ENTRY) / f"{ENTRY}.py").read_text(encoding="utf-8")


def _rows(result) -> dict[str, object]:
    return {row.symbol: row for row in (*result.inputs, *result.formulas)}


def _result():
    """The card's own ``Result`` — fed exactly as the graph feeds it."""
    import rfem
    import sheet
    import sources
    from beam_bearing_pressure_rfem import EXPORT_CSV, INPUTS_JSON, build_graph

    card = next(
        n for n in build_graph().to_dict()["nodes"] if n["type"] == "sheet.calc_card"
    )
    data = sources.read_json(str(INPUTS_JSON))
    governing = rfem.governing_force(rfem.read_extrema(str(EXPORT_CSV)), component="Vz")
    sockets = [s["name"] for s in sheet.formula_free_symbols(card["inputs"]["formulas"])]
    values = {
        key: (governing if key == "F_c90d" else sources.pick(data, key)) for key in sockets
    }
    return sheet.calc(
        title=card["inputs"]["title"],
        as_of=card["inputs"]["as_of"],
        formulas=card["inputs"]["formulas"],
        checks=card["inputs"]["checks"],
        precision=card["inputs"]["precision"],
        **values,
    )


# -- the graph's shape (no heavy deps needed) ---------------------------------


def test_the_export_arc_sits_beside_the_json_arc():
    from beam_bearing_pressure_rfem import build_graph

    doc = build_graph().to_dict()
    assert [n["type"] for n in doc["nodes"]] == [
        "rfem.read_extrema",
        "rfem.governing_force",
        "sources.write_json",
        "sources.read_json",
        *["sources.pick"] * 8,
        "sheet.calc_card",
    ]
    keys = [n["inputs"]["key"] for n in doc["nodes"] if n["type"] == "sources.pick"]
    assert keys == GIVENS  # eight givens — F_c90d is not among them


def test_the_force_comes_from_the_export_and_the_other_eight_from_json():
    from beam_bearing_pressure_rfem import build_graph

    edges = _edge_set(build_graph())
    assert ("read_extrema", "result", "governing_force", "table") in edges
    assert ("governing_force", "result", "calc_card", "F_c90d") in edges
    for node_id, symbol in zip(["pick"] + [f"pick_{n}" for n in range(2, 9)], GIVENS):
        assert ("read_json", "result", node_id, "data") in edges
        assert (node_id, "result", "calc_card", symbol) in edges
    # …and nothing feeds F_c90d from the JSON side.
    assert not any(e[2] == "calc_card" and e[3] == "F_c90d" and e[0] != "governing_force"
                   for e in edges)


def test_the_artifact_hangs_off_the_selector_not_between_it_and_the_card():
    """The selector stays pure; the card can be fed without writing anything."""
    from beam_bearing_pressure_rfem import build_graph

    edges = _edge_set(build_graph())
    assert ("governing_force", "result", "write_json", "data") in edges
    # write_json feeds nothing: it is a leaf.
    assert not any(e[0] == "write_json" for e in edges)
    assert build_graph().output == {"node": "calc_card", "socket": "result"}


def test_inputs_json_no_longer_carries_the_force():
    """One number, one source: the JSON's F_c90d entry is gone, not shadowed."""
    from beam_bearing_pressure_rfem import INPUTS_JSON

    data = json.loads(INPUTS_JSON.read_text(encoding="utf-8"))
    assert "F_c90d" not in data
    assert list(data) == GIVENS
    assert data["l_1"]["value"] is None  # the empty given survives the move


def test_the_calculation_is_unchanged_from_the_json_only_example():
    """Same literals, same check, same title, same as_of, same precision."""
    from beam_bearing_pressure import build_graph as json_only_graph
    from beam_bearing_pressure_rfem import build_graph

    def card_of(graph):
        return next(
            n for n in graph.to_dict()["nodes"] if n["type"] == "sheet.calc_card"
        )["inputs"]

    theirs, ours = card_of(json_only_graph()), card_of(build_graph())
    assert ours["formulas"] == theirs["formulas"]
    assert ours["checks"] == theirs["checks"]
    assert ours["title"] == theirs["title"] == "Support pressure without reinforcement"
    assert ours["as_of"] == theirs["as_of"] == "2025-07-02"
    assert ours["precision"] == theirs["precision"] == 5


def test_the_selection_policy_is_one_literal_on_one_node():
    from beam_bearing_pressure_rfem import build_graph

    selector = next(
        n for n in build_graph().to_dict()["nodes"] if n["type"] == "rfem.governing_force"
    )
    assert selector["inputs"] == {"component": "Vz"}


def test_the_write_destination_stays_relative_in_the_graph():
    """`sources.write_json` refuses an absolute path; the graph never authors one."""
    from beam_bearing_pressure_rfem import build_graph

    writer = next(
        n for n in build_graph().to_dict()["nodes"] if n["type"] == "sources.write_json"
    )
    assert writer["inputs"] == {"path": "governing.json"}


# -- the numbers, one at a time -----------------------------------------------


@needs_sym_extra
def test_graph_loads_binds_and_runs_end_to_end(run_dir):
    from beam_bearing_pressure_rfem import build_graph

    graph = build_graph()
    validate_graph(graph.to_dict())
    result = run(graph)

    governing = result.value("governing_force")
    assert governing["value"] == F_C90D
    assert governing["signed"] == VZ_SIGNED
    assert governing["unit"] == "kN"
    assert governing["ref"] == GOVERNING_REF
    assert governing["member"] == 10103.0 and governing["node"] == 1578.0
    assert governing["position"] == 6.1500000000005
    assert governing["load_case"] == "LK67"
    assert governing["component"] == "Vz" and governing["source"] == "export.csv"


@needs_sym_extra
def test_every_computed_value_individually():
    values = _result().values

    assert values["F_c90d"] == F_C90D  # the magnitude reaches the calc
    assert values["l_l"] == 0.0
    assert values["l_r"] == 30.0
    assert values["l_ef"] == 110.0
    assert values["A_ef"] == 24200.0
    assert values["sigma_c90d"] == SIGMA_C90D
    assert values["f_c90d"] == F_C90D_STRENGTH
    assert values["eta"] == ETA


@needs_sym_extra
def test_the_rows_render_at_five_significant_digits():
    rows = _rows(_result())

    assert [(s, rows[s].value_text, rows[s].unit) for s in
            ("l_l", "l_r", "l_ef", "A_ef", "sigma_c90d", "f_c90d", "eta")] == [
        ("l_l", "0", "mm"),
        ("l_r", "30", "mm"),
        ("l_ef", "110", "mm"),
        ("A_ef", "24200", "mm²"),
        ("sigma_c90d", "12.28", "N/mm²"),
        ("f_c90d", "1.7308", "N/mm²"),
        ("eta", "405.43", "%"),
    ]


@needs_sym_extra
def test_the_derived_given_cites_the_export_row_it_came_from():
    """`F_c90d`'s row reads like the other eight — value, unit, provenance."""
    given = {row.symbol: row for row in _result().inputs}

    assert (given["F_c90d"].value_text, given["F_c90d"].unit) == ("297.18", "kN")
    assert given["F_c90d"].ref == GOVERNING_REF
    # The eight JSON givens still cite their code clauses.
    assert given["gamma_M"].ref == "DIN EN 1995-1-1/NA NDP 2.4.1(1)P"
    assert (given["l_1"].value_text, given["l_1"].unit) == ("–", "mm")


@needs_sym_extra
def test_the_check_fails_at_about_405_percent():
    result = _result()

    (check,) = result.checks
    assert check.expr == "eta < 100"
    assert check.passed is False
    assert check.substituted == "405.43 < 100 = False"
    assert check.utilisation == ETA and check.limit == 100.0
    assert result.passed is False
    assert result.governing == ("eta < 100", ETA)


@needs_sym_extra
def test_a_failing_check_does_not_fail_the_run(run_dir):
    """ADR 0016: the verdict is card content — no assertion node, no raise."""
    from beam_bearing_pressure_rfem import build_graph

    result = run(build_graph())
    assert set(result.outputs) == {
        "read_extrema", "governing_force", "write_json", "read_json",
        "pick", *[f"pick_{n}" for n in range(2, 9)], "calc_card",
    }
    assert "Overall <b>FAIL</b>" in result.value("calc_card", "result")


@needs_sym_extra
def test_output_html_carries_the_export_provenance_and_the_verdict(run_dir):
    from beam_bearing_pressure_rfem import build_graph

    graph = build_graph()
    html = run(graph).value(graph.output["node"], graph.output["socket"])

    assert isinstance(html, str) and html.startswith("<!doctype html>")
    assert "Support pressure without reinforcement" in html
    assert '297.18&nbsp;<span class="unit">kN</span>' in html
    assert f'<span class="ref">{GOVERNING_REF}</span>' in html
    assert '12.28&nbsp;<span class="unit">N/mm²</span>' in html
    assert '405.43&nbsp;<span class="unit">%</span>' in html
    # The chip states the measured value and the limit it was judged against —
    # never the substituted inequality, which for a failing check is a false
    # statement printed on a design document.
    assert '<span class="chk__tag">actual</span> 405.43&nbsp;<span class="unit">%</span>' in html
    assert '<span class="chk__tag">limit</span> 100&nbsp;<span class="unit">%</span>' in html
    assert 'badge--fail">FAIL' in html
    assert "405.43 &lt; 100 = False" not in html
    assert 'class="status status--fail"' in html and "Overall <b>FAIL</b>" in html
    # Self-contained, like every card in this repo.
    assert "http" not in html
    assert "<script" not in html and "<link" not in html and "@import" not in html


# -- the written artifact -----------------------------------------------------


@needs_sym_extra
def test_the_run_writes_the_governing_record_into_the_run_directory(run_dir):
    from beam_bearing_pressure_rfem import build_graph

    result = run(build_graph())

    written = run_dir / "governing.json"
    assert result.value("write_json") == str(written)
    record = json.loads(written.read_text(encoding="utf-8"))
    assert record == result.value("governing_force")
    assert record["value"] == F_C90D and record["ref"] == GOVERNING_REF


def test_the_artifact_is_gitignored_and_not_committed():
    """Two copies of the same number are two things that can disagree."""
    directory = example_dir(ENTRY)
    ignored = (directory / ".gitignore").read_text(encoding="utf-8")

    assert "governing.json" in ignored
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files", "governing.json"],
        cwd=directory, capture_output=True, text=True, check=True,
    )
    assert tracked.stdout.strip() == ""


def test_the_export_and_the_workbook_are_committed():
    """The CSV the graph reads and the workbook it was converted from."""
    directory = example_dir(ENTRY)
    assert (directory / "export.csv").is_file()
    assert (directory / "260726_GZT_DesignLoadsMembers_Start_End.xlsx").is_file()
    assert (directory / "xlsx_to_csv.py").is_file()


@needs_sym_extra
def test_graph_declares_environment_dependencies():
    from beam_bearing_pressure_rfem import DEPENDENCIES, build_graph

    graph = build_graph()
    assert graph.environment is not None
    assert graph.environment["network"] == "none"
    assert graph.environment["dependencies"] == DEPENDENCIES


@needs_sym_extra
def test_graph_exports_python(run_dir):
    from beam_bearing_pressure_rfem import build_graph

    script = to_python(build_graph())
    namespace: dict = {}
    exec(compile(script, "<exported>", "exec"), namespace)  # noqa: S102 - trusted, generated
    graph = build_graph()
    assert namespace["_calc_card"] == run(graph).value(
        graph.output["node"], graph.output["socket"]
    )


# -- served + the bijection ---------------------------------------------------


def test_the_entry_is_discoverable_by_the_picker():
    from server.entries import EntryCatalog

    entries = {e["id"]: e for e in EntryCatalog().discover().entries()}
    assert entries[ENTRY]["status"] == "ok", entries[ENTRY].get("error")
    assert entries[ENTRY]["title"] == "Beam bearing pressure rfem"


def test_served_node_ids_are_the_authored_variable_names():
    from server.demo import load_graph, make_workspace

    graph = load_graph(ENTRY, make_workspace(ENTRY))
    assert [n["id"] for n in graph["nodes"]] == [
        "forces", "governing", "artifact", "inputs",
        "a_1", "l", "l_1", "b", "k_c90", "k_mod", "f_c90k", "gamma_M", "card",
    ]
    assert graph["output"] == {"node": "card", "socket": "result"}
    # Served pristine: relative filenames, no absolute machine path anywhere.
    assert graph["nodes"][0]["inputs"]["path"] == "export.csv"
    assert graph["nodes"][2]["inputs"]["path"] == "governing.json"
    assert graph["nodes"][3]["inputs"]["path"] == "inputs.json"


def test_the_module_is_a_byte_exact_fixed_point_of_the_bijection():
    """Parsing and saving it unedited rewrites nothing (ADR 0004 D5 / 0020)."""
    import beam_bearing_pressure_rfem  # noqa: F401 - registers the node types

    text = _module_text()
    graph = from_composite(text, DEFAULT_REGISTRY, module_name=ENTRY)
    written = compute_writeback(text, graph, DEFAULT_REGISTRY, ENTRY)
    assert written.strategy == "unchanged"
    assert written.text == text


def test_the_wiring_statements_are_already_in_the_emitters_canonical_form():
    import ast

    import beam_bearing_pressure_rfem  # noqa: F401 - registers the node types
    from engine.composite import composite_call_names, wiring_lines

    text = _module_text()
    graph = from_composite(text, DEFAULT_REGISTRY, module_name=ENTRY)
    call_names = composite_call_names(ast.parse(text), ENTRY)

    emitted = wiring_lines(graph, DEFAULT_REGISTRY, call_names=call_names)
    # Every statement whose arguments are literals is emitted exactly as
    # authored. (The three `path=` reads/writes take a composite parameter, so
    # the emitter writes the resolved literal there instead — which is why the
    # fixed-point test above, not this one, is the bijection's real guarantee.)
    card = next(line for line in emitted if line.lstrip().startswith("card = "))
    assert card in text
    assert next(line for line in emitted if "governing_force(" in line) in text
    for line in emitted:
        if "pick(" in line:
            assert line in text


def test_an_edit_and_its_revert_restore_the_file_byte_for_byte():
    import beam_bearing_pressure_rfem  # noqa: F401 - registers the node types

    text = _module_text()

    edited = from_composite(text, DEFAULT_REGISTRY, module_name=ENTRY)
    next(n for n in edited.nodes if n.id == "governing").inputs["component"] = "Vy"
    patched = compute_writeback(text, edited, DEFAULT_REGISTRY, ENTRY)
    assert patched.strategy == "patched" and patched.changed_ids == ["governing"]
    assert "component='Vy'" in patched.text

    reverted = from_composite(patched.text, DEFAULT_REGISTRY, module_name=ENTRY)
    next(n for n in reverted.nodes if n.id == "governing").inputs["component"] = "Vz"
    assert compute_writeback(patched.text, reverted, DEFAULT_REGISTRY, ENTRY).text == text


# -- the example it extends is untouched ---------------------------------------


def test_the_json_only_example_still_has_its_own_force():
    """`beam_bearing_pressure` stays the minimal JSON-only case, unchanged."""
    from beam_bearing_pressure import INPUTS_JSON as JSON_ONLY_INPUTS

    data = json.loads(JSON_ONLY_INPUTS.read_text(encoding="utf-8"))
    assert data["F_c90d"] == {
        "value": 107.0, "unit": "kN", "ref": "EN 1995-1-1 6.1.5 (1)",
    }
