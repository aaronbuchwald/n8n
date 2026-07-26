"""Tests for ``beam_bearing_pressure_tiered`` — one design per load tier.

Covers, in order:

* the graph's shape — the export arc (read → population) and the JSON arc
  (read → grouping rule + eight picks) meeting at one ``grouping.group``, then
  at one ``sheet.group_card``;
* that the grouping rule lives in ``inputs.json`` beside the givens, reached by
  an ordinary ``sources.pick``;
* the tier distribution this export actually produces, and every governing force
  with the row it came from;
* every computed number individually, and a MIXED verdict — two tiers FAIL, one
  PASSES — on a **green** run (ADR 0016);
* the shared geometry appearing once, not once per tier;
* the written artifact — a run output, not a committed file;
* the module is a byte-exact fixed point of the graph⟷source bijection;
* the two examples it sits beside are untouched, and the export is not copied.

Run with:  uv run --extra dev --extra sym python -m pytest -q
"""

from __future__ import annotations

import json
import subprocess

import pytest

from engine import DEFAULT_REGISTRY, from_composite, run, to_python, validate_graph
from server.demo import example_dir
from server.writeback import compute_writeback

ENTRY = "beam_bearing_pressure_tiered"
HEAVY_DEPS = ("calcsheet", "sympy", "latex2mathml")

THRESHOLDS = [150, 50]

# The division this export actually falls into, and the row governing each tier.
# (key, label, member ends, |Vz| kN, ref)
TIERS = [
    ("T1", "[150, ∞) kN", 24, 297.175507, "RFEM 10103/1578 @ 6.15 m · LK67"),
    ("T2", "[50, 150) kN", 97, 144.104507, "RFEM 10105/1933 @ 0 m · LK80"),
    ("T3", "[0, 50) kN", 63, 48.985149, "RFEM 10112/1943 @ 5.1 m · LK3"),
]
VZ_ROWS = 184

# η per tier, to full double precision. The shared strength is
# 1.75 · 0.90 · 2.50 / 1.30 and the shared area 24200 mm².
ETA = {
    "T1": 405.4342480388299,
    "T2": 196.60066545979276,
    "T3": 66.83006029122393,
}
SIGMA = {
    "T1": 12.279979628099174,
    "T2": 5.9547316942148765,
    "T3": 2.0241797107438016,
}

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


def _result():
    """The card's own ``Result`` — fed exactly as the graph feeds it."""
    import grouping
    import rfem
    import sheet
    import sources
    from beam_bearing_pressure_tiered import EXPORT_CSV, INPUTS_JSON, build_graph

    card = next(
        n for n in build_graph().to_dict()["nodes"] if n["type"] == "sheet.group_card"
    )
    data = sources.read_json(str(INPUTS_JSON))
    ends = rfem.member_ends(rfem.read_extrema(str(EXPORT_CSV)), component="Vz")
    groups = grouping.group(ends, sources.pick(data, "grouping"))

    sockets = [s["name"] for s in sheet.formula_free_symbols(card["inputs"]["formulas"])]
    values = {
        key: (groups if key == "F_c90d" else sources.pick(data, key)) for key in sockets
    }
    formulas, checks, _ = sheet._expand_for_groups(
        sheet.parse_formulas(card["inputs"]["formulas"]),
        sheet.parse_checks(card["inputs"]["checks"]),
        "F_c90d",
        groups["groups"],
    )
    return sheet._evaluate_parsed(
        card["inputs"]["title"],
        card["inputs"]["as_of"],
        formulas,
        checks,
        card["inputs"]["precision"],
        sheet._group_values(values, "F_c90d", groups["groups"]),
    )


# -- the graph's shape (no heavy deps needed) ---------------------------------


def test_the_population_arc_meets_the_grouping_rule_at_one_node():
    from beam_bearing_pressure_tiered import build_graph

    doc = build_graph().to_dict()
    assert [n["type"] for n in doc["nodes"]] == [
        "rfem.read_extrema",
        "rfem.member_ends",
        "sources.read_json",
        "sources.pick",  # the grouping rule
        "grouping.group",
        "sources.write_json",
        *["sources.pick"] * 8,
        "sheet.group_card",
    ]
    keys = [n["inputs"]["key"] for n in doc["nodes"] if n["type"] == "sources.pick"]
    assert keys == ["grouping", *GIVENS]  # the rule is read like any other given


