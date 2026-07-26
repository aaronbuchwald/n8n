"""``tiered`` — load bands the user names, one connection design per band.

The user states the thresholds an engineer would state in a meeting: "above
150 kN one detail, above 50 kN another, the rest a third". Two thresholds
therefore make **three** tiers::

    thresholds = [150, 50]

    T1  [150, ∞)   the heaviest ends
    T2  [50, 150)
    T3  [0, 50)    everything left

Reading it as a worked example of the contract:

* **What governs a tier** — the largest magnitude *within that tier*, via
  :func:`grouping.contract.governing_by_magnitude`. Each tier is designed for
  its own worst case, which is the entire reason for tiering: the light
  connections stop paying for the heavy ones.
* **Boundaries** — every tier is **half-open**, ``[lower, upper)``, so a value
  exactly on a threshold falls in the tier the threshold **opens**, i.e. the
  *upper* one. With thresholds 600 and 400, exactly ``400.0`` belongs to
  ``[400, 600)``, not to ``[0, 400)``. Half-open is not a coin toss: it is the
  only convention under which "≥ 400 kN gets the heavier detail" reads the same
  in the parameters as it does in the drawing, and it is the only one where
  adjacent tiers can neither overlap nor leave a gap.
* **What an empty tier means** — an **error**, naming the tier and its bounds.
  A tier nobody falls into is almost always a threshold in the wrong place (or
  in the wrong unit), and quietly dropping it would turn "three connection
  types" into two without saying so. Invariant 3 is enforced for every strategy
  anyway; this module raises first, with a message that names the actual bounds
  and the range the data does span, because "group 'T1' is empty" is much less
  help than "no member end reaches 600 kN; the largest is 297.176 kN".
* **Provenance** — every record is carried through untouched, and the governing
  one is a member of its own tier, so each tier's row on the card cites the real
  member, node, position and load case its number came from.

**Thresholds are declared descending** — ``[150, 50]``, heaviest first — because
that is the order the tiers themselves are in, the order they are read out, and
the order they appear on the card. An ascending list is refused rather than
sorted: silently reinterpreting the parameters is how a user ends up designing
to a rule they did not write.

Pure standard library.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from engine import UserError

from .contract import (
    REF,
    Group,
    force_of,
    governing_by_magnitude,
    population_unit,
    reject_unknown_params,
)
from .registry import register

__all__ = ["ACCEPTED_PARAMS", "THRESHOLDS", "bands", "format_bound", "tiered"]

THRESHOLDS = "thresholds"
ACCEPTED_PARAMS: tuple[str, ...] = (THRESHOLDS,)

# The unbounded top of the highest tier. A real infinity rather than a very
# large number, so the comparison is exact and the label is honest.
INFINITY = math.inf


def format_bound(value: float) -> str:
    """A bound as it appears in a label: ``150``, ``62.5``, ``∞``."""
    if value == INFINITY:
        return "∞"
    return f"{value:g}"


def bands(thresholds: Sequence[float]) -> list[tuple[float, float]]:
    """The ``(lower, upper)`` pairs a descending threshold list defines.

    ``[150, 50]`` -> ``[(150, ∞), (50, 150), (0, 50)]``. Split out as a plain
    function because it is the part worth reading on its own: *n* thresholds
    always make *n + 1* bands, each band's lower bound is the next threshold
    down, and the last band reaches 0.
    """
    edges = [INFINITY, *thresholds, 0.0]
    return [(edges[i + 1], edges[i]) for i in range(len(edges) - 1)]


def _validate(params: Mapping[str, object]) -> list[float]:
    """The ``thresholds`` parameter, checked and returned as floats."""
    reject_unknown_params(params, strategy="tiered", accepted=ACCEPTED_PARAMS)
    if THRESHOLDS not in params:
        raise UserError(
            "grouping strategy 'tiered' needs a 'thresholds' parameter — the "
            "load levels the tiers are cut at, largest first, e.g. "
            "{'strategy': 'tiered', 'params': {'thresholds': [150, 50]}}"
        )
    raw = params[THRESHOLDS]
    if isinstance(raw, (str, bytes, Mapping)) or not isinstance(raw, Sequence):
        raise UserError(
            f"'thresholds' must be a list of numbers, got {type(raw).__name__}"
        )
    if not raw:
        raise UserError(
            "'thresholds' is empty; with no threshold there is nothing to tier "
            "— use the 'single' strategy to design one connection for everything"
        )

    values: list[float] = []
    for index, item in enumerate(raw):
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise UserError(
                f"threshold {index} is {item!r} ({type(item).__name__}), not a number"
            )
        value = float(item)
        if not math.isfinite(value):
            raise UserError(f"threshold {index} is {item!r}, which is not a finite number")
        if value <= 0:
            raise UserError(
                f"threshold {index} is {format_bound(value)}; thresholds must be "
                f"greater than 0, because the lowest tier already starts at 0 "
                f"and a threshold of 0 would make it the empty range [0, 0)"
            )
        values.append(value)

    for index in range(1, len(values)):
        if values[index] >= values[index - 1]:
            raise UserError(
                f"thresholds must be declared descending, largest first: "
                f"threshold {index} ({format_bound(values[index])}) is not below "
                f"threshold {index - 1} ({format_bound(values[index - 1])}). "
                f"They are not sorted for you — the order you write is the order "
                f"the tiers are designed in."
            )
    return values


def tiered(
    population: Sequence[Mapping[str, object]], params: Mapping[str, object]
) -> list[Group]:
    """One group per load band, each governed by its own largest magnitude."""
    thresholds = _validate(params)
    unit = population_unit(population)
    suffix = f" {unit}" if unit else ""

    negative = next((r for r in population if force_of(r) < 0), None)
    if negative is not None:
        raise UserError(
            f"'tiered' groups by magnitude and the lowest tier starts at 0, but "
            f"{str(negative.get(REF, '')) or 'a member end'} carries "
            f"{force_of(negative):g}{suffix}; feed it magnitudes (a record's "
            f"'value' is the magnitude, its 'signed' companion keeps the sign)"
        )

    groups: list[Group] = []
    for index, (lower, upper) in enumerate(bands(thresholds), start=1):
        label = f"[{format_bound(lower)}, {format_bound(upper)}){suffix}"
        members = tuple(
            record for record in population if lower <= force_of(record) < upper
        )
        if not members:
            largest = max(force_of(record) for record in population)
            smallest = min(force_of(record) for record in population)
            raise UserError(
                f"tier T{index} {label} catches no member end. The population "
                f"spans {smallest:g}{suffix} to {largest:g}{suffix}, so this "
                f"threshold is in the wrong place (or in the wrong unit). An "
                f"empty tier is not dropped silently: it would turn "
                f"{len(thresholds) + 1} connection types into "
                f"{len(thresholds)} without saying so."
            )
        groups.append(
            Group(
                key=f"T{index}",
                label=label,
                members=members,
                governing=governing_by_magnitude(members),
                # `None`, not `inf`, for the open top: `json.dumps` spells a
                # Python infinity `Infinity`, which is not valid JSON, and this
                # dict ends up in a written artifact.
                extra={
                    "lower": lower,
                    "upper": None if upper == INFINITY else upper,
                    "unit": unit,
                },
            )
        )
    return groups


register(
    "tiered",
    tiered,
    summary="one group per user-named load band, each governed by its own maximum",
)
