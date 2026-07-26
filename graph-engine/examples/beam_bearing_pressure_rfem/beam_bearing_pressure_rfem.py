"""Support pressure without reinforcement, with the force taken from RFEM.

The same EC5 bearing check as ``examples/beam_bearing_pressure`` — same
formulas, same checks, same title, same ``as_of``, same ``precision`` — with
one thing changed: the governing force is no longer a number somebody typed
into ``inputs.json``. It is read out of a real RFEM export::

    export.csv ─> forces (rfem.read_extrema)
                    └─> governing (rfem.governing_force) ─┬─> artifact (write_json)
                                                          └─> card (sheet.calc_card)
    inputs.json ─> inputs (sources.read_json) ─> eight sources.pick nodes ──┘

``F_c90d`` is therefore **derived**, and ``inputs.json`` no longer carries it —
the eight remaining givens are the ones the export cannot know (geometry,
material, partial factors). Leaving the old ``F_c90d`` entry in place would
have created a second source of truth for the one number this example exists to
source properly.

**Where the force comes from.** ``260726_GZT_DesignLoadsMembers_Start_End.xlsx``
is an RFEM "design loads, members, start/end" extremum export, committed
untouched beside this module as the provenance record;
``xlsx_to_csv.py`` converts it, cell for cell, into the ``export.csv`` the graph
reads. 1104 data rows: 46 members × 2 node locations × 6 extremum types ×
max/min.

**Which row governs, and why the filter matters.** ``rfem.governing_force``
first filters to the rows whose ``Extremum`` column is ``Vz`` — RFEM has already
done the extremum search, and those rows *are* its answer — and then takes the
largest ``|Vz|`` among them. The other rows are not weaker candidates; they
carry the Vz that merely accompanies some *other* component's extremum. For
this file both scans happen to return the same number, which is a coincidence of
the data and not a reason to drop the filter (a test pins it on a table where
the two answers differ). The winner::

    Stab 10103 · Knoten 1578 · x = 6.1500000000005 m · Extremum Vz · LK67
    Vz = -297.175507 kN  ->  |Vz| = 297.175507 kN  ->  F_c90d

The magnitude is what feeds the check: the sign states a direction in the
model's axes, while a bearing pressure is about how much force presses on the
support. The signed value stays in the record.

**The given keeps its provenance.** ``governing_force`` returns the same
``{"value", "unit", "ref"}`` envelope ``inputs.json``'s entries use, so
``F_c90d``'s row on the card cites its source row —
``RFEM 10103/1578 @ 6.15 m · LK67`` — exactly where the other eight rows cite a
code clause. Nothing between the export and the card had to learn what a card
wants.

**The artifact is its own node.** ``sources.write_json`` hangs off ``governing``
rather than sitting between it and the card, so the selector stays pure and the
card can be fed without writing anything. The written ``governing.json`` is a
run output, not a source: it is gitignored, because a committed copy of the same
number is a second thing that can silently disagree with the export.

**The check FAILS, and the run stays green.** σ_c90d = 297175.507 / 24200 ≈
12.28 N/mm² against 1.75 · 1.7308 N/mm², so η ≈ 405 % — this support is nowhere
near sufficient for the force RFEM reports. Per ADR 0016 that is the *card's*
verdict and not an execution error, so there is no assertion node re-deriving it
on the side. It is what this data says.

Run (the ``sym`` extra provides calcsheet/SymPy/latex2mathml)::

    uv run --extra sym python examples/beam_bearing_pressure_rfem/beam_bearing_pressure_rfem.py
"""

from __future__ import annotations

import os
from pathlib import Path

from engine import main
from rfem import governing_force, read_extrema
from sheet import calc_card
from sources import pick, read_json, write_json

HERE = Path(__file__).resolve().parent
EXPORT_CSV = HERE / "export.csv"
INPUTS_JSON = HERE / "inputs.json"
ARTIFACT_JSON = "governing.json"  # relative, always — see sources.write_json

# What the graph needs to run — the ADR 0003 declarative descriptor. Versions
# match the `sym` extra in pyproject.toml; calcsheet pulls sympy + latex2mathml.
DEPENDENCIES = [
    {"name": "calcsheet", "version": "0.1.*"},
    {"name": "sympy", "version": "1.14.*"},
    {"name": "latex2mathml", "version": "3.81.*"},
]


# -- the graph, as ordinary Python (ADR 0004 straight-line form) -------------


@main
def beam_bearing_pressure_rfem(
    export_path: str = "export.csv",
    inputs_path: str = "inputs.json",
    artifact_path: str = "governing.json",
) -> str:
    """Select the governing force from the export, then render the calc card."""
    # The RFEM export, as a table — 1104 rows, the file's own columns.
    forces = read_extrema(path=export_path)

    # One row out of it. The `component` literal is the whole selection policy:
    # filter to the Vz extremum rows, take the largest |Vz|. It comes back as a
    # `{value, unit, ref}` record, so the number arrives with the member, node,
    # position and load case it was read from.
    governing = governing_force(table=forces, component='Vz')

    # The record, written to disk beside the example — a run output, not an
    # input. Its own node, hanging off `governing`: the selector stays a pure
    # function, and the card below is fed whether or not anything is written.
    artifact = write_json(data=governing, path=artifact_path)

    # The eight givens the export cannot know: geometry, material, partial
    # factors. One `pick` per value, exactly as in the JSON-only example, so any
    # single one stays independently re-pointable. `F_c90d` is NOT among them —
    # it is derived from the export now, and a second copy here would be a
    # second source of truth.
    inputs = read_json(path=inputs_path)
    a_1 = pick(data=inputs, key='a_1')
    l = pick(data=inputs, key='l')
    l_1 = pick(data=inputs, key='l_1')
    b = pick(data=inputs, key='b')
    k_c90 = pick(data=inputs, key='k_c90')
    k_mod = pick(data=inputs, key='k_mod')
    f_c90k = pick(data=inputs, key='f_c90k')
    gamma_M = pick(data=inputs, key='gamma_M')

    # The calculation, unchanged from `examples/beam_bearing_pressure` — the
    # literals, the check, the title, `as_of` and `precision` are all identical.
    # Only where `F_c90d` comes from is different: the `governing` record rather
    # than a `pick` off the JSON. Every free symbol of `formulas` is a derived
    # input socket (ADR 0007), and the keyword arguments follow the symbols'
    # first-appearance order.
    #
    # `eta` is about 405 % for this force: the check FAILS and the run stays
    # green (ADR 0016 — the verdict is card content, not an execution error).
    card = calc_card(
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
        F_c90d=governing,
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
    graph = beam_bearing_pressure_rfem.to_graph(
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