def test_the_force_comes_from_the_groups_and_the_other_eight_from_json():
    from beam_bearing_pressure_tiered import build_graph

    edges = _edge_set(build_graph())
    assert ("read_extrema", "result", "member_ends", "table") in edges
    assert ("member_ends", "result", "group", "population") in edges
    assert ("pick", "result", "group", "config") in edges
    assert ("group", "result", "group_card", "F_c90d") in edges
    for node_id, symbol in zip([f"pick_{n}" for n in range(2, 10)], GIVENS):
        assert ("read_json", "result", node_id, "data") in edges
        assert (node_id, "result", "group_card", symbol) in edges
    # …and nothing else feeds F_c90d.
    assert not any(
        e[2] == "group_card" and e[3] == "F_c90d" and e[0] != "group" for e in edges
    )


def test_the_artifact_hangs_off_the_grouping_not_between_it_and_the_card():
    """The grouping stays pure; the card can be fed without writing anything."""
    from beam_bearing_pressure_tiered import build_graph

    edges = _edge_set(build_graph())
    assert ("group", "result", "write_json", "data") in edges
    assert not any(e[0] == "write_json" for e in edges)  # a leaf
    assert build_graph().output == {"node": "group_card", "socket": "result"}


def test_the_grouping_rule_lives_in_the_existing_inputs_file():
    """One document, one `sources.pick` — not a second file to keep in sync."""
    from beam_bearing_pressure_tiered import INPUTS_JSON

    data = json.loads(INPUTS_JSON.read_text(encoding="utf-8"))
    assert list(data) == ["grouping", *GIVENS]
    assert data["grouping"] == {
        "strategy": "tiered",
        "params": {"thresholds": THRESHOLDS},
    }
    assert "F_c90d" not in data  # still derived, still one source of truth
    assert data["l_1"]["value"] is None  # the empty given survives the move


def test_the_calculation_is_unchanged_from_the_single_group_example():
    """Same literals, same check, same title, same as_of, same precision."""
    from beam_bearing_pressure_rfem import build_graph as single_graph
    from beam_bearing_pressure_tiered import build_graph

    def card_of(graph, node_type):
        return next(
            n for n in graph.to_dict()["nodes"] if n["type"] == node_type
        )["inputs"]

    theirs = card_of(single_graph(), "sheet.calc_card")
    ours = card_of(build_graph(), "sheet.group_card")
    assert ours["formulas"] == theirs["formulas"]
    assert ours["checks"] == theirs["checks"]
    assert ours["title"] == theirs["title"] == "Support pressure without reinforcement"
    assert ours["as_of"] == theirs["as_of"] == "2025-07-02"
    assert ours["precision"] == theirs["precision"] == 5


def test_the_selection_policy_is_still_one_literal_on_one_node():
    from beam_bearing_pressure_tiered import build_graph

    selector = next(
        n for n in build_graph().to_dict()["nodes"] if n["type"] == "rfem.member_ends"
    )
    assert selector["inputs"] == {"component": "Vz"}


def test_the_write_destination_stays_relative_in_the_graph():
    from beam_bearing_pressure_tiered import build_graph

    writer = next(
        n for n in build_graph().to_dict()["nodes"] if n["type"] == "sources.write_json"
    )
    assert writer["inputs"] == {"path": "groups.json"}


# -- the numbers, one tier at a time -------------------------------------------


@needs_sym_extra
def test_graph_loads_binds_and_runs_end_to_end(run_dir):
    from beam_bearing_pressure_tiered import build_graph

    graph = build_graph()
    validate_graph(graph.to_dict())
    result = run(graph)

    record = result.value("group")
    assert record["strategy"] == "tiered"
    assert record["params"] == {"thresholds": THRESHOLDS}
    assert record["unit"] == "kN" and record["count"] == VZ_ROWS
    assert [
        (g["key"], g["label"], g["count"], g["governing"]["value"], g["governing"]["ref"])
        for g in record["groups"]
    ] == TIERS


