"""Bijection tests for ``to_composite`` / ``from_composite`` (ADR 0004).

The core deliverable: prove Graph ⟷ wiring-composite is an identity round-trip
**modulo layout** (positions) and wiring-line formatting. Covers a real traced
graph, a multi-output source, a positional-only node, source idempotence, a
hand-written composite that drives real execution, control-flow rejection, and
the variable-name-is-id invariant.

Self-contained toy node types (multi-output ``split``, positional-only ``diff``)
are registered into a local registry, mirroring ``test_engine.py``.
"""

from __future__ import annotations

import pytest

import calc  # noqa: F401 - registers calc.* node types into DEFAULT_REGISTRY
import sources  # noqa: F401 - registers sources.* node types
from engine import (
    DEFAULT_REGISTRY,
    EngineError,
    Graph,
    NodeRegistry,
    from_composite,
    run,
    to_composite,
)

from minimal import build_graph


# -- toy node functions (multi-output + positional-only) -------------------


def split(x: int = 0) -> dict:
    return {"lo": x, "hi": x + 1}


def diff(a, b, /) -> int:  # positional-only
    return a - b


def scale(value: int, factor: int = 2) -> int:
    return value * factor


def note(text: str = "", label: str = "note", n: int = 0) -> str:  # multi-line str param
    return f"{label}:{text}:{n}"


@pytest.fixture
def toy_registry() -> NodeRegistry:
    reg = NodeRegistry()
    reg.register(split, outputs=["lo", "hi"])
    reg.register(diff)
    reg.register(scale)
    reg.register(note)
    return reg


# -- comparison helper: graph equality modulo layout -----------------------


def _canonical(graph: Graph) -> dict:
    """A layout-independent, order-independent view of a graph for equality.

    Nodes compared by id (positions dropped), edges as an unordered set, plus
    the output socket — exactly the bijective content per ADR 0004.
    """
    d = graph.to_dict()
    nodes = {n["id"]: {"type": n["type"], "inputs": n["inputs"]} for n in d["nodes"]}
    edges = frozenset(tuple(sorted(e.items())) for e in d["edges"])
    return {"nodes": nodes, "edges": edges, "output": d["output"]}


def _assert_roundtrip_identity(graph: Graph, registry: NodeRegistry) -> None:
    restored = from_composite(to_composite(graph, registry), registry)
    assert _canonical(restored) == _canonical(graph)


# -- graph-level round-trip identity ---------------------------------------


def test_roundtrip_identity_traced_minimal_graph():
    # A real traced graph over registered node types (read -> total/average ->
    # render), including a str widget literal (the CSV path).
    graph = build_graph()
    _assert_roundtrip_identity(graph, DEFAULT_REGISTRY)


def test_roundtrip_identity_multi_output_source(toy_registry: NodeRegistry):
    # split has two output sockets, wired via x["lo"] / x["hi"].
    graph = Graph()
    graph.add("s", f"{__name__}.split", inputs={"x": 5})
    graph.add("lo_scaled", f"{__name__}.scale")
    graph.add("hi_scaled", f"{__name__}.scale", inputs={"factor": 3})
    graph.connect("s", "lo", "lo_scaled", "value")
    graph.connect("s", "hi", "hi_scaled", "value")
    graph.output = {"node": "hi_scaled", "socket": "result"}
    _assert_roundtrip_identity(graph, toy_registry)


def test_roundtrip_identity_positional_only(toy_registry: NodeRegistry):
    # diff(a, b, /) — both params positional-only, emitted positionally.
    graph = Graph()
    graph.add("s", f"{__name__}.split", inputs={"x": 10})
    graph.add("d", f"{__name__}.diff")
    graph.connect("s", "hi", "d", "a")
    graph.connect("s", "lo", "d", "b")
    graph.output = {"node": "d", "socket": "result"}
    _assert_roundtrip_identity(graph, toy_registry)

    # And the emitted call is truly positional (no a=/b= keywords).
    source = to_composite(graph, toy_registry)
    assert "d = diff(s['hi'], s['lo'])" in source


