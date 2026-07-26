"""``single`` — one group, containing everything.

The degenerate grouping: every member end goes in one group, and the largest
magnitude in the whole population governs it. One group means one connection
design, which is what a project does when it standardises on a single detail
sized for the worst case.

This is exactly what ``rfem.governing_force`` has always computed, and that is
the point: the strategy that ships today is an **ordinary implementation of the
contract**, not a bypass around it. It goes through
:func:`grouping.registry.apply_strategy` like any other, gets its population
validated and its invariants checked like any other, and it reproduces the same
number the older node does on the same data.

Reading it as a worked example of the contract:

* **What governs a group** — the largest magnitude, via
  :func:`grouping.contract.governing_by_magnitude`, whose tie-break keeps the
  answer independent of the population's order.
* **Boundaries** — there are none: there is only one group, so no member end is
  ever near an edge.
* **What an empty group means** — unreachable here. ``validate_population``
  already refused an empty population, so the one group always has members.
* **Provenance** — the governing record is handed back *as it came in*, so the
  member, node, position and load case reach the card untouched.

Pure standard library.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .contract import Group, governing_by_magnitude, reject_unknown_params
from .registry import register

__all__ = ["ACCEPTED_PARAMS", "KEY", "LABEL", "single"]

# The key the summary card suffixes symbols with: `eta` becomes `eta_all`.
KEY = "all"
LABEL = "all member ends"

# `single` has nothing to configure. Declaring that explicitly (rather than
# ignoring whatever arrives) is what turns `{"strategy": "single", "params":
# {"thresholds": [150]}}` into an error saying the thresholds were not read —
# the user meant `tiered`.
ACCEPTED_PARAMS: tuple[str, ...] = ()


def single(
    population: Sequence[Mapping[str, object]], params: Mapping[str, object]
) -> list[Group]:
    """One group over the whole population, governed by its largest magnitude."""
    reject_unknown_params(params, strategy="single", accepted=ACCEPTED_PARAMS)
    members = tuple(population)
    return [
        Group(
            key=KEY,
            label=LABEL,
            members=members,
            governing=governing_by_magnitude(members),
        )
    ]


register(
    "single",
    single,
    summary="one group over every member end, governed by the overall maximum",
)
