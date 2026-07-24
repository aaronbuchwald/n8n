"""Capacity check, split — one evaluation, two renderings (ADR 0021).

The same calculation as ``examples/capacity_check``, wired the other way:
instead of one ``sheet.calc_card`` node that evaluates **and** renders, the two
steps are separate nodes with the completed ``Result`` on the wire between
them::

    forces.csv  ─> forces ──> F_max ──┐
                                      ├─> sheet (sheet.calc) ──┬─> card ────> html
    members.csv ─> members ─> C_min ──┘        Result          └─> branded ─> html

``sheet.calc`` puts the ``Result`` — rows, values, verdicts, pre-minted
markup — on a socket; each ``sheet.render_html`` node turns that one result
into a document. **The second card is a second rendering, not a second
calculation**: the numbers are computed once and the two cards can never
disagree. Swapping a rendering (or adding a PDF one later) is one node on the
same wire.

The two forms are equals, not a migration: ``calc_card`` stays the one-node
convenience form and ``examples/capacity_check`` still ships it. Rendering
options are literals on the *render* node only (``header``, ``footer``,
``theme``) — presentation never leaks upstream into the dataflow, so the calc
node knows nothing about banners.

Everything else is deliberately identical to ``capacity_check``: same CSVs,
same formulas, same checks, same ``as_of``. ``card`` renders with every option
at its default, so its HTML is byte-for-byte what the single-node example
produces — that equality is the point of the split, and a test asserts it.

``F_max`` and ``C_min`` are read before any formula defines them, so they are
the calc's **inputs** and therefore ``sheet.calc``'s input sockets, derived
from the formulas themselves (ADR 0007). The derived-socket seam moves with the
deriving parameter, which is why it lands on ``calc`` and not on the renderer.

**A failing check does not fail the run.** ``U < 50`` is false for this data
(57.1 %), so both cards render FAIL — the verdict is card content, not an
execution error.

Simple, generic mock data only — no real engineering formulas, just a
highest-force-vs-lowest-capacity ratio.

Run (the ``sym`` extra provides calcsheet/SymPy/latex2mathml)::

    uv run --extra sym python examples/capacity_check_split/capacity_check_split.py
"""

from __future__ import annotations

from pathlib import Path

from calc import maximum, minimum
from engine import main
from sheet import calc, render_html
from sources import read_csv

HERE = Path(__file__).resolve().parent
FORCES_CSV = HERE / "forces.csv"
MEMBERS_CSV = HERE / "members.csv"

# What the graph needs to run — the ADR 0003 declarative descriptor. Versions
# match the `sym` extra in pyproject.toml; calcsheet pulls sympy + latex2mathml.
DEPENDENCIES = [
    {"name": "calcsheet", "version": "0.1.*"},
    {"name": "sympy", "version": "1.14.*"},
    {"name": "latex2mathml", "version": "3.81.*"},
]


# -- the graph, as ordinary Python (ADR 0004 straight-line form) -------------


@main
def capacity_check_split(
    forces_path: str = "forces.csv", members_path: str = "members.csv"
) -> str:
    """Read both CSVs, reduce each to its extreme, evaluate once, render twice."""
    # Two independent CSV arcs, exactly as in the single-node example.
    forces = read_csv(path=forces_path, column="force")
    members = read_csv(path=members_path, column="capacity")

    # Reduce each arc to the value that governs the check: the highest applied
    # force and the lowest available capacity.
    F_max = maximum(forces)
    C_min = minimum(members)

    # The arcs meet at the node that holds the calculation as data. It emits the
    # `Result` itself — the numbers, not a document — so the choice of rendering
    # is no longer welded to the node that owns them.
    #
    # Straight-line form (ADR 0004 D7): each call is its own assignment — no
    # nested calls in arguments — so the composite round-trips through the
    # graph⟷source bijection and can be served + edited in the UI.
    #
    # The calc literals are written one string per entry (ADR 0020): adjacent
    # literals concatenate at parse time, so the value is exactly the lines
    # below — indentation is code, never content — and this is the shape a UI
    # edit writes back.
    sheet = calc(
        title='Capacity check',
        as_of='2026-07-24',
        formulas=(
            'r = F_max / C_min  # demand / capacity\n'
            'U = 100 * r [%]  # utilisation'
        ),
        checks=(
            'U < 100  # capacity not exceeded\n'
            'U < 50  # utilisation target'
        ),
        F_max=F_max,
        C_min=C_min,
    )

    # Two renderings of that ONE result. The first takes every option's default,
    # so it is byte-identical to what `sheet.calc_card` renders; the second is
    # the same card with a banner and a fine-print line. Neither re-evaluates
    # anything — they read the same `Result` off the same wire.
    card = render_html(result=sheet)
    branded = render_html(result=sheet, header='Acme Corp', footer='forces.csv · members.csv')

    # The plain card is the graph output; `branded` is a sibling artifact of the
    # same evaluation, which is exactly what the split buys.
    return card


def build_graph(forces_csv: Path | str = FORCES_CSV, members_csv: Path | str = MEMBERS_CSV):
    """Trace the composite into a Graph (absolute CSV paths so it runs anywhere)."""
    graph = capacity_check_split.to_graph(
        forces_path=str(forces_csv), members_path=str(members_csv)
    )
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
