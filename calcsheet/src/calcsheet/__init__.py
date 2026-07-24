"""calcsheet — completed calculations as artifacts.

Declare a calculation as data (inputs, formulas, references, checks), evaluate
it once, and render that one result as a self-contained "C4 four-slot" HTML
card with a binary pass/fail verdict.

    from calcsheet import Calc, Check, Formula, Input, render_html

    calc = Calc(
        title="Capacity check",
        as_of="2026-07-24",
        inputs={"F_max": Input(120, ref="forces.csv · max")},
        formulas=[Formula("U", "100 * F_max / 210", unit="%")],
        checks=[Check("U < 100", "capacity not exceeded")],
    )
    html = render_html(calc.evaluate())

Importing this package has no side effects and touches no clock, filesystem or
network — it is a library, so a graph engine can later wrap it by decorating a
function that calls it.
"""

from __future__ import annotations

from .errors import CalcError
from .evaluate import CheckResult, Result, Row, evaluate_calc
from .model import Calc, Check, Formula, Input
from .registry import (
    RendererInfo,
    get_renderer,
    register_renderer,
    renderer_info,
    renderers,
)
from .render import HtmlOptions, render_html
from .serialize import RESULT_SCHEMA_KEY, RESULT_SCHEMA_VERSION

__all__ = [
    "RESULT_SCHEMA_KEY",
    "RESULT_SCHEMA_VERSION",
    "Calc",
    "CalcError",
    "Check",
    "CheckResult",
    "Formula",
    "HtmlOptions",
    "Input",
    "RendererInfo",
    "Result",
    "Row",
    "evaluate_calc",
    "get_renderer",
    "register_renderer",
    "renderer_info",
    "renderers",
    "render_html",
]