@needs_sym_extra
def test_the_tiers_partition_the_population(run_dir):
    from beam_bearing_pressure_tiered import build_graph

    record = run(build_graph()).value("group")
    assert sum(g["count"] for g in record["groups"]) == VZ_ROWS
    refs = [ref for g in record["groups"] for ref in g["member_refs"]]
    assert len(refs) == len(set(refs)) == VZ_ROWS


@needs_sym_extra
def test_the_single_strategy_would_return_the_first_tiers_force(run_dir):
    """The example this one extends designs for exactly T1's number."""
    import grouping
    import rfem
    from beam_bearing_pressure_tiered import EXPORT_CSV

    ends = rfem.member_ends(rfem.read_extrema(str(EXPORT_CSV)), component="Vz")
    (whole,) = grouping.apply_strategy("single", ends, {})
    assert whole.governing["value"] == TIERS[0][3] == 297.175507
    assert whole.governing["ref"] == TIERS[0][4]


@needs_sym_extra
def test_the_shared_geometry_is_computed_once_not_once_per_tier():
    """All tiers share one geometry — the card says so by not repeating it."""
    values = _result().values

    assert values["l_l"] == 0.0
    assert values["l_r"] == 30.0
    assert values["l_ef"] == 110.0
    assert values["A_ef"] == 24200.0
    assert values["f_c90d"] == 1.7307692307692306
    for key in ("T1", "T2", "T3"):
        assert f"l_ef_{key}" not in values
        assert f"A_ef_{key}" not in values
        assert f"f_c90d_{key}" not in values


@needs_sym_extra
def test_every_computed_value_individually():
    values = _result().values

    for key, _label, _count, force, _ref in TIERS:
        assert values[f"F_c90d_{key}"] == force
        assert values[f"sigma_c90d_{key}"] == SIGMA[key]
        assert values[f"eta_{key}"] == ETA[key]


@needs_sym_extra
def test_each_tier_gets_a_count_row_and_a_force_row_citing_its_export_row():
    """Provenance reaches the card per tier, not just for the worst case."""
    rows = {row.symbol: row for row in _result().inputs}

    for key, label, count, force, ref in TIERS:
        assert (rows[f"n_{key}"].value_text, rows[f"n_{key}"].unit) == (str(count), "ends")
        assert rows[f"n_{key}"].ref == label
        assert rows[f"F_c90d_{key}"].value == force
        assert rows[f"F_c90d_{key}"].unit == "kN"
        assert rows[f"F_c90d_{key}"].ref == ref
    # The eight shared givens still cite their code clauses, once each.
    assert rows["gamma_M"].ref == "DIN EN 1995-1-1/NA NDP 2.4.1(1)P"
    assert (rows["l_1"].value_text, rows["l_1"].unit) == ("–", "mm")


@needs_sym_extra
def test_two_tiers_fail_and_one_passes_on_the_one_card():
    result = _result()

    assert [(c.expr, c.passed) for c in result.checks] == [
        ("eta_T1 < 100", False),
        ("eta_T2 < 100", False),
        ("eta_T3 < 100", True),
    ]
    assert [c.description for c in result.checks] == [
        f"{label} — reinforcement of the support not required"
        for _key, label, *_rest in TIERS
    ]
    assert [c.utilisation for c in result.checks] == [ETA[k] for k in ("T1", "T2", "T3")]
    assert all(c.limit == 100.0 for c in result.checks)
    # A calc is valid only when every check passes; the worst tier governs.
    assert result.passed is False
    assert result.governing == ("eta_T1 < 100", ETA["T1"])


@needs_sym_extra
def test_a_failing_tier_does_not_fail_the_run(run_dir):
    """ADR 0016: the verdict is card content — no assertion node, no raise."""
    from beam_bearing_pressure_tiered import build_graph

    result = run(build_graph())
    assert set(result.outputs) == {
        "read_extrema", "member_ends", "read_json", "pick", "group", "write_json",
        *[f"pick_{n}" for n in range(2, 10)], "group_card",
    }
    assert "Overall <b>FAIL</b>" in result.value("group_card", "result")


