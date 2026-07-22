"""Run the whole pipeline as plain Python — no Nodezator required.

This script is the hand-written twin of what Nodezator's "Export as Python"
would emit for the graph described in the README: read a CSV, select a row,
unpack it, do two pieces of math (one imperative), render the equations with
handcalcs + forallpeople, and assert the acceptance criterion f(x) < 1.

The point: the graph is just a picture of *this*. Delete the app and the
engineering still runs.

Usage:
    python run_demo.py            # selects the first member (index 0)
    python run_demo.py 1          # selects member at index 1 (this one FAILS)
"""

import sys
from pathlib import Path

from demolib import (
    read_members_csv,
    select_member,
    unpack_member,
    axial_stress,
    capacity_margin,
    render_stress_check,
    assert_utilisation_below_one,
)

HERE = Path(__file__).resolve().parent
CSV_PATH = HERE / "members.csv"
HTML_OUT = HERE / "report.html"


def main(index: int = 0) -> int:
    # ---- data flow, mirroring the node graph edge-for-edge ----
    rows = read_members_csv(str(CSV_PATH))
    member = select_member(rows, index=index)
    fields = unpack_member(member)

    name = fields["name"]
    force_kN = fields["force_kN"]
    width_mm = fields["width_mm"]
    thickness_mm = fields["thickness_mm"]
    fy_MPa = fields["fy_MPa"]

    # ---- math node 1: unit-aware stress (forallpeople) ----
    stress = axial_stress(force_kN, width_mm, thickness_mm)

    # ---- math node 2: imperative load ramp ----
    margin = capacity_margin(force_kN, width_mm, thickness_mm, fy_MPa)

    # ---- report node: typeset equations (handcalcs + forallpeople) ----
    report = render_stress_check(force_kN, width_mm, thickness_mm, fy_MPa)

    # ---- console summary ----
    print(f"Member selected : {name}  (row index {index})")
    print(f"  P = {force_kN} kN, section = {width_mm} x {thickness_mm} mm, fy = {fy_MPa} MPa")
    print(f"  axial_stress      -> {stress}")
    print(f"  capacity_margin   -> {margin}")
    print(f"  utilisation f(x)  -> {report['utilisation']}")
    print(f"  equation summary  -> {report['summary']}")

    _write_html(name, report["latex"], report["utilisation"])
    print(f"\nTypeset equations written to: {HTML_OUT}")

    # ---- acceptance node: assert f(x) < 1 ----
    try:
        verdict = assert_utilisation_below_one(report["utilisation"], label=name)
        print(f"\n{verdict}")
        return 0
    except AssertionError as exc:
        print(f"\nFAIL — {exc}")
        return 1


def _write_html(title: str, latex: str, utilisation: float) -> None:
    """Wrap the handcalcs LaTeX in a minimal MathJax page you can open locally."""
    status = "PASS" if utilisation < 1.0 else "FAIL"

    # handcalcs already delimits its output with $$...$$; strip that so we can
    # use MathJax's default \[...\] display delimiters without double-wrapping.
    body = latex.strip()
    if body.startswith("$$") and body.endswith("$$"):
        body = body[2:-2].strip()
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Stress check — {title}</title>
  <script>
    window.MathJax = {{ tex: {{ inlineMath: [['\\\\(', '\\\\)']] }} }};
  </script>
  <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js" async></script>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 720px; margin: 3rem auto; }}
    .status {{ font-weight: 700; color: {'#1a7f37' if status == 'PASS' else '#cf222e'}; }}
  </style>
</head>
<body>
  <h1>Axial stress check — {title}</h1>
  <p>Acceptance criterion: <code>f(x) = utilisation &lt; 1</code>
     → <span class="status">{status}</span> (utilisation = {utilisation:.3f})</p>
  <div>\\[{body}\\]</div>
</body>
</html>
"""
    HTML_OUT.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    selected_index = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    raise SystemExit(main(selected_index))
