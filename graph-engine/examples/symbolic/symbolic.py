"""Symbolic math end-to-end, with the ``sym`` node pack.

Two small, generic calculations wired into one self-contained HTML card:

* **quadratic** — parse ``x**2 - 5*x + 6``, solve it symbolically (roots 2 and
  3), substitute the first root back in and evaluate numerically (residual 0);
* **kinetic energy** — attach real SI units (kg, m/s), carry them through
  ½·m·v² (auto-reducing to joules), and typeset the substituted steps with
  handcalcs → native MathML (zero-JS, CDN-free).

    parse_expr ─> solve_for ─> pick ─> substitute ─> evaluate_numeric ─┐
    quantity(kg) ── multiply ─┐                                        ├─> describe ×3 ─> join_text ─┐
    quantity(m/s) ┴─ multiply ┘ (E_k, in J) ───────────────────────────┘                             │
    typeset_calc ─> latex_to_mathml ── (MathML) ──────────────────────────────────> render_math_card ┘

The graph declares what it needs to run via the ADR 0003 ``environment``
descriptor (dependencies; no mounts; no network) — declarative today,
enforced by the C-stream runner later.

Run (the ``sym`` extra provides the libraries)::

    uv run --extra sym python examples/symbolic/symbolic.py
"""

from __future__ import annotations

from engine import main
from sym import (
    describe,
    evaluate_numeric,
    join_text,
    latex_to_mathml,
    multiply,
    parse_expr,
    pick,
    quantity,
    render_math_card,
    solve_for,
    substitute,
    typeset_calc,
)

# Kinetic-energy inputs: ½ · m · v² with m = 2 kg, v = 3 m/s → 9 J.
MASS_KG = 2.0
SPEED_M_S = 3.0

# What the graph needs to run — the ADR 0003 declarative descriptor. Versions
# match the `sym` extra in pyproject.toml (verified installable via uv).
DEPENDENCIES = [
    {"name": "sympy", "version": "1.14.*"},
    {"name": "handcalcs", "version": "1.11.*"},
    {"name": "forallpeople", "version": "2.7.*"},
    {"name": "latex2mathml", "version": "3.81.*"},
]


@main
def symbolic_report(quadratic: str = "x**2 - 5*x + 6") -> str:
    """Solve a quadratic, verify a root numerically, typeset ½·m·v² — one card."""
    # Symbolic: solve, then check root #0 numerically (residual should be 0).
    expr = parse_expr(quadratic)
    roots = solve_for(expr, "x")
    residual = evaluate_numeric(substitute(expr, "x", pick(roots, 0)))

    # Units: E_k = ½ · m · v², carried in real SI units (reduces to joules).
    mass = quantity(MASS_KG, "kg")
    speed = quantity(SPEED_M_S, "m/s")
    energy = multiply(multiply(speed, speed), mass, factor=0.5)

    # Typeset the substituted steps (handcalcs → LaTeX → native MathML).
    steps = typeset_calc("E_k = 1/2 * m * v**2", {"m": MASS_KG, "v": SPEED_M_S})
    mathml = latex_to_mathml(steps.latex)

    caption = join_text(
        describe(roots, "roots"),
        describe(residual, "residual at first root"),
        describe(energy, "E_k"),
    )
    return render_math_card("Quadratic roots & kinetic energy", mathml, caption)


def build_graph(quadratic: str = "x**2 - 5*x + 6"):
    """Trace the composite into a Graph carrying its environment descriptor."""
    graph = symbolic_report.to_graph(quadratic=quadratic)
    graph.environment = {
        "dependencies": DEPENDENCIES,
        "mounts": [],
        "network": "none",
    }
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
