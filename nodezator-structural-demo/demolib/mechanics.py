"""Math nodes.

Two flavours on purpose:

* ``axial_stress`` — declarative, unit-aware math using **forallpeople**. You
  feed it base SI and it carries real physical units through the calculation.
* ``capacity_margin`` — deliberately **imperative**: a ``while`` loop with
  mutation, a running counter and an early ``break``. It shows that a node body
  is just Python — control flow and all — not a restricted expression language.
"""

import forallpeople as si

# Populate forallpeople's namespace with SI units (si.N, si.m, si.Pa, ...).
# forallpeople auto-selects sensible prefixes on display, so a Pascal result
# prints as "MPa" without us asking.
si.environment("default")


def axial_stress(
    force_kN: float = 100.0,
    width_mm: float = 50.0,
    thickness_mm: float = 10.0,
) -> "si.Physical":
    """Axial (normal) stress on a rectangular bar: sigma = P / A.

    Inputs are plain numbers in engineering units; internally we attach real
    forallpeople units so the returned quantity is a true physical value
    (auto-displayed in MPa).
    """
    force = force_kN * 1_000 * si.N               # kN -> N
    area = (width_mm / 1_000 * si.m) * (thickness_mm / 1_000 * si.m)  # mm -> m, then m^2
    stress = force / area                          # N / m^2 == Pa (shows as MPa)
    return stress


def capacity_margin(
    force_kN: float = 100.0,
    width_mm: float = 50.0,
    thickness_mm: float = 10.0,
    fy_MPa: float = 250.0,
    step_kN: float = 10.0,
) -> dict:
    """Ramp the load in fixed steps until the bar yields — the imperative node.

    Because MPa == N/mm^2, we can keep the loop in plain numbers: stress in MPa
    is simply (force in N) / (area in mm^2). Returns how many whole steps the
    member survives before reaching yield, the load at yield, and the
    utilisation at the *applied* force.
    """
    area_mm2 = width_mm * thickness_mm

    # --- imperative core: mutate state in a loop until a condition trips ---
    load_kN = 0.0
    safe_steps = 0
    while True:
        stress_MPa = (load_kN * 1_000.0) / area_mm2  # N / mm^2 == MPa
        if stress_MPa >= fy_MPa:
            break
        safe_steps += 1
        load_kN += step_kN
    # ----------------------------------------------------------------------

    applied_stress_MPa = (force_kN * 1_000.0) / area_mm2
    utilisation = applied_stress_MPa / fy_MPa

    return {
        "safe_steps": safe_steps,
        "yield_load_kN": round(load_kN, 3),
        "utilisation": round(utilisation, 4),
    }
