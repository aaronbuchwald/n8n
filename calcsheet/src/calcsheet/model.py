"""The declarative model: a calc is DATA, not decorated Python source.

Nothing here computes anything. A :class:`Calc` is an inert description —
given quantities, formulas over them, and the checks that decide whether the
result is acceptable — so it can be built, stored, diffed and shipped without
ever running. :meth:`Calc.evaluate` is the only door to numbers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid a model <-> evaluate import cycle at runtime
    from .evaluate import Result


@dataclass(frozen=True)
class Input:
    """A given quantity: a number that arrives from outside the calc.

    ``ref`` is provenance shown in the row's right-hand gutter (``"forces.csv
    · max"``); ``unit`` is a plain display string — this package does no unit
    algebra, so the author owns dimensional consistency.
    """

    value: float
    ref: str = ""
    unit: str = ""


@dataclass(frozen=True)
class Formula:
    """A derived quantity: ``symbol = expr`` over previously defined symbols.

    ``expr`` is expression text parsed by sympy (``"F_max / C_min"``).
    Formulas evaluate in declaration order, so ``expr`` may only name inputs
    and formulas declared *before* it.
    """

    symbol: str
    expr: str
    ref: str = ""
    unit: str = ""


@dataclass(frozen=True)
class Check:
    """A design check: a boolean expression over the final scope.

    ``expr`` must be relational or boolean (``"U < 100"``, ``"r > 0"``) — a
    plain number is not a verdict and is rejected. ``description`` says what
    the check is *for*, in prose.

    ``utilisation`` optionally names the symbol whose value *is* this check's
    utilisation (usually the left-hand side). It augments the verdict, never
    replaces it: geometry checks like ``"spacing >= 4 * d"`` are naturally
    boolean and stay that way, and ``passed`` remains authoritative.
    """

    expr: str
    description: str = ""
    utilisation: str = ""


@dataclass(frozen=True)
class Calc:
    """A complete calculation, ready to evaluate and render.

    ``as_of`` is a caller-provided date string and is never derived from the
    clock: an artifact that re-renders differently tomorrow is not an
    artifact. ``precision`` is significant digits for displayed values.
    """

    title: str
    as_of: str
    inputs: Mapping[str, Input] = field(default_factory=dict)
    formulas: Sequence[Formula] = ()
    checks: Sequence[Check] = ()
    precision: int = 3

    def evaluate(self) -> Result:
        """Run the calc once and return its :class:`~calcsheet.evaluate.Result`."""
        from .evaluate import evaluate_calc

        return evaluate_calc(self)
