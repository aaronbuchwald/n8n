"""Dimensional tripwires for the two places numbers enter, and the one where they meet.

Engineering wrongness hides in unit slips, so every number crossing a boundary
into this package declares its unit and is checked against the dimension the
schema expects: KB properties (``"rho_k[kg/m^3]"``), FEM columns
(``"V_z[kN]"``), and clause symbols (the code's ``[symbols]`` table). Inside
``calcsheet`` units stay display strings — that boundary is deliberate (ADR
0022, "Units and dimensional correctness").

This is a deliberately small unit algebra rather than a ``forallpeople``
dependency: all it must do is parse a unit string, compare dimensions and
scale a float. Nothing here does arithmetic on quantities.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .errors import DesignCheckError

# (mass, length, time, angle). Angle gets its own slot so a plain ratio cannot
# silently bind to a symbol declared in degrees.
Dimension = tuple[int, int, int, int]

_DIMENSIONLESS: Dimension = (0, 0, 0, 0)

# factor to SI base (kg, m, s, rad), and dimension
_ATOMS: dict[str, tuple[float, Dimension]] = {
    "kg": (1.0, (1, 0, 0, 0)),
    "g": (1e-3, (1, 0, 0, 0)),
    "t": (1e3, (1, 0, 0, 0)),
    "m": (1.0, (0, 1, 0, 0)),
    "mm": (1e-3, (0, 1, 0, 0)),
    "cm": (1e-2, (0, 1, 0, 0)),
    "km": (1e3, (0, 1, 0, 0)),
    "s": (1.0, (0, 0, 1, 0)),
    "N": (1.0, (1, 1, -2, 0)),
    "kN": (1e3, (1, 1, -2, 0)),
    "MN": (1e6, (1, 1, -2, 0)),
    "Pa": (1.0, (1, -1, -2, 0)),
    "kPa": (1e3, (1, -1, -2, 0)),
    "MPa": (1e6, (1, -1, -2, 0)),
    "GPa": (1e9, (1, -1, -2, 0)),
    "rad": (1.0, (0, 0, 0, 1)),
    "deg": (math.pi / 180.0, (0, 0, 0, 1)),
}

# Compound spellings that appear in real tables and headers, expanded before parsing.
_ALIASES = {
    "kNm": "kN*m",
    "kNmm": "kN*mm",
    "Nm": "N*m",
    "Nmm": "N*mm",
}

# Human names for the dimensions this package actually traffics in — an error
# saying "expected a density, got a stress" is worth more than an exponent tuple.
_DIMENSION_NAMES: dict[Dimension, str] = {
    _DIMENSIONLESS: "dimensionless",
    (1, 0, 0, 0): "mass",
    (0, 1, 0, 0): "length",
    (0, 2, 0, 0): "area",
    (0, 3, 0, 0): "volume",
    (0, 0, 1, 0): "time",
    (0, 0, 0, 1): "angle",
    (1, 1, -2, 0): "force",
    (1, 2, -2, 0): "moment",
    (1, -1, -2, 0): "stress",
    (1, -3, 0, 0): "density",
}

_ATOM = re.compile(r"^([A-Za-z]+)(?:\^(-?\d+))?$")

# `name[unit]` — the one bracket convention shared by KB keys and FEM headers.
_BRACKETED = re.compile(r"^\s*([^\[\]]+?)\s*(?:\[\s*([^\[\]]*?)\s*\])?\s*$")

_SUPERSCRIPTS = str.maketrans({"²": "^2", "³": "^3", "⁴": "^4"})


@dataclass(frozen=True)
class Unit:
    """A parsed unit: how to reach SI base, and what dimension it is."""

    text: str
    factor: float
    dimension: Dimension

    @property
    def dimension_name(self) -> str:
        return _DIMENSION_NAMES.get(self.dimension, f"dimension {self.dimension}")


def split_unit(text: str) -> tuple[str, str]:
    """``"rho_k[kg/m^3]"`` -> ``("rho_k", "kg/m^3")``; ``"n"`` -> ``("n", "")``.

    One convention for KB property keys and FEM column headers alike, so there
    is exactly one place where a unit can be attached to a name.
    """
    match = _BRACKETED.match(text)
    if match is None or not match.group(1).strip():
        raise DesignCheckError(
            f"{text!r} is not a 'name' or 'name[unit]' declaration"
        )
    return match.group(1).strip(), (match.group(2) or "").strip()


def parse_unit(text: str) -> Unit:
    """Parse a unit string into its SI factor and dimension.

    Accepts ``""``/``"-"``/``"1"`` for dimensionless, ``*``/``·`` products,
    a single ``/`` for the denominator, ``^n`` exponents and the ``²``/``³``
    superscripts that make a KB file readable.
    """
    normalised = text.strip().translate(_SUPERSCRIPTS).replace("·", "*")
    if normalised in ("", "-", "1", "%"):
        # `%` is a display convention, not a dimension; treat it as a ratio.
        return Unit(text=text, factor=1.0, dimension=_DIMENSIONLESS)
    normalised = _ALIASES.get(normalised, normalised)

    parts = normalised.split("/")
    if len(parts) > 2:
        raise DesignCheckError(
            f"unit {text!r} has more than one '/'; write 'kg/(m^3)' as 'kg/m^3'"
        )
    factor = 1.0
    dimension = list(_DIMENSIONLESS)
    for sign, group in ((1, parts[0]), (-1, parts[1] if len(parts) == 2 else "")):
        for atom in (a for a in group.split("*") if a.strip()):
            atom_factor, atom_dimension, exponent = _atom(atom, text)
            factor *= atom_factor ** (sign * exponent)
            for index, power in enumerate(atom_dimension):
                dimension[index] += sign * exponent * power
    return Unit(text=text, factor=factor, dimension=(dimension[0], dimension[1], dimension[2], dimension[3]))


def _atom(atom: str, whole: str) -> tuple[float, Dimension, int]:
    match = _ATOM.match(atom.strip())
    if match is None:
        raise DesignCheckError(f"unit {whole!r}: cannot read the part {atom.strip()!r}")
    name, exponent = match.group(1), int(match.group(2) or 1)
    if name not in _ATOMS:
        raise DesignCheckError(
            f"unit {whole!r}: unknown unit {name!r}; known units: "
            f"{', '.join(sorted(_ATOMS))}"
        )
    factor, dimension = _ATOMS[name]
    return factor, dimension, exponent


def convert(value: float, source: str, target: str, *, what: str) -> float:
    """``value`` expressed in ``source``, restated in ``target``.

    A dimension mismatch is refused by name — this is the tripwire, and it
    fires at ingest, at KB load and at symbol binding, never mid-calculation.
    """
    from_unit, to_unit = parse_unit(source), parse_unit(target)
    if from_unit.dimension != to_unit.dimension:
        raise DesignCheckError(
            f"{what}: expected {to_unit.dimension_name} ({target or 'dimensionless'}), "
            f"got {from_unit.dimension_name} ({source or 'dimensionless'})"
        )
    return value * from_unit.factor / to_unit.factor
