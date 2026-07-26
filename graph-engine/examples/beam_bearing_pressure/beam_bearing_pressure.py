"""Auflagerdruck ohne Verstärkung — a real EC5 support-pressure check.

A faithful reproduction of a timber design sheet: the compressive stress
perpendicular to the grain at a beam support, checked against the design
compressive strength times the bearing factor ``k_c90`` (EN 1995-1-1 6.1.5).
Unlike ``examples/capacity_check``, none of this is mock data — every given and
every code reference is copied from the source sheet.

One JSON file of givens, one value per node, one calculation::

    inputs.json ─> inputs (sources.read_json)
                     └─> nine sources.pick nodes ──> card (sheet.calc_card) ─> html

**Why nine picks and not one reader.** Each given is its own node with its own
wire, so any single one can later be re-pointed at a different source — a
member database, an API node, another calc's output — without touching the
other eight. A node that read all nine keys at once would make that a rewrite.
``sources.read_json``/``sources.pick`` know nothing about bearing pressure;
the engineering lives entirely in the ``formulas`` literal.

**The empty given.** The sheet prints ``l_1 = –``: this support has no second
bearing length, so the quantity does not exist for this member. ``inputs.json``
says ``"value": null``, ``pick`` yields ``None``, and calcsheet renders the row
as ``–``. The rule that uses it is still stated in full —
``l_r = MinDefined(30, l, l_1/2)`` — and only the argument that depends on the
empty given drops out before the minimum is taken. So the card shows the
general rule and the value for *this* case: ``min(30, 80, –/2) = 30 mm``.

Three choices worth naming, each also commented where it lands:

* **``l_ef``, not ``l``** — the source sheet reuses ``l`` for both the 80 mm
  given and the 110 mm effective length. calcsheet refuses a redefinition (each
  symbol is defined once), and ``l_ef`` is EC5's own symbol for exactly this
  quantity, so nothing is invented to work around the refusal.
* **the ``* 1000``** — ``F_c90d`` stays in kN so its given row reads like the
  sheet's. calcsheet has no unit algebra, so the kN→N conversion is written
  where it happens, in the formula, rather than hidden in the input.
* **the check FAILS** — η = 145.98 % > 100 %, i.e. "Eine Verstärkung des
  Auflagers ist erforderlich!". Per ADR 0016 that is the *card's* verdict and
  the run stays green; there is no assertion node re-deriving it on the side.

Run (the ``sym`` extra provides calcsheet/SymPy/latex2mathml)::

    uv run --extra sym python examples/beam_bearing_pressure/beam_bearing_pressure.py
"""

from __future__ import annotations

from pathlib import Path

from engine import main
from sheet import calc_card
from sources import pick, read_json

HERE = Path(__file__).resolve().parent
INPUTS_JSON = HERE / "inputs.json"

# What the graph needs to run — the ADR 0003 declarative descriptor. Versions
# match the `sym` extra in pyproject.toml; calcsheet pulls sympy + latex2mathml.
DEPENDENCIES = [
    {"name": "calcsheet", "version": "0.1.*"},
    {"name": "sympy", "version": "1.14.*"},
    {"name": "latex2mathml", "version": "3.81.*"},
]


# -- the graph, as ordinary Python (ADR 0004 straight-line form) -------------


@main
def beam_bearing_pressure(inputs_path: str = "inputs.json") -> str:
    """Read the givens, fan them out one per node, and render the calc card."""
    # One read of the sheet's given table. `read_json` hands back the document
    # unchanged — it neither knows nor cares which keys are in it.
    inputs = read_json(path=inputs_path)

    # One `pick` per given, in the order the source sheet lists them. Each is an
    # independent node, so re-pointing a single value at another source is a
    # one-node edit. `l_1` is the empty one: its entry holds `null`, which picks
    # as `None` and reaches the card as an empty given.
    F_c90d = pick(data=inputs, key='F_c90d')
    a_1 = pick(data=inputs, key='a_1')
    l = pick(data=inputs, key='l')
    l_1 = pick(data=inputs, key='l_1')
    b = pick(data=inputs, key='b')
    k_c90 = pick(data=inputs, key='k_c90')
    k_mod = pick(data=inputs, key='k_mod')
    f_c90k = pick(data=inputs, key='f_c90k')
    gamma_M = pick(data=inputs, key='gamma_M')

    # The nine arcs meet at ONE node that holds the entire calculation as data.
    # Every free symbol of `formulas` is a derived input socket (ADR 0007), so
    # the symbols are declared exactly once — in the literal below — and the
    # keyword arguments follow that same first-appearance order.
    #
    # `l_ef` rather than `l`: the source sheet reuses `l` for the 80 mm given
    # AND the 110 mm effective length; calcsheet refuses a redefinition, and
    # `l_ef` is EC5's own symbol for the effective bearing length.
    #
    # The `* 1000` is the kN→N conversion, written where it happens: `F_c90d`
    # stays in kN so its given row reads `107` like the sheet, and calcsheet
    # does no unit algebra, so the factor has to be visible in the formula.
    #
    # `precision=5` because at the default of 3 the card would render
    # `A_ef = 2.42e+04` and `eta = 146` — significant digits, not decimals.
    #
    # The check's trailing `[eta]` names its utilisation symbol, which is what
    # puts `145.98 ≤ 100` on the governing chip. It FAILS, and per ADR 0016 the
    # run still succeeds: the verdict is card content, not an execution error.
    #
    # Straight-line form (ADR 0004 D7): each call is its own assignment — no
    # nested calls in arguments — so the composite round-trips through the
    # graph⟷source bijection and can be served + edited in the UI. The calc
    # literals are written one string per entry (ADR 0020): adjacent literals
    # concatenate at parse time, so the value is exactly the lines below —
    # indentation is code, never content.
    card = calc_card(
        title='Auflagerdruck ohne Verstärkung',
        as_of='2025-07-02',
        formulas=(
            'l_l = MinDefined(30, a_1) [mm]  # EN 1995-1-1 6.1.5 (1)\n'
            'l_r = MinDefined(30, l, l_1/2) [mm]  # EN 1995-1-1 6.1.5 (1)\n'
            'l_ef = l_l + l + l_r [mm]  # EN 1995-1-1 6.1.5 (1)\n'
            'A_ef = l_ef * b [mm^2]  # EN 1995-1-1 6.1.5 (1)\n'
            'sigma_c90d = F_c90d * 1000 / A_ef [N/mm^2]  # EN 1995-1-1 6.1.5 (1) (6.4)\n'
            'f_c90d = k_mod * f_c90k / gamma_M [N/mm^2]  # EN 1995-1-1 2.4.1 (1)P (2.14)\n'
            'eta = sigma_c90d / (k_c90 * f_c90d) * 100 [%]  # EN 1995-1-1 6.1.5 (1)P (6.3)'
        ),
        checks='eta < 100 [eta]  # reinforcement of the support not required',
        precision=5,
        a_1=a_1,
        l=l,
        l_1=l_1,
        b=b,
        F_c90d=F_c90d,
        k_mod=k_mod,
        f_c90k=f_c90k,
        gamma_M=gamma_M,
        k_c90=k_c90,
    )
    # The card's single `result` socket — the self-contained HTML document — is
    # the graph output.
    return card


def build_graph(inputs_json: Path | str = INPUTS_JSON):
    """Trace the composite into a Graph (absolute JSON path so it runs anywhere)."""
    graph = beam_bearing_pressure.to_graph(inputs_path=str(inputs_json))
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
