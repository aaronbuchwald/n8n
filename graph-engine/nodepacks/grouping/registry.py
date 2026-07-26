"""The strategy registry — one named lookup, one enforced front door.

A registry rather than an ``if name == "single": … elif name == "tiered": …``
chain, for one reason: a third strategy must be an **addition**, not an edit.
Adding one is a new module that ends in a :func:`register` call plus one import
line in :mod:`grouping`; no existing file's logic changes, and nothing has to
learn that the new name exists.

:func:`apply_strategy` is the only sanctioned way to run a strategy — the
registry does not just *hold* the implementations, it is where the contract is
enforced. It validates the population before the strategy sees it and checks
invariants 1–5 on what comes back, for every strategy alike. ``single`` gets no
shortcut and ``tiered`` gets no special case; both are ordinary registrations
that go through the same door.

Pure standard library.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from engine import UserError

from .contract import Group, Strategy, check_invariants, validate_population

__all__ = ["apply_strategy", "get_strategy", "register", "strategy_names"]

# name -> (implementation, one-line summary). The summary exists so an error
# message can be *useful*: "unknown strategy 'tier'" is much less help than the
# same sentence followed by what each available name actually does.
_STRATEGIES: dict[str, tuple[Strategy, str]] = {}


def register(name: str, strategy: Strategy, *, summary: str = "") -> Strategy:
    """Register ``strategy`` under ``name``; returns it, so it can decorate.

    Registration is deliberately loud about collisions: two implementations
    claiming one name means a graph's behaviour depends on import order, which
    is exactly the kind of thing that is discovered months later.
    """
    if not isinstance(name, str) or not name:
        raise ValueError(f"a strategy name must be a non-empty string, got {name!r}")
    existing = _STRATEGIES.get(name)
    if existing is not None and existing[0] is not strategy:
        raise ValueError(
            f"a different grouping strategy is already registered as {name!r}; "
            f"pick another name rather than shadowing it"
        )
    _STRATEGIES[name] = (strategy, summary)
    return strategy


def strategy_names() -> list[str]:
    """Every registered name, sorted — the vocabulary, as data."""
    return sorted(_STRATEGIES)


def _catalogue() -> str:
    """``'single' (…), 'tiered' (…)`` — what an unknown-name error lists."""
    parts = []
    for name in strategy_names():
        summary = _STRATEGIES[name][1]
        parts.append(f"{name!r} ({summary})" if summary else repr(name))
    return ", ".join(parts) or "(none registered)"


def get_strategy(name: object) -> Strategy:
    """Look up a strategy by name, or raise listing what exists.

    The listing is the point: a misremembered name is the most likely way to
    meet this error, and the answer is always one of the names it prints.
    """
    if not isinstance(name, str):
        raise UserError(
            f"a grouping strategy is named by a string, got {name!r} "
            f"({type(name).__name__}); available strategies: {_catalogue()}"
        )
    entry = _STRATEGIES.get(name)
    if entry is None:
        raise UserError(
            f"unknown grouping strategy {name!r}; available strategies: "
            f"{_catalogue()}"
        )
    return entry[0]


def apply_strategy(
    name: object,
    population: object,
    params: Mapping[str, object] | None = None,
) -> tuple[Group, ...]:
    """Resolve ``name``, run it over ``population``, and enforce the contract.

    Three steps, none of them skippable:

    1. :func:`grouping.contract.validate_population` — so every strategy is
       handed a population it can trust, and none has to re-check it;
    2. the strategy itself, which validates its own ``params``;
    3. :func:`grouping.contract.check_invariants` — so a strategy that quietly
       drops or double-counts a member end fails loudly at the point of the
       mistake instead of producing a design that is silently wrong.
    """
    strategy = get_strategy(name)
    records = validate_population(population)
    if params is None:
        params = {}
    if not isinstance(params, Mapping):
        raise UserError(
            f"the parameters of grouping strategy {name!r} must be an object, "
            f"got {type(params).__name__}"
        )
    groups: Sequence[Group] = strategy(records, params)
    return check_invariants(groups, records, strategy=str(name))