def test_roundtrip_identity_alias_collision(toy_registry: NodeRegistry):
    # A node id equal to a type's call name must not shadow the function: the
    # type imports under an alias and the body calls the alias.
    graph = Graph()
    graph.add("s", f"{__name__}.split", inputs={"x": 1})
    graph.add("diff", f"{__name__}.diff")  # id collides with the `diff` import
    graph.connect("s", "hi", "diff", "a")
    graph.connect("s", "lo", "diff", "b")
    graph.output = {"node": "diff", "socket": "result"}

    source = to_composite(graph, toy_registry)
    assert "import diff as diff_2" in source
    assert "diff = diff_2(" in source
    _assert_roundtrip_identity(graph, toy_registry)


# -- source idempotence (byte-stable emit) ---------------------------------


def test_source_idempotence_minimal():
    source = to_composite(build_graph())
    assert to_composite(from_composite(source)) == source


def test_source_idempotence_multi_output(toy_registry: NodeRegistry):
    graph = Graph()
    graph.add("s", f"{__name__}.split", inputs={"x": 5})
    graph.add("d", f"{__name__}.diff")
    graph.connect("s", "lo", "d", "a")
    graph.connect("s", "hi", "d", "b")
    graph.output = {"node": "d", "socket": "result"}

    source = to_composite(graph, toy_registry)
    assert to_composite(from_composite(source, toy_registry), toy_registry) == source


# -- parse a hand-written composite and run it -----------------------------


HANDWRITTEN = '''\
from engine import main
from sources import mock_api
from calc import average, median, render_summary


@main
def report():
    values = mock_api(dataset="readings")
    avg = average(values=values)
    med = median(values=values)
    card = render_summary(title="Readings", average=avg, median=med)
    return card
'''


def test_parse_handwritten_composite_drives_execution():
    graph = from_composite(HANDWRITTEN, DEFAULT_REGISTRY)

    # Structure parsed as expected.
    assert {n.id for n in graph.nodes} == {"values", "avg", "med", "card"}
    assert graph.node("values").type == "sources.mock_api"
    assert graph.node("values").inputs == {"dataset": "readings"}
    assert graph.output == {"node": "card", "socket": "result"}

    # The parsed graph really runs (mock readings: [10,20,30,40]).
    result = run(graph)
    assert result.value("avg") == 25.0
    assert result.value("med") == 25.0
    html = result.value("card", "result")
    assert html.startswith("<div")
    assert "25" in html


def test_parse_then_emit_roundtrips_handwritten():
    graph = from_composite(HANDWRITTEN, DEFAULT_REGISTRY)
    reparsed = from_composite(to_composite(graph), DEFAULT_REGISTRY)
    assert _canonical(reparsed) == _canonical(graph)


# -- variable-name ids -----------------------------------------------------


def test_node_ids_equal_source_variable_names():
    graph = from_composite(HANDWRITTEN, DEFAULT_REGISTRY)
    # ids are exactly the composite's assignment variable names.
    assert sorted(n.id for n in graph.nodes) == ["avg", "card", "med", "values"]
    # positions are excluded from the bijection (layout is a sidecar concern).
    assert all(n.position is None for n in graph.nodes)


# -- rejection of non-dataflow constructs (ADR 0004 D7) --------------------


def test_rejects_if_statement():
    source = '''\
from engine import main
from calc import total


@main
def bad():
    a = total(values=[1, 2])
    if a:
        b = total(values=[3])
    return a
'''
    with pytest.raises(EngineError, match="D7"):
        from_composite(source, DEFAULT_REGISTRY)


def test_rejects_for_loop():
    source = '''\
from engine import main
from calc import total


@main
def bad():
    for i in range(3):
        a = total(values=[i])
    return a
'''
    with pytest.raises(EngineError, match="D7"):
        from_composite(source, DEFAULT_REGISTRY)


def test_rejects_tuple_target():
    source = '''\
from engine import main
from calc import total


@main
def bad():
    a, b = total(values=[1]), total(values=[2])
    return a
'''
    with pytest.raises(EngineError, match="D7"):
        from_composite(source, DEFAULT_REGISTRY)


# -- multi-line string literals: block form (ADR 0020) ---------------------
#
# The emitted spelling of a multi-line value is parenthesized implicit string
# concatenation — one repr()-escaped fragment per line, each carrying its own
# '\n' — inside an expanded call (D1/D3). These are additions: the tests above
# pin the unchanged single-line behaviour and pass untouched.