@needs_sym_extra
def test_output_html_carries_every_tiers_provenance_and_verdict(run_dir):
    from beam_bearing_pressure_tiered import build_graph

    graph = build_graph()
    html = run(graph).value(graph.output["node"], graph.output["socket"])

    assert isinstance(html, str) and html.startswith("<!doctype html>")
    assert "Support pressure without reinforcement" in html
    for _key, label, count, _force, ref in TIERS:
        assert f'<span class="ref">{ref}</span>' in html
        assert f'{count}&nbsp;<span class="unit">ends</span>' in html
        assert f'<span class="ref">{label}</span>' in html
    assert '297.18&nbsp;<span class="unit">kN</span>' in html
    assert '405.43&nbsp;<span class="unit">%</span>' in html
    assert '66.83&nbsp;<span class="unit">%</span>' in html
    assert 'badge--fail">FAIL' in html and 'badge--pass">PASS' in html
    assert 'class="status status--fail"' in html and "Overall <b>FAIL</b>" in html
    # The division itself is on the artifact, not only in inputs.json.
    assert "thresholds=[150, 50]" in html and "184 member ends in 3 groups" in html
    # Self-contained, like every card in this repo.
    assert "http" not in html
    assert "<script" not in html and "<link" not in html and "@import" not in html


# -- the written artifact -----------------------------------------------------


@needs_sym_extra
def test_the_run_writes_the_division_into_the_run_directory(run_dir):
    from beam_bearing_pressure_tiered import build_graph

    result = run(build_graph())

    written = run_dir / "groups.json"
    assert result.value("write_json") == str(written)
    record = json.loads(written.read_text(encoding="utf-8"))
    assert record == result.value("group")
    assert [g["key"] for g in record["groups"]] == ["T1", "T2", "T3"]
    # Valid JSON, not Python's `Infinity`: the open tier's upper bound is null.
    assert record["groups"][0]["extra"]["upper"] is None
    assert "Infinity" not in written.read_text(encoding="utf-8")


def test_the_artifact_is_gitignored_and_not_committed():
    directory = example_dir(ENTRY)
    ignored = (directory / ".gitignore").read_text(encoding="utf-8")

    assert "groups.json" in ignored
    tracked = subprocess.run(
        ["git", "ls-files", "groups.json"],
        cwd=directory, capture_output=True, text=True, check=True,
    )
    assert tracked.stdout.strip() == ""


def test_the_export_is_read_next_door_and_not_copied():
    """A third copy of the same 1104 rows is a third thing that can drift."""
    from beam_bearing_pressure_tiered import EXPORT_CSV

    directory = example_dir(ENTRY)
    assert EXPORT_CSV == example_dir("beam_bearing_pressure_rfem") / "export.csv"
    assert EXPORT_CSV.is_file()
    assert not (directory / "export.csv").exists()
    assert sorted(p.name for p in directory.iterdir() if p.is_file()) == [
        ".gitignore", f"{ENTRY}.py", "inputs.json",
    ]


@needs_sym_extra
def test_graph_declares_environment_dependencies():
    from beam_bearing_pressure_tiered import DEPENDENCIES, build_graph

    graph = build_graph()
    assert graph.environment is not None
    assert graph.environment["network"] == "none"
    assert graph.environment["dependencies"] == DEPENDENCIES


@needs_sym_extra
def test_graph_exports_python(run_dir):
    from beam_bearing_pressure_tiered import build_graph

    script = to_python(build_graph())
    namespace: dict = {}
    exec(compile(script, "<exported>", "exec"), namespace)  # noqa: S102 - trusted, generated
    graph = build_graph()
    assert namespace["_group_card"] == run(graph).value(
        graph.output["node"], graph.output["socket"]
    )


# -- served + the bijection ---------------------------------------------------


def test_the_entry_is_discoverable_by_the_picker():
    from server.entries import EntryCatalog

    entries = {e["id"]: e for e in EntryCatalog().discover().entries()}
    assert entries[ENTRY]["status"] == "ok", entries[ENTRY].get("error")
    assert entries[ENTRY]["title"] == "Beam bearing pressure tiered"


def test_served_node_ids_are_the_authored_variable_names():
    from server.demo import load_graph, make_workspace

    graph = load_graph(ENTRY, make_workspace(ENTRY))
    assert [n["id"] for n in graph["nodes"]] == [
        "forces", "ends", "inputs", "grouping", "groups", "artifact",
        "a_1", "l", "l_1", "b", "k_c90", "k_mod", "f_c90k", "gamma_M", "card",
    ]
    assert graph["output"] == {"node": "card", "socket": "result"}
    # Served pristine: relative paths, no absolute machine path anywhere.
    assert graph["nodes"][0]["inputs"]["path"] == (
        "../beam_bearing_pressure_rfem/export.csv"
    )
    assert graph["nodes"][2]["inputs"]["path"] == "inputs.json"
    assert graph["nodes"][5]["inputs"]["path"] == "groups.json"


