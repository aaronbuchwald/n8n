"""The capacity check: a utilisation calc with two design checks.

Run it: ``python -m calcsheet.examples.capacity`` (add ``--no-open`` to skip
the browser). It writes ``out/capacity-check.html`` relative to the current
directory and prints the path and the overall status — which is FAIL, because
57.1 % utilisation clears the 100 % safety limit but misses the 50 % target.
"""

from __future__ import annotations

import argparse
import webbrowser
from pathlib import Path

from calcsheet import Calc, Check, Formula, Input, render_html

OUTPUT_PATH = Path("out") / "capacity-check.html"


def build_calc() -> Calc:
    """The calc itself — pure data, no numbers computed yet."""
    return Calc(
        title="Capacity check",
        as_of="2026-07-24",  # pinned: an artifact must not change with the clock
        inputs={
            "F_max": Input(120, ref="forces.csv · max"),
            "C_min": Input(210, ref="members.csv · min"),
        },
        formulas=[
            Formula("r", "F_max / C_min", ref="demand / capacity"),
            Formula("U", "100 * r", ref="utilisation", unit="%"),
        ],
        checks=[
            Check("U < 100", "capacity not exceeded"),
            Check("U < 50", "utilisation target"),
        ],
    )


def render() -> str:
    """Build, evaluate and render the example card."""
    return render_html(build_calc().evaluate())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--no-open", action="store_true", help="write the file but don't open a browser"
    )
    args = parser.parse_args(argv)

    result = build_calc().evaluate()
    html = render_html(result)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(html, encoding="utf-8")
    path = OUTPUT_PATH.resolve()

    print(f"wrote {path}")
    print(f"status: {'PASS' if result.passed else 'FAIL'}")
    for check in result.checks:
        print(f"  {'PASS' if check.passed else 'FAIL'}  {check.substituted}")

    if not args.no_open:
        webbrowser.open(path.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