CALC = "r = F_max / C_min  # demand / capacity\nU = 100 * r [%]  # utilisation"

# Values that make naive multi-line spellings (triple quotes, dedent) go wrong.
TORTURE_VALUES = {
    "trailing_newline": "a\nb\n",
    "only_newline": "\n",
    "crlf": "a\r\nb\r\n",
    "crlf_trailing": "first\r\nsecond\r\n",
    "embedded_quotes": "he said \"hi\"\nshe said 'bye'\nboth \"'\n",
    "backslashes_latex": "\\nu = \\frac{a}{b}\\\\\nE = m c^2  # \\nu, not a newline",
    "triple_quote": 'a """ b\nc """',
    "ends_with_quote": "ends with a quote'\nand a double \"\n",
    "ends_with_backslash": "path C:\\\\tmp\\\\\nnext line",
    "tabs_and_cr": "a\tb\rc\nd\te",
    "blank_lines": "first\n\n\nlast",
}


def _note_graph(value: str, **extra) -> Graph:
    graph = Graph()
    graph.add("n", f"{__name__}.note", inputs={"text": value, **extra})
    graph.output = {"node": "n", "socket": "result"}
    return graph


def test_multiline_literal_emits_as_parenthesized_fragments(toy_registry: NodeRegistry):
    source = to_composite(_note_graph(CALC, label="calc"), toy_registry)
    assert (
        "    n = note(\n"
        "        text=(\n"
        "            'r = F_max / C_min  # demand / capacity\\n'\n"
        "            'U = 100 * r [%]  # utilisation'\n"
        "        ),\n"
        "        label='calc',\n"
        "    )\n"
    ) in source
    # One fragment per value line, each ending in its own escaped newline but
    # the last — and no triple quotes anywhere.
    assert '"""' not in source and "'''" not in source


def test_multiline_literal_is_one_constant_for_the_parser(toy_registry: NodeRegistry):
    # CPython concatenates adjacent string literals at parse time, which is why
    # the parse side needs no change at all (ADR 0020 D4).
    import ast

    source = to_composite(_note_graph(CALC), toy_registry)
    call = next(
        s.value
        for s in ast.walk(ast.parse(source))
        if isinstance(s, ast.Assign) and isinstance(s.value, ast.Call)
    )
    text_arg = next(kw.value for kw in call.keywords if kw.arg == "text")
    assert isinstance(text_arg, ast.Constant) and text_arg.value == CALC


@pytest.mark.parametrize("value", TORTURE_VALUES.values(), ids=list(TORTURE_VALUES))
def test_multiline_roundtrip_is_byte_exact(value: str, toy_registry: NodeRegistry):
    graph = _note_graph(value)
    _assert_roundtrip_identity(graph, toy_registry)
    # The parsed-back value is the SAME BYTES — no dedent, no strip, no added or
    # lost trailing newline, no \r\n normalization.
    restored = from_composite(to_composite(graph, toy_registry), toy_registry)
    assert restored.node("n").inputs["text"] == value


@pytest.mark.parametrize("value", TORTURE_VALUES.values(), ids=list(TORTURE_VALUES))
def test_multiline_emit_is_idempotent(value: str, toy_registry: NodeRegistry):
    source = to_composite(_note_graph(value), toy_registry)
    once = to_composite(from_composite(source, toy_registry), toy_registry)
    assert once == source
    # emit(parse(emit(x))) == emit(x), and it stays stable a second time round.
    assert to_composite(from_composite(once, toy_registry), toy_registry) == source


def test_single_line_values_keep_plain_repr(toy_registry: NodeRegistry):
    source = to_composite(_note_graph("Capacity check", label="t"), toy_registry)
    # One physical line, no parentheses grown around the value (non-negotiable 5).
    assert "    n = note(text='Capacity check', label='t')\n" in source
    assert source.count("\n    n = ") == 1


def test_a_long_single_line_value_does_not_expand(toy_registry: NodeRegistry):
    # The predicate is a newline, not a length heuristic (D2).
    long_value = "x" * 300
    source = to_composite(_note_graph(long_value), toy_registry)
    assert f"    n = note(text='{long_value}')\n" in source