def test_the_module_is_a_byte_exact_fixed_point_of_the_bijection():
    """Parsing and saving it unedited rewrites nothing (ADR 0004 D5 / 0020)."""
    import beam_bearing_pressure_tiered  # noqa: F401 - registers the node types

    text = _module_text()
    graph = from_composite(text, DEFAULT_REGISTRY, module_name=ENTRY)
    written = compute_writeback(text, graph, DEFAULT_REGISTRY, ENTRY)
    assert written.strategy == "unchanged"
    assert written.text == text


def test_the_wiring_statements_are_already_in_the_emitters_canonical_form():
    import ast

    import beam_bearing_pressure_tiered  # noqa: F401 - registers the node types
    from engine.composite import composite_call_names, wiring_lines

    text = _module_text()
    graph = from_composite(text, DEFAULT_REGISTRY, module_name=ENTRY)
    call_names = composite_call_names(ast.parse(text), ENTRY)

    emitted = wiring_lines(graph, DEFAULT_REGISTRY, call_names=call_names)
    card = next(line for line in emitted if line.lstrip().startswith("card = "))
    assert card in text
    assert next(line for line in emitted if "member_ends(" in line) in text
    assert next(line for line in emitted if "group(" in line) in text
    for line in emitted:
        if "pick(" in line:
            assert line in text


def test_changing_the_strategy_is_an_inputs_edit_not_a_graph_edit(tmp_path):
    """Swapping 'tiered' for 'single' moves no wire and adds no node."""
    import grouping
    import rfem
    from beam_bearing_pressure_tiered import EXPORT_CSV, build_graph

    ends = rfem.member_ends(rfem.read_extrema(str(EXPORT_CSV)), component="Vz")
    shape = [n["type"] for n in build_graph().to_dict()["nodes"]]

    one = grouping.group(ends, {"strategy": "single"})
    three = grouping.group(
        ends, {"strategy": "tiered", "params": {"thresholds": THRESHOLDS}}
    )
    assert len(one["groups"]) == 1 and len(three["groups"]) == 3
    assert [n["type"] for n in build_graph().to_dict()["nodes"]] == shape


def test_an_edit_and_its_revert_restore_the_file_byte_for_byte():
    import beam_bearing_pressure_tiered  # noqa: F401 - registers the node types

    text = _module_text()

    edited = from_composite(text, DEFAULT_REGISTRY, module_name=ENTRY)
    next(n for n in edited.nodes if n.id == "ends").inputs["component"] = "Vy"
    patched = compute_writeback(text, edited, DEFAULT_REGISTRY, ENTRY)
    assert patched.strategy == "patched" and patched.changed_ids == ["ends"]
    assert "component='Vy'" in patched.text

    reverted = from_composite(patched.text, DEFAULT_REGISTRY, module_name=ENTRY)
    next(n for n in reverted.nodes if n.id == "ends").inputs["component"] = "Vz"
    assert compute_writeback(patched.text, reverted, DEFAULT_REGISTRY, ENTRY).text == text


# -- the two examples it sits beside are untouched ------------------------------


def test_the_two_earlier_examples_are_byte_untouched():
    """`git diff` against the base must be empty for both directories."""
    root = example_dir(ENTRY).parents[1]
    diff = subprocess.run(
        [
            "git", "diff", "--name-only", "HEAD", "--",
            "examples/beam_bearing_pressure", "examples/beam_bearing_pressure_rfem",
        ],
        cwd=root, capture_output=True, text=True, check=True,
    )
    assert diff.stdout.strip() == ""


def test_the_single_group_example_still_designs_for_the_overall_maximum():
    from beam_bearing_pressure_rfem import INPUTS_JSON as RFEM_INPUTS

    data = json.loads(RFEM_INPUTS.read_text(encoding="utf-8"))
    assert "grouping" not in data  # the earlier example learned nothing new
    assert list(data) == GIVENS
