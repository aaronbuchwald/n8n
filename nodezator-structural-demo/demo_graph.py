"""Wire the demo functions into the headless engine and build the beam graph.

This is the bridge between the framework-free logic in ``demolib/`` and the
Phase-0 :mod:`engine`. It registers each demo function as a node type (mirroring
the ``main_callable`` + ``third_party_import_text`` bindings in
``demo_nodepack/*/__main__.py``) and assembles the same pipeline the README
draws and ``run_demo.py`` runs by hand — but now as *engine data*:

    read_members_csv -> select_member -> unpack_member
        -> axial_stress
        -> capacity_margin
        -> render_stress_check -> assert_utilisation_below_one

Run it directly to execute the graph, print the exported Python, and write the
frozen JSON schemas + example artifacts under ``engine/schemas/``.
"""

from __future__ import annotations

from pathlib import Path

from demolib.data import read_members_csv, select_member, unpack_member
from demolib.mechanics import axial_stress, capacity_margin
from demolib.report import assert_utilisation_below_one, render_stress_check

from engine import Graph, NodeRegistry

HERE = Path(__file__).resolve().parent
CSV_PATH = HERE / "members.csv"


def build_registry() -> NodeRegistry:
    """Register the seven demo node types with their export import lines."""
    reg = NodeRegistry()
    reg.register(read_members_csv, third_party_import="from demolib.data import read_members_csv")
    reg.register(select_member, third_party_import="from demolib.data import select_member")
    # unpack_member's list-of-dicts return annotation yields 5 named outputs by
    # pure introspection — no override needed.
    reg.register(unpack_member, third_party_import="from demolib.data import unpack_member")
    reg.register(axial_stress, third_party_import="from demolib.mechanics import axial_stress")
    reg.register(capacity_margin, third_party_import="from demolib.mechanics import capacity_margin")
    # render_stress_check declares `-> dict`; declare its keys as output sockets
    # so downstream nodes can wire a single value (here: utilisation).
    reg.register(
        render_stress_check,
        outputs=[
            {"name": "latex", "type": "str"},
            {"name": "utilisation", "type": "float"},
            {"name": "summary", "type": "str"},
        ],
        third_party_import="from demolib.report import render_stress_check",
    )
    reg.register(
        assert_utilisation_below_one,
        third_party_import="from demolib.report import assert_utilisation_below_one",
    )
    return reg


def build_graph(index: int = 0, csv_path: Path | str = CSV_PATH) -> Graph:
    """Build the beam-check graph selecting member ``index``."""
    g = Graph()
    g.add("csv", "read_members_csv", inputs={"path": str(csv_path)}, position={"x": 0, "y": 0})
    g.add("pick", "select_member", inputs={"index": index}, position={"x": 220, "y": 0})
    g.add("unpack", "unpack_member", position={"x": 440, "y": 0})
    g.add("stress", "axial_stress", position={"x": 680, "y": -120})
    g.add("margin", "capacity_margin", position={"x": 680, "y": 40})
    g.add("report", "render_stress_check", position={"x": 680, "y": 200})
    g.add("check", "assert_utilisation_below_one", position={"x": 920, "y": 200})

    g.connect("csv", "output", "pick", "rows")
    g.connect("pick", "output", "unpack", "member")

    for field in ("force_kN", "width_mm", "thickness_mm"):
        g.connect("unpack", field, "stress", field)
    for field in ("force_kN", "width_mm", "thickness_mm", "fy_MPa"):
        g.connect("unpack", field, "margin", field)
        g.connect("unpack", field, "report", field)

    g.connect("report", "utilisation", "check", "utilisation")
    g.connect("unpack", "name", "check", "label")
    return g


def main() -> None:
    from engine import run, to_python

    registry = build_registry()
    graph = build_graph(index=0)

    result = run(graph, registry)
    util = result.value("report", "utilisation")
    verdict = result.value("check")
    print(f"utilisation f(x) = {util}  ->  {verdict}")

    print("\n----- to_python(graph) -----")
    print(to_python(graph, registry))


if __name__ == "__main__":
    main()