def test_non_string_values_keep_container_repr(toy_registry: NodeRegistry):
    # A string nested in a container keeps container repr() — out of scope (D2).
    graph = Graph()
    graph.add("s", f"{__name__}.split", inputs={"x": 3})
    graph.output = {"node": "s", "socket": "lo"}
    source = to_composite(graph, toy_registry)
    assert "    s = split(x=3)\n" in source


def test_crossing_the_boundary_does_not_thrash(toy_registry: NodeRegistry):
    """A value oscillating across the newline boundary re-emits stably.

    Single → multi → single returns byte-identical source: representation is a
    pure function of the value, so nothing accumulates (D2/D6).
    """
    single = to_composite(_note_graph("one line"), toy_registry)
    multi = to_composite(_note_graph("one line\ntwo lines"), toy_registry)
    assert single != multi
    assert to_composite(_note_graph("one line"), toy_registry) == single
    assert to_composite(from_composite(multi, toy_registry), toy_registry) == multi
    # And back down: the block form leaves no residue behind.
    demoted = from_composite(multi, toy_registry)
    demoted.node("n").inputs["text"] = "one line"
    assert to_composite(demoted, toy_registry) == single


def test_only_the_multiline_argument_goes_block_form(toy_registry: NodeRegistry):
    source = to_composite(_note_graph(CALC, label="single", n=7), toy_registry)
    # Siblings stay ordinary reprs, one per line, in the expanded call.
    assert "        label='single',\n" in source
    assert "        n=7,\n" in source


def test_wired_reference_in_a_block_form_statement(toy_registry: NodeRegistry):
    graph = Graph()
    graph.add("s", f"{__name__}.split", inputs={"x": 1})
    graph.add("n", f"{__name__}.note", inputs={"text": CALC})
    graph.connect("s", "lo", "n", "n")
    graph.output = {"node": "n", "socket": "result"}

    source = to_composite(graph, toy_registry)
    assert "        n=s['lo'],\n" in source
    _assert_roundtrip_identity(graph, toy_registry)


# -- the parser keeps accepting every hand-written spelling (D4) ------------


def _handwritten(argument: str) -> str:
    return (
        "from engine import main\n"
        f"from {__name__} import note\n"
        "\n\n"
        "@main\n"
        "def report():\n"
        f"    n = note(text={argument})\n"
        "    return n\n"
    )


def test_parser_accepts_every_handwritten_spelling(toy_registry: NodeRegistry):
    escaped = _handwritten(repr(CALC))
    concatenated = _handwritten(
        "(\n"
        "        'r = F_max / C_min  # demand / capacity\\n'\n"
        "        'U = 100 * r [%]  # utilisation'\n"
        "    )"
    )
    # A triple-quoted literal takes its content literally: to denote the same
    # value its lines must start at column 0 (the reason it is not the emitted
    # form, ADR 0020 Option 1).
    triple = _handwritten(
        '"""r = F_max / C_min  # demand / capacity\nU = 100 * r [%]  # utilisation"""'
    )
    for label, source in [
        ("escaped", escaped),
        ("implicit concatenation", concatenated),
        ("triple-quoted", triple),
    ]:
        graph = from_composite(source, toy_registry)
        assert graph.node("n").inputs["text"] == CALC, label
        # All three denote one value, so all three normalize to the same bytes
        # the first time the statement is re-emitted.
        assert to_composite(graph, toy_registry) == to_composite(
            from_composite(escaped, toy_registry), toy_registry
        ), label


def test_dedent_argument_is_still_rejected(toy_registry: NodeRegistry):
    source = (
        "from engine import main\n"
        "import textwrap\n"
        f"from {__name__} import note\n"
        "\n\n"
        "@main\n"
        "def report():\n"
        '    n = note(text=textwrap.dedent("""a\\nb"""))\n'
        "    return n\n"
    )
    with pytest.raises(EngineError, match="literal"):
        from_composite(source, toy_registry)


def test_unknown_type_names_the_node():
    source = '''\
from engine import main
from calc import bogus_node


@main
def bad():
    x = bogus_node(values=[1])
    return x
'''
    with pytest.raises(EngineError, match="x"):
        from_composite(source, DEFAULT_REGISTRY)
