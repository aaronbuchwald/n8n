"""Tests for the ``sym`` node pack and the symbolic example.

Covers, in order:

* the **lazy-import contract** — ``import sym`` + listing every node spec works
  in a subprocess where sympy/handcalcs/forallpeople/latex2mathml are blocked;
* the dependency-free nodes (plain Python, always run);
* each library's nodes (skipped cleanly via ``importorskip`` when a dep is
  missing — but in CI/dev the ``sym`` extra is installed, so they run);
* the example graph end-to-end: correct numbers, self-contained MathML HTML
  (no ``http``/CDN references), the ADR 0003 environment descriptor, and the
  ``to_python`` export.

Run with:  uv run --extra dev --extra sym python -m pytest -q
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

import sym
from engine import run, to_python, validate_graph

HEAVY_DEPS = ("sympy", "handcalcs", "forallpeople", "latex2mathml")


# -- lazy-import contract ----------------------------------------------------


def test_import_and_spec_listing_need_no_heavy_deps():
    """``import sym`` + spec listing must work with every heavy dep blocked.

    The deps *are* installed in this venv, so laziness is proven in a child
    process with an import hook that refuses them: if any node body's library
    leaked to module top level, the import itself would fail.
    """
    script = textwrap.dedent(
        """
        import sys

        BLOCKED = {"sympy", "handcalcs", "forallpeople", "latex2mathml"}

        class _Blocker:
            def find_spec(self, name, path=None, target=None):
                if name.split(".")[0] in BLOCKED:
                    raise ImportError(f"blocked heavy dep: {name}")
                return None

        sys.meta_path.insert(0, _Blocker())

        import sym  # must not touch any blocked module

        specs = [n.spec for n in sym.NODES]
        assert len(specs) == 12, specs
        assert all(s["id"].startswith("sym.") for s in specs)
        assert all(s["outputs"] for s in specs)
        loaded = {m.split(".")[0] for m in sys.modules}
        assert not (loaded & BLOCKED), loaded & BLOCKED
        print("lazy-ok")
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stderr
    assert "lazy-ok" in proc.stdout


def test_every_node_has_a_registered_spec():
    ids = {n.spec["id"] for n in sym.NODES}
    assert len(ids) == len(sym.NODES) == 12
    assert "sym.typeset_calc" in ids
    # typeset_calc is the pack's one multi-output node.
    typeset = next(n.spec for n in sym.NODES if n.spec["id"] == "sym.typeset_calc")
    assert [o["name"] for o in typeset["outputs"]] == ["latex", "results"]


def test_parse_expr_declares_math_widget():
    """parse_expr's 'text' input declares the math widget (ADR 0005 B)."""
    parse_expr_spec = next(n.spec for n in sym.NODES if n.spec["id"] == "sym.parse_expr")
    text_input = next(inp for inp in parse_expr_spec["inputs"] if inp["name"] == "text")
    assert text_input["widget"] is not None
    assert text_input["widget"]["kind"] == "math"
    assert text_input["widget"].get("config", {}).get("syntax") == "sympy"


# -- dependency-free nodes ---------------------------------------------------


def test_multiply_and_pick_and_join_are_plain_python():
    assert sym.multiply(3.0, 4.0, factor=0.5) == 6.0
    assert sym.pick([10, 20, 30], 1) == 20
    assert sym.join_text("a", "", "c", sep=" | ") == "a | c"


def test_describe_formats_floats_and_lists():
    assert sym.describe(0.30000000000004, "residual") == "residual = 0.3"
    assert sym.describe([2, 3], "roots") == "roots = 2, 3"
    assert sym.describe(1.5) == "1.5"


def test_render_math_card_escapes_text_inputs():
    out = sym.render_math_card("</h1><script>x</script>", "", "<b>bold</b>")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out and "&lt;b&gt;" in out


def test_render_math_card_refuses_non_mathml_markup():
    for bad in ('<script>1</script>', '<a href="x">y</a>', '<img src="x">', "http://cdn"):
        with pytest.raises(ValueError):
            sym.render_math_card("t", bad, "")


# -- SymPy nodes -------------------------------------------------------------


def test_solve_quadratic_and_verify_numerically():
    pytest.importorskip("sympy")
    expr = sym.parse_expr("x**2 - 5*x + 6")
    roots = sym.solve_for(expr, "x")
    assert [float(r) for r in roots] == [2.0, 3.0]
    residual = sym.evaluate_numeric(sym.substitute(expr, "x", sym.pick(roots, 0)))
    assert residual == 0.0


