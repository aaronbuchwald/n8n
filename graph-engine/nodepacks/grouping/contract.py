"""The grouping-strategy contract — what a strategy is handed, what it owes back.

A **grouping strategy** answers one question: *given the forces at every member
end, how are they divided into groups, each of which gets one connection
design?* Everything else about grouping — the registry, the node, the summary
card — is machinery around that one answer.

This module is the contract itself, and nothing else: no strategy is
implemented here, no node is declared here, and nothing here knows what RFEM,
a bearing check or a calc card is. See :mod:`grouping.registry` for the lookup
seam, :mod:`grouping.single` / :mod:`grouping.tiered` for the shipped
implementations, and ``docs/grouping-strategies.md`` for the guide.

**What a strategy receives.** Two arguments, both already validated:

* ``population`` — an ordered tuple of **force records**. Each is a mapping
  carrying a finite number under ``value`` (its magnitude), a display ``unit``,
  and a human ``ref`` naming the row it came from, plus any amount of extra
  provenance the producer chose to attach (member, node, position, load case,
  source file …). A strategy reads ``value`` to decide, and otherwise treats a
  record as **opaque**: it never rebuilds one, never edits one, and hands the
  originals back inside its groups. That is the whole mechanism by which
  provenance survives grouping.
* ``params`` — the strategy's own parameters as a plain JSON mapping
  (``{"thresholds": [150, 50]}``). A strategy validates its own params and
  raises :class:`engine.UserError` with a sentence a user can act on; unknown
  keys are a typo and must be refused, never ignored.

**What a strategy returns.** An ordered sequence of :class:`Group`. The order is
the strategy's editorial choice — it is the order the summary card's rows appear
in — and must be a deterministic function of the input, not of dict or file
order.

**The invariants**, enforced for every strategy by
:func:`grouping.registry.apply_strategy` (see :func:`check_invariants`):

1. **Total** — every record in the population lands in some group.
2. **Exclusive** — no record lands in two groups. (1) + (2) together are what
   make the word *partition* honest: a member end designed twice, or not at all,
   is a silent engineering error.
3. **Non-empty** — no group has zero members. A group nobody falls into is
   almost always a mistake in the parameters, and dropping it silently hides
   the mistake.
4. **Governing is a real member** — a group's ``governing`` record must be
   *identically* one of its own ``members``. A strategy therefore cannot
   synthesise a governing value, and the provenance on the card is the
   population's own.
5. **Keys are identifiers and unique** — a group's ``key`` is used to derive
   symbol names on the summary card, so it must be a valid Python identifier and
   distinct within one result.

Two further obligations are the author's, because no cheap runtime check proves
them (the guide explains how to test them instead):

6. **Deterministic** — the same population and params always give the same
   groups, byte for byte.
7. **Order-independent** — shuffling the population changes nothing, *including*
   which record governs. That forbids the obvious ``max(members, key=force)``:
   Python's ``max`` returns the first maximal element in iteration order, so a
   tie silently depends on file order. Use :func:`governing_by_magnitude`, whose
   tie-break is the record's ``ref``.

Pure standard library.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Callable

from engine import EngineError, UserError

__all__ = [
    "Group",
    "Strategy",
    "StrategyContractError",
    "check_invariants",
    "force_of",
    "governing_by_magnitude",
    "population_unit",
    "reject_unknown_params",
    "validate_population",
]

# The record keys this contract gives meaning to. Everything else a producer
# attaches is provenance a strategy must carry through untouched.
VALUE = "value"
UNIT = "unit"
REF = "ref"


@dataclass(frozen=True)
class Group:
    """One connection group — the unit a single design is produced for.

    ``key``
        A short identifier (``"T1"``, ``"all"``), unique within one result. It
        is not decoration: the summary card suffixes the calculation's symbols
        with it (``eta`` becomes ``eta_T1``), so it must be a valid Python
        identifier.
    ``label``
        What a reviewer reads — the range, the population, whatever the strategy
        considers this group to *be* (``"[150, ∞) kN"``). Free text.
    ``members``
        Every force record that fell in this group, as handed in. Order follows
        the strategy's own; ``count`` is derived from it rather than declared,
        so the two can never disagree.
    ``governing``
        The one member whose force this group is designed for. Must be
        identically an element of ``members`` (invariant 4).
    ``extra``
        Strategy-specific descriptors a consumer may read but nothing requires —
        ``tiered`` puts its numeric ``lower``/``upper`` bounds here so a
        different renderer can format the range its own way instead of parsing
        ``label``.
    """

    key: str
    label: str
    members: tuple[Mapping[str, object], ...]
    governing: Mapping[str, object]
    extra: Mapping[str, object] = field(default_factory=dict)

    @property
    def count(self) -> int:
        """How many member ends fell in this group."""
        return len(self.members)

    def to_dict(self) -> dict:
        """The group as plain JSON — what travels on a socket.

        The members are reduced to their ``ref`` strings. The full records would
        be hundreds of near-duplicate objects on a wire whose consumers want a
        count and a governing row; the refs keep the partition **auditable**
        (you can read the artifact and check by hand that every member end
        appears exactly once) at a fraction of the size.
        """
        return {
            "key": self.key,
            "label": self.label,
            "count": self.count,
            "governing": dict(self.governing),
            "member_refs": [str(member.get(REF, "")) for member in self.members],
            "extra": dict(self.extra),
        }


# ``strategy(population, params) -> groups``. Spelled out rather than left
# implicit because it is the seam: a third strategy is a function of this shape
# plus one `register(...)` call.
Strategy = Callable[
    [tuple[Mapping[str, object], ...], Mapping[str, object]], Sequence[Group]
]


# -- reading a force record ---------------------------------------------------


def force_of(record: Mapping[str, object]) -> float:
    """The magnitude a record carries, as a ``float``.

    The one accessor every strategy uses, so "what a strategy decides on" has a
    single definition. Assumes :func:`validate_population` already ran.
    """
    return float(record[VALUE])  # type: ignore[arg-type]


def governing_by_magnitude(
    members: Sequence[Mapping[str, object]],
) -> Mapping[str, object]:
    """The largest-magnitude member, with an order-independent tie-break.

    ``max(members, key=force_of)`` would satisfy "the largest force governs" and
    still violate invariant 7: on a tie it returns whichever equal-valued record
    the iteration reached first, so re-ordering the export changes which member
    end the card cites. Sorting by ``(-value, ref)`` makes the answer a function
    of the *records*, not of their order — and two records with the same
    magnitude and the same ref are indistinguishable anyway.

    A strategy that governs by something else (a percentile, a per-support
    envelope) simply does not call this — "what governs a group" is a design
    question the strategy owns, and the framework only checks that the answer is
    one of the group's own members.
    """
    return min(members, key=lambda record: (-force_of(record), str(record.get(REF, ""))))


# -- validating what goes in --------------------------------------------------


def validate_population(
    population: object,
) -> tuple[Mapping[str, object], ...]:
    """Check and normalise a population, so no strategy has to re-check it.

    Refuses, with a sentence naming the offending element:

    * anything that is not an ordered sequence of records (a bare mapping or a
      string is a wiring mistake, not a population of one);
    * an empty population — there is nothing to divide, and every strategy would
      otherwise have to invent an answer;
    * an element that is not a mapping, or has no ``value``;
    * a ``value`` that is not a finite real number (``bool`` is an ``int``
      subclass, and a flag is not a force);
    * a non-string ``unit``/``ref``;
    * **mixed units** — a population whose records disagree about their unit is
      not a population of comparable forces, and a threshold in it would mean
      two things at once.

    Returns the records as a tuple, unchanged and in order.
    """
    if isinstance(population, (str, bytes, Mapping)) or not isinstance(
        population, Sequence
    ):
        raise UserError(
            f"a population must be a list of force records (wire it from a node "
            f"that produces one, e.g. rfem.member_ends), got "
            f"{type(population).__name__}"
        )
    records = tuple(population)
    if not records:
        raise UserError(
            "the population is empty: there are no member-end forces to group "
            "(check the filter on the node that produced it)"
        )

    unit: str | None = None
    for index, record in enumerate(records):
        where = f"population entry {index}"
        if not isinstance(record, Mapping):
            raise UserError(
                f"{where} is {type(record).__name__}, not a force record; a "
                f"record is a mapping carrying at least {{'value': …}}"
            )
        if VALUE not in record:
            raise UserError(
                f"{where} has no {VALUE!r} key; it has: "
                f"{', '.join(repr(k) for k in record) or '(nothing)'}"
            )
        value = record[VALUE]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise UserError(
                f"{where}: {VALUE!r} is {value!r} ({type(value).__name__}), "
                f"which is not a force"
            )
        if not math.isfinite(float(value)):
            raise UserError(f"{where}: {VALUE!r} is {value!r}, which is not a finite number")
        for field_name in (UNIT, REF):
            text = record.get(field_name, "")
            if not isinstance(text, str):
                raise UserError(
                    f"{where}: {field_name!r} must be a string, got {text!r} "
                    f"({type(text).__name__})"
                )
        this_unit = str(record.get(UNIT, ""))
        if unit is None:
            unit = this_unit
        elif this_unit != unit:
            raise UserError(
                f"{where} is in {this_unit!r} but earlier entries are in "
                f"{unit!r}; one population must be one unit, or a threshold in "
                f"it would mean two different things"
            )
    return records


def population_unit(population: Sequence[Mapping[str, object]]) -> str:
    """The unit every record in a validated population shares (possibly ``""``)."""
    return str(population[0].get(UNIT, "")) if population else ""


def reject_unknown_params(
    params: Mapping[str, object], *, strategy: str, accepted: Sequence[str]
) -> None:
    """Refuse a parameter this strategy does not read.

    Ignoring an unrecognised key is how a typo becomes a silently wrong design:
    ``{"threshold": [150, 50]}`` would leave ``tiered`` with no thresholds at
    all. The message lists what the strategy *does* accept.
    """
    unknown = [key for key in params if key not in accepted]
    if unknown:
        accepted_text = ", ".join(repr(k) for k in accepted) or "(no parameters)"
        raise UserError(
            f"grouping strategy {strategy!r} does not take "
            f"{', '.join(repr(k) for k in unknown)}; it accepts: {accepted_text}"
        )


# -- checking what comes back -------------------------------------------------


class StrategyContractError(EngineError):
    """A strategy broke the contract — a bug in the strategy, not in its input.

    Deliberately **not** a :class:`engine.UserError`: the user cannot fix it by
    editing a threshold. It names the strategy so the report points at the file
    to open.
    """


def check_invariants(
    groups: Sequence[Group],
    population: Sequence[Mapping[str, object]],
    *,
    strategy: str,
) -> tuple[Group, ...]:
    """Enforce invariants 1–5 on a strategy's result; return it as a tuple.

    Runs for **every** strategy on **every** call, including the two shipped
    ones: the contract is only worth writing down if nothing gets to skip it.
    The checks are all O(n) over the population, so this is cheap enough to keep
    on in production, where it turns a subtle wrong number into a loud error.

    Identity (``id()``), not equality, decides membership: two member ends can
    carry equal values and equal provenance and still be two distinct ends, and
    the partition must be about the objects that went in.
    """

    def fail(message: str) -> StrategyContractError:
        return StrategyContractError(
            f"grouping strategy {strategy!r} broke its contract: {message}"
        )

    if isinstance(groups, (str, bytes, Mapping)) or not isinstance(groups, Sequence):
        raise fail(f"it returned {type(groups).__name__}, not a sequence of Group")
    result = tuple(groups)
    if not result:
        raise fail("it returned no groups; every population divides into at least one")

    seen_keys: dict[str, int] = {}
    for index, group in enumerate(result):
        if not isinstance(group, Group):
            raise fail(f"entry {index} is {type(group).__name__}, not a Group")
        if not group.key.isidentifier():
            raise fail(
                f"group {index} has key {group.key!r}, which is not a valid "
                f"identifier (keys become symbol suffixes on the summary card)"
            )
        if group.key in seen_keys:
            raise fail(
                f"groups {seen_keys[group.key]} and {index} share the key "
                f"{group.key!r}; keys must be unique"
            )
        seen_keys[group.key] = index
        if not group.members:
            raise fail(
                f"group {group.key!r} ({group.label}) is empty — invariant 3 "
                f"says a strategy must not return a group nobody falls into"
            )
        if not any(member is group.governing for member in group.members):
            raise fail(
                f"group {group.key!r} governs by a record that is not one of its "
                f"own members, so its provenance is invented rather than carried"
            )

    # Total + exclusive, by object identity and by *multiplicity*: counting
    # rather than set membership means a population that legitimately holds the
    # same record object twice is still checked correctly.
    placed: Counter[int] = Counter()
    owner: dict[int, str] = {}
    for group in result:
        for member in group.members:
            placed[id(member)] += 1
            owner.setdefault(id(member), group.key)
    wanted = Counter(id(record) for record in population)

    foreign = [i for i in placed if i not in wanted]
    if foreign:
        raise fail(
            f"group {owner[foreign[0]]!r} contains a record that was not in the "
            f"population; a strategy divides what it was given, it does not "
            f"add to it"
        )
    for index, record in enumerate(population):
        got, want = placed[id(record)], wanted[id(record)]
        if got > want:
            raise fail(
                f"member end {index} ({record.get(REF, '')!r}) lands in "
                f"{got} groups but exists {want} time(s); the groups must "
                f"partition the population, not overlap it"
            )
        if got < want:
            raise fail(
                f"member end {index} ({record.get(REF, '')!r}) fell in no group "
                f"at all; the groups must cover the whole population"
            )
    return result
