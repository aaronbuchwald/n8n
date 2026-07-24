"""Declarative, closed applicability predicates — knowledge-base content never executes.

A clause says when it governs with strings like ``"fastener.d <= 6.0"`` or
``"members.all_timber"``. They are matched against a flat table of *facts*
derived from the connection and the config, by a hand-written comparison — not
by ``eval``. KB files must stay reviewable data, and the sandbox posture must
not be undermined by executable knowledge-base content.

A predicate naming a fact that does not exist is an error, never a quiet
``False``: a typo in a KB file must not silently drop a clause from a proof.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from .config import DesignConfig
from .connections import ScrewConnection
from .errors import DesignCheckError

Fact = float | int | str | bool

_COMPARISON = re.compile(
    r"^\s*(?P<name>[A-Za-z_][A-Za-z_0-9.]*)\s*(?P<op>==|!=|<=|>=|<|>)\s*(?P<literal>.+?)\s*$"
)
_BARE = re.compile(r"^\s*(?P<negated>not\s+)?(?P<name>[A-Za-z_][A-Za-z_0-9.]*)\s*$")
_NUMBER = re.compile(r"^-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$")

_ORDERED_OPS = {
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
}


def facts(connection: ScrewConnection, config: DesignConfig) -> Mapping[str, Fact]:
    """The flat, dotted table a predicate may ask about.

    Deliberately shallow and finite: everything a clause can branch on is
    listed here, so the vocabulary is auditable from one function.
    """
    return {
        "connection.kind": connection.kind,
        "connection.name": connection.name,
        "connection.n": connection.n,
        "connection.shear_planes": connection.shear_planes,
        "connection.spacing": connection.spacing,
        "connection.angle_to_grain": connection.angle_to_grain,
        "fastener.d": connection.fastener.d,
        "fastener.L": connection.fastener.L,
        "fastener.f_uk": connection.fastener.f_uk,
        "members.count": len(connection.members),
        "members.all_timber": connection.all_timber,
        "members.any_timber": any(member.is_timber for member in connection.members),
        "members.roles": ",".join(member.role for member in connection.members),
        "config.service_class": config.service_class,
        "config.load_duration": config.load_duration,
        "config.target_utilisation": config.target_utilisation,
    }


def evaluate_predicate(text: str, known: Mapping[str, Fact], *, what: str) -> bool:
    """Evaluate one predicate against ``known``, or refuse it by name."""
    bare = _BARE.match(text)
    if bare is not None:
        value = _fact(bare.group("name"), known, what=what, predicate=text)
        if not isinstance(value, bool):
            raise DesignCheckError(
                f"{what}: predicate {text!r} uses {bare.group('name')!r} as a flag, but it "
                f"is {type(value).__name__}; compare it instead, e.g. "
                f"'{bare.group('name')} == ...'"
            )
        return not value if bare.group("negated") else value

    comparison = _COMPARISON.match(text)
    if comparison is None:
        raise DesignCheckError(
            f"{what}: cannot read predicate {text!r}; write 'fact', 'not fact' or "
            f"'fact <op> literal' with <op> one of ==, !=, <, <=, >, >="
        )
    name, operator = comparison.group("name"), comparison.group("op")
    left = _fact(name, known, what=what, predicate=text)
    right = _literal(comparison.group("literal"), what=what, predicate=text)

    if operator in ("==", "!="):
        equal = _equal(left, right)
        return equal if operator == "==" else not equal
    if not _numeric(left) or not _numeric(right):
        raise DesignCheckError(
            f"{what}: predicate {text!r} orders {type(left).__name__} against "
            f"{type(right).__name__}; <, <=, > and >= need two numbers"
        )
    return _ORDERED_OPS[operator](float(left), float(right))


def applies(predicates: tuple[str, ...], known: Mapping[str, Fact], *, what: str) -> bool:
    """True when every predicate holds — an empty list means "always applicable"."""
    return all(evaluate_predicate(predicate, known, what=what) for predicate in predicates)


def _fact(name: str, known: Mapping[str, Fact], *, what: str, predicate: str) -> Fact:
    if name not in known:
        raise DesignCheckError(
            f"{what}: predicate {predicate!r} names unknown fact {name!r}; known facts: "
            f"{', '.join(sorted(known))}"
        )
    return known[name]


def _literal(text: str, *, what: str, predicate: str) -> Fact:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    if text in ("true", "false"):
        return text == "true"
    if _NUMBER.match(text):
        return float(text)
    raise DesignCheckError(
        f"{what}: predicate {predicate!r} has literal {text!r}; a literal must be a "
        f"number, true/false, or a quoted string"
    )


def _numeric(value: Fact) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _equal(left: Fact, right: Fact) -> bool:
    # bools compare to bools, numbers to numbers, strings to strings — so
    # `connection.n == 'screw'` is False rather than a confusing TypeError.
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if _numeric(left) and _numeric(right):
        return float(left) == float(right)
    if isinstance(left, str) and isinstance(right, str):
        return left == right
    return False
