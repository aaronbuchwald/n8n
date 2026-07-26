"""Support pressure without reinforcement — one design per load tier.

The same EC5 bearing check as ``examples/beam_bearing_pressure_rfem``, over the
same RFEM export, with the same formulas, checks, title, ``as_of`` and
``precision``. One thing changed: instead of taking **one** governing force out
of the export and designing **one** connection for it, the member ends are
divided into **groups**, and every group gets its own design::

    export.csv ─> forces (rfem.read_extrema)
                    └─> ends (rfem.member_ends) ─┐
    inputs.json ─> inputs (sources.read_json)    │
                    ├─> grouping (sources.pick) ─┴─> groups (grouping.group)
                    │                                  ├─> artifact (write_json)
                    │                                  └─> card (sheet.group_card)
                    └─> eight sources.pick nodes ─────────┘

**The question this example exists to ask.** "The maximum |Vz| over the whole
model" is one answer to *how do you divide the member ends into groups?* — the
degenerate one, a single group. The general question has other answers, and
which one applies is an engineering decision, not a property of the graph. So
the decision is named in the project's inputs and implemented by a **grouping
strategy**; the graph stays the same shape whichever strategy runs. See
``docs/grouping-strategies.md`` for the contract and
``graph-engine/nodepacks/grouping`` for the two shipped strategies.

**The rule this project chose**, in ``inputs.json`` beside the givens::

    "grouping": {"strategy": "tiered", "params": {"thresholds": [150, 50]}}

Two thresholds, declared descending, make three half-open tiers — ``[150, ∞)``,
``[50, 150)`` and ``[0, 50)`` kN — and a value exactly on a threshold falls in
the tier that threshold opens. Over the 184 ``Extremum = Vz`` rows of this
export they divide 24 / 97 / 63, and each tier is governed by its own largest
magnitude::

    T1  [150, ∞) kN   24 ends   297.175507 kN   10103/1578 @ 6.15 m · LK67
    T2  [50, 150) kN  97 ends   144.104507 kN   10105/1933 @ 0 m    · LK80
    T3  [0, 50) kN    63 ends    48.985149 kN   10112/1943 @ 5.1 m  · LK3

The ``single`` strategy on the same population returns T1's number, 297.175507
kN, for the whole model — which is exactly what
``examples/beam_bearing_pressure_rfem`` designs for. The tiering is what stops
the 63 lightest ends from paying for the heaviest one.

**Why the config is in ``inputs.json`` and not a new file.** It is a per-project
knob exactly like ``k_mod`` or ``gamma_M``, and it is read the same way — one
``sources.pick`` off the one document. A second file would be a second thing to
find, a second thing to version and a second thing that can disagree with the
first. The strategy's own parameters are nested under ``params`` so a strategy
may name a parameter anything at all without ever colliding with a key the
envelope might grow later.

**One node grouped, one node summarised.** How many tiers there are is a
property of the *data*: move a threshold and the card grows a row, while the
canvas does not change at all. So ``grouping.group`` returns all N groups on one
socket and ``sheet.group_card`` renders them as **one** card with one row per
group. The accepted trade — the owner's, explicitly — is that the per-tier
arithmetic happens inside the summary node rather than being individually
openable on the canvas; the card carries that burden by putting every
intermediate value on it, subscripted with the tier's key.

**All three tiers share one geometry.** ``l``, ``b``, ``k_c90``, ``k_mod``,
``f_c90k``, ``gamma_M``, ``a_1`` and ``l_1`` are the same for every tier; only
the governing force differs. The card says so by *not repeating* the shared
work: ``l_ef``, ``A_ef`` and ``f_c90d`` appear once, and only ``sigma_c90d`` and
``eta`` are computed per tier. Designing different bearing geometry per tier —
a wider bearing plate for T1, say — is the real-world next step and is
explicitly **out of scope** here: it needs a per-group *given*, not just a
per-group force.

**Two tiers FAIL, one PASSES, and the run stays green.** η is 405.43 %, 196.60 %
and 66.83 %. Per ADR 0016 those are the *card's* verdicts and not execution
errors, so there is no assertion node re-deriving them on the side. A failing
tier does not suppress the others — all three verdicts are on the one card, and
the overall verdict is their conjunction.

**The export is not copied.** ``export.csv`` is read from
``examples/beam_bearing_pressure_rfem/`` next door, where it lives beside the
workbook it was converted from. A third copy of the same 1104 rows would be a
third thing that can silently drift.

Run (the ``sym`` extra provides calcsheet/SymPy/latex2mathml)::

    uv run --extra sym python examples/beam_bearing_pressure_tiered/beam_bearing_pressure_tiered.py
"""

from __future__ import annotations

import os
from pathlib import Path

from engine import main
from grouping import group
from rfem import member_ends, read_extrema
from sheet import group_card
from sources import pick, read_json, write_json

HERE = Path(__file__).resolve().parent
# The sibling example's export, read in place — see the module docstring.
EXPORT_CSV = HERE.parent / "beam_bearing_pressure_rfem" / "export.csv"
INPUTS_JSON = HERE / "inputs.json"
ARTIFACT_JSON = "groups.json"  # relative, always — see sources.write_json

# What the graph needs to run — the ADR 0003 declarative descriptor. Versions
# match the `sym` extra in pyproject.toml; calcsheet pulls sympy + latex2mathml.
DEPENDENCIES = [
    {"name": "calcsheet", "version": "0.1.*"},
    {"name": "sympy", "version": "1.14.*"},
    {"name": "latex2mathml", "version": "3.81.*"},
]


