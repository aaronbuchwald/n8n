"""Reporting nodes: render the equations (handcalcs + forallpeople) and assert.

* ``render_stress_check`` uses **handcalcs** to turn the calculation into a set
  of typeset LaTeX equations, with **forallpeople** supplying real units so the
  rendered math reads like a hand calculation.
* ``assert_utilisation_below_one`` is the acceptance criterion: the classic
  engineering check ``f(x) < 1`` (here the demand/capacity utilisation ratio).
"""

import forallpeople as si
from handcalcs.decorator import handcalc

si.environment("default")


@handcalc(jupyter_display=False)
def _stress_equations(P, A, f_y):
    """Body rendered by handcalcs — every assignment becomes one equation."""
    sigma = P / A          # axial stress
    U = sigma / f_y        # utilisation (demand / capacity), dimensionless
    return U


def render_stress_check(
    force_kN: float = 100.0,
    width_mm: float = 50.0,
    thickness_mm: float = 10.0,
    fy_MPa: float = 250.0,
) -> dict:
    """Produce typeset LaTeX for the stress check plus the utilisation number.

    Returns a dict with:
      * ``latex``       — the handcalcs LaTeX (drop into MathJax / Jupyter).
      * ``utilisation`` — the dimensionless ratio used by the assertion node.
      * ``summary``     — a plain-text one-liner for quick viewing.
    """
    P = force_kN * 1_000 * si.N
    A = (width_mm / 1_000 * si.m) * (thickness_mm / 1_000 * si.m)
    f_y = fy_MPa * 1e6 * si.Pa

    rendered = _stress_equations(P, A, f_y)
    # The handcalc decorator returns (latex_str, function_return_value); we only
    # need the LaTeX. Stay tolerant of its shape across handcalcs versions.
    latex = rendered[0] if isinstance(rendered, tuple) else str(rendered)

    utilisation = float((P / A) / f_y)
    summary = f"sigma = P / A ;  U = sigma / f_y = {utilisation:.3f}"

    return {
        "latex": latex,
        "utilisation": round(utilisation, 4),
        "summary": summary,
    }


def assert_utilisation_below_one(
    utilisation: float = 0.8,
    label: str = "member",
) -> str:
    """Acceptance check: assert the utilisation ratio f(x) < 1.

    Raises ``AssertionError`` (which surfaces as a node error in Nodezator) when
    the member is overstressed; otherwise returns a pass message.
    """
    assert utilisation < 1.0, (
        f"{label}: utilisation f(x) = {utilisation:.3f} is NOT < 1.0 "
        f"— member FAILS the check"
    )
    return f"PASS — {label}: utilisation f(x) = {utilisation:.3f} < 1.0"