def test_parse_equation_form_and_solve():
    pytest.importorskip("sympy")
    # "lhs = rhs" strings become equations and solve as written.
    assert [float(r) for r in sym.solve_for("2*x + 1 = 7", "x")] == [3.0]


def test_evaluate_numeric_lambdifies_with_subs():
    pytest.importorskip("sympy")
    assert sym.evaluate_numeric("x**2 + y", {"x": 3.0, "y": 1.0}) == 10.0


def test_evaluate_numeric_missing_symbol_raises():
    pytest.importorskip("sympy")
    with pytest.raises(ValueError, match="x"):
        sym.evaluate_numeric("x + 1")


# -- forallpeople nodes ------------------------------------------------------


def test_quantity_carries_units_through_multiply():
    pytest.importorskip("forallpeople")
    mass = sym.quantity(2.0, "kg")
    speed = sym.quantity(3.0, "m/s")
    energy = sym.multiply(sym.multiply(speed, speed), mass, factor=0.5)
    assert float(energy) == 9.0
    assert "J" in str(energy)  # kg·m²/s² auto-reduces to joules


def test_quantity_parses_compound_units():
    pytest.importorskip("forallpeople")
    force = sym.quantity(4.0, "kg*m/s^2")
    assert float(force) == 4.0
    assert "N" in str(force)
    assert sym.quantity(1.5, "") == 1.5  # dimensionless -> plain float


def test_quantity_rejects_unknown_unit():
    pytest.importorskip("forallpeople")
    with pytest.raises(ValueError, match="furlong"):
        sym.quantity(1.0, "furlong")


# -- handcalcs + latex2mathml nodes -----------------------------------------


def test_typeset_calc_substitutes_values():
    pytest.importorskip("handcalcs")
    out = sym.typeset_calc("E_k = 1/2 * m * v**2", {"m": 2.0, "v": 3.0})
    assert out["results"]["E_k"] == 9.0
    # The LaTeX shows symbolic form AND the substituted numbers.
    assert "E_{k}" in out["latex"]
    assert "2.000" in out["latex"] and "3.000" in out["latex"] and "9.000" in out["latex"]


def test_typeset_calc_rejects_bad_identifier():
    pytest.importorskip("handcalcs")
    with pytest.raises(ValueError, match="identifier"):
        sym.typeset_calc("a = b", {"b; import os": 1.0})


def test_latex_to_mathml_is_native_and_reference_free():
    pytest.importorskip("latex2mathml")
    mathml = sym.latex_to_mathml(r"$$\begin{aligned}a &= \frac{1}{2} &= 0.5\end{aligned}$$")
    assert mathml.startswith("<math")
    assert "</math>" in mathml
    assert "http" not in mathml and "xmlns" not in mathml


# -- the example graph, end-to-end ------------------------------------------


def _sym_deps_available() -> bool:
    for name in HEAVY_DEPS:
        try:
            __import__(name)
        except ImportError:
            return False
    return True


needs_sym_extra = pytest.mark.skipif(
    not _sym_deps_available(), reason="sym extra not installed"
)


@needs_sym_extra
def test_example_graph_runs_and_renders_self_contained_html():
    from symbolic import build_graph

    graph = build_graph()
    result = run(graph)

    # Numbers are right: roots 2/3, residual 0, energy 9 J.
    roots = result.value("solve_for")
    assert [float(r) for r in roots] == [2.0, 3.0]
    assert result.value("evaluate_numeric") == 0.0
    energy = result.value("multiply_2")
    assert float(energy) == 9.0
    assert result.value("typeset_calc", "results")["E_k"] == 9.0

    html = result.value(graph.output["node"], graph.output["socket"])
    assert isinstance(html, str) and html.startswith("<div")
    # Typeset math is present as native MathML.
    assert "<math" in html and "</math>" in html
    assert "roots = 2, 3" in html and "E_k = 9.000 J" in html
    # Self-contained: no external/CDN references of any kind.
    assert "http" not in html
    assert "<script" not in html and "<link" not in html and "@import" not in html


@needs_sym_extra
def test_example_graph_declares_environment_dependencies():
    from symbolic import DEPENDENCIES, build_graph

    graph = build_graph()
    assert graph.environment is not None
    assert graph.environment["network"] == "none"
    declared = {d["name"] for d in graph.environment["dependencies"]}
    assert declared == set(HEAVY_DEPS)
    assert graph.environment["dependencies"] == DEPENDENCIES
    # The descriptor round-trips through the schema validator.
    assert validate_graph(graph.to_dict()) == graph.to_dict()


@needs_sym_extra
def test_example_graph_exports_python():
    from symbolic import build_graph

    script = to_python(build_graph())
    assert "from sym import" in script
    assert "render_math_card" in script
