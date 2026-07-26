"""``grouping`` — dividing a population of member forces into connection groups.

Today's RFEM example takes **one** governing force — the maximum ``|Vz|`` across
every beam end — and designs **one** connection for it. That is the degenerate
case of a general question::

    given the forces at every member end,
    how do you divide them into groups, each of which gets one connection design?

A **grouping strategy** is one answer to that question. This pack is the seam
that makes the answer swappable:

* :mod:`grouping.contract` — what a strategy receives, what it returns, and the
  invariants it must uphold. Read this first.
* :mod:`grouping.registry` — the named lookup, and the front door
  (:func:`~grouping.registry.apply_strategy`) where the contract is enforced.
* :mod:`grouping.single`, :mod:`grouping.tiered` — the two shipped strategies,
  each an ordinary registration with no privileged path.
* :func:`group` — the one node: a population in, N groups out.

``docs/grouping-strategies.md`` is the guide; ``.agents/skills/grouping-strategy``
is the skill that authors and audits strategies against it.

**Why this pack knows nothing about RFEM.** A strategy decides on one number per
member end and treats everything else about a record as opaque provenance. That
is what lets the same two strategies work on a population from an RFEM export, a
hand-typed table or a different FE package: :func:`rfem.member_ends` owns the
knowledge of what an RFEM export looks like, and this pack owns the knowledge of
what a *group* is. Neither imports the other's vocabulary.

**One node, N groups — not one node per group.** The number of groups is a
property of the *data* (a tier list in a project's inputs), never of the graph.
A graph whose shape changed with the tier count could not be edited on the
canvas without re-authoring it every time a threshold moved, and the summary
would have to be assembled from N wires. So :func:`group` returns all N groups
on one socket, and one summary node (``sheet.group_card``) renders them as one
card with a row per group. The accepted cost is that the per-group arithmetic
happens inside a node instead of being individually openable on the canvas.

Pure standard library.
"""

from __future__ import annotations

from engine import UserError, node

from .contract import (
    Group,
    Strategy,
    StrategyContractError,
    check_invariants,
    force_of,
    governing_by_magnitude,
    population_unit,
    reject_unknown_params,
    validate_population,
)
from .registry import apply_strategy, get_strategy, register, strategy_names

# Importing a strategy module is what registers it — one import line per
# strategy, which is the whole "a third strategy is an addition, not an edit"
# claim made concrete. Imported for the side effect; re-exported so
# `grouping.tiered` also names the module a reader wants to open.
from . import single as single  # noqa: F401 - imported for its registration
from . import tiered as tiered  # noqa: F401 - imported for its registration

# The key in a grouping config that names the strategy, and the key holding
# that strategy's own parameters.
STRATEGY = "strategy"
PARAMS = "params"


@node
def group(population: list, config: dict = None) -> dict:
    """Divide a population of member-end forces into connection groups.

    ``population`` is a list of force records — mappings carrying a magnitude
    under ``value``, a ``unit``, a human ``ref``, and whatever provenance their
    producer attached (wire it from :func:`rfem.member_ends`).

    ``config`` selects the strategy and configures it::

        {"strategy": "single"}
        {"strategy": "tiered", "params": {"thresholds": [150, 50]}}

    **Why the parameters are nested** rather than sitting beside ``strategy``:
    ``params`` is the strategy's own namespace, so a strategy may name a
    parameter anything it likes without ever colliding with a key this envelope
    might grow later (a ``ref``, a ``version``, a second selector). Flattened,
    adding one envelope key would silently turn an existing parameter into a
    reserved word. ``params`` may be omitted when the strategy takes none.

    Returns one record describing the whole division::

        {"strategy", "params", "unit", "count", "groups": [...]}

    where each group carries ``key``, ``label``, ``count``, the ``governing``
    record **verbatim** (so the member, node, position and load case survive
    into the design), the ``member_refs`` of everything that fell in it, and any
    strategy-specific ``extra`` descriptors.

    Every failure here is the user's to fix and says so: an unknown strategy
    lists the ones that exist, a bad parameter names itself, and an empty group
    names the group and its bounds.
    """
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise UserError(
            f"the 'config' input must be a grouping config object such as "
            f"{{'strategy': 'tiered', 'params': {{'thresholds': [150, 50]}}}} "
            f"(wire it from sources.pick), got {type(config).__name__}"
        )
    unknown = [key for key in config if key not in (STRATEGY, PARAMS)]
    if unknown:
        raise UserError(
            f"grouping config has unexpected key(s) "
            f"{', '.join(repr(k) for k in unknown)}; it holds {STRATEGY!r} and "
            f"an optional {PARAMS!r} object — a strategy's own parameters go "
            f"inside {PARAMS!r}"
        )
    if STRATEGY not in config:
        raise UserError(
            f"grouping config has no {STRATEGY!r} key; available strategies: "
            f"{', '.join(repr(n) for n in strategy_names()) or '(none)'}"
        )
    name = config[STRATEGY]
    params = config.get(PARAMS) or {}

    records = validate_population(population)
    groups = apply_strategy(name, records, params)
    return {
        "strategy": name,
        "params": dict(params),
        "unit": population_unit(records),
        "count": len(records),
        "groups": [g.to_dict() for g in groups],
    }


NODES = [group]

__all__ = [
    "Group",
    "NODES",
    "PARAMS",
    "STRATEGY",
    "Strategy",
    "StrategyContractError",
    "apply_strategy",
    "check_invariants",
    "force_of",
    "governing_by_magnitude",
    "group",
    "population_unit",
    "register",
    "reject_unknown_params",
    "strategy_names",
    "get_strategy",
    "validate_population",
]