# -- the graph, as ordinary Python (ADR 0004 straight-line form) -------------


@main
def beam_bearing_pressure_tiered(
    export_path: str = "../beam_bearing_pressure_rfem/export.csv",
    inputs_path: str = "inputs.json",
    artifact_path: str = "groups.json",
) -> str:
    """Group the export's member ends by load tier, then render one calc card."""
    # The RFEM export, as a table — 1104 rows, the file's own columns.
    forces = read_extrema(path=export_path)

    # The population to be divided: every row RFEM reports as a Vz extremum,
    # 184 of them, each a record carrying its magnitude and the member, node,
    # position and load case it was read from. This node is the only one that
    # knows what an RFEM export looks like; everything downstream sees a plain
    # population of forces.
    ends = member_ends(table=forces, component='Vz')

    # The project's inputs: the grouping rule beside the eight givens, read the
    # same way as any of them.
    inputs = read_json(path=inputs_path)
    grouping = pick(data=inputs, key='grouping')

    # The division itself. `config` names the strategy and its parameters; the
    # node returns N groups on one socket, each with its label, its member
    # count, and the governing force with its provenance intact. Swapping
    # 'tiered' for 'single' in inputs.json is the whole difference between
    # designing three connections and designing one — no wire moves.
    groups = group(population=ends, config=grouping)

    # The division, written to disk beside the example — a run output, not an
    # input. Its own node, hanging off `groups`: the grouping stays a pure
    # function, and the card below is fed whether or not anything is written.
    # The artifact lists every member end's ref under the group it fell in, so
    # the partition can be audited by hand.
    artifact = write_json(data=groups, path=artifact_path)

    # The eight givens the export cannot know: geometry, material, partial
    # factors. Identical for every tier — this example varies the force alone.
    a_1 = pick(data=inputs, key='a_1')
    l = pick(data=inputs, key='l')
    l_1 = pick(data=inputs, key='l_1')
    b = pick(data=inputs, key='b')
    k_c90 = pick(data=inputs, key='k_c90')
    k_mod = pick(data=inputs, key='k_mod')
    f_c90k = pick(data=inputs, key='f_c90k')
    gamma_M = pick(data=inputs, key='gamma_M')

    # The calculation, unchanged from `examples/beam_bearing_pressure_rfem` —
    # the literals, the check, the title, `as_of` and `precision` are all
    # identical, and it is still written ONCE, for one group. `F_c90d` is fed
    # the group population instead of a single record, and `sheet.group_card`
    # instantiates the calculation for each group: the formulas that depend on
    # `F_c90d` are copied per tier and suffixed with the tier's key, and the
    # ones that do not are computed once.
    card = group_card(
        title='Support pressure without reinforcement',
        as_of='2025-07-02',
        formulas=(
            'l_l = MinDefined(30, a_1) [mm]  # EN 1995-1-1 6.1.5 (1)\n'
            'l_r = MinDefined(30, l, l_1/2) [mm]  # EN 1995-1-1 6.1.5 (1)\n'
            'l_ef = l_l + l + l_r [mm]  # EN 1995-1-1 6.1.5 (1)\n'
            'A_ef = l_ef * b [mm²]  # EN 1995-1-1 6.1.5 (1)\n'
            'sigma_c90d = F_c90d * 1000 / A_ef [N/mm²]  # EN 1995-1-1 6.1.5 (1) (6.4)\n'
            'f_c90d = k_mod * f_c90k / gamma_M [N/mm²]  # EN 1995-1-1 2.4.1 (1)P (2.14)\n'
            'eta = sigma_c90d / (k_c90 * f_c90d) * 100 [%]  # EN 1995-1-1 6.1.5 (1)P (6.3)'
        ),
        checks='eta < 100 [eta]  # reinforcement of the support not required',
        precision=5,
        a_1=a_1,
        l=l,
        l_1=l_1,
        b=b,
        F_c90d=groups,
        k_mod=k_mod,
        f_c90k=f_c90k,
        gamma_M=gamma_M,
        k_c90=k_c90,
    )
    # The card's single `result` socket — the self-contained HTML document — is
    # the graph output. `artifact` is a leaf: nothing consumes the written path.
    return card


def build_graph(
    export_csv: Path | str = EXPORT_CSV,
    inputs_json: Path | str = INPUTS_JSON,
    artifact_path: str = ARTIFACT_JSON,
):
    """Trace the composite into a Graph.

    The two **reads** get absolute paths so the graph runs from any working
    directory. The **write** stays relative on purpose: ``sources.write_json``
    refuses an absolute destination, and the run directory is what confines it
    (the server runs a graph in the program's own directory; :func:`main_cli`
    does the same).
    """
    graph = beam_bearing_pressure_tiered.to_graph(
        export_path=str(export_csv),
        inputs_path=str(inputs_json),
        artifact_path=artifact_path,
    )
    graph.environment = {
        "dependencies": DEPENDENCIES,
        # The written artifact is what a `rw` mount would grant once ADR 0003's
        # mount guard exists; until then `sources.write_json` confines itself to
        # the run directory and this stays the honest empty declaration.
        "mounts": [],
        "network": "none",
    }
    return graph


def main_cli() -> None:
    from engine import run, to_python

    os.chdir(HERE)  # the run directory the artifact is written into
    graph = build_graph()
    out = graph.output
    print(run(graph).value(out["node"], out["socket"]))
    print("\n----- to_python(graph) -----")
    print(to_python(graph))


if __name__ == "__main__":
    main_cli()
