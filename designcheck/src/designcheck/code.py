"""T5/T6 — the building code as data: factor tables, clauses, and the symbol dictionary.

A clause is an identifier, a formula, its applicability conditions and the
citation text — nothing else. Its formula language is ``calcsheet``'s existing
expression language, so a clause is precisely one prospective ``Formula`` or
``Check`` row and there is no second evaluator anywhere in this package.

``SymbolSpec`` is the code's dictionary of leaf symbols: what each one means
dimensionally and where the resolver may fetch it from. Keeping it as KB data
(rather than a table hard-coded in the resolver) is what lets a second code
name its own factors without touching Python.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .errors import DesignCheckError
from .materials import KbRef

CLAUSE_KINDS = ("formula", "check")


@dataclass(frozen=True)
class Clause:
    """One rule of a code, in the form the resolver can compile."""

    id: str
    citation: str
    title: str
    kind: str
    formula: str = ""  # kind="formula": calcsheet expression text
    defines: str = ""  # kind="formula": the symbol it yields
    check: str = ""  # kind="check": relational expression
    utilisation: str = ""  # kind="check": the symbol that IS this check's margin
    unit: str = ""  # display unit of `defines`
    requires: tuple[str, ...] = ()  # symbols it reads — the resolver orders by this
    applies: tuple[str, ...] = ()  # declarative applicability predicates
    notes: str = ""  # scope caveats, rendered as fine print

    def __post_init__(self) -> None:
        for name, value in (("id", self.id), ("citation", self.citation), ("title", self.title)):
            if not value.strip():
                raise DesignCheckError(
                    f"clause {self.id or '<unnamed>'!r}: {name} must be non-empty"
                )
        if self.kind not in CLAUSE_KINDS:
            raise DesignCheckError(
                f"clause {self.id!r}: kind {self.kind!r} is not one of {', '.join(CLAUSE_KINDS)}"
            )
        if self.kind == "formula":
            if not self.formula.strip() or not self.defines.strip():
                raise DesignCheckError(
                    f"clause {self.id!r}: a formula clause needs both 'formula' and 'defines'"
                )
            if not self.defines.isidentifier():
                raise DesignCheckError(
                    f"clause {self.id!r}: defines {self.defines!r} is not a valid symbol name"
                )
            if self.check or self.utilisation:
                raise DesignCheckError(
                    f"clause {self.id!r}: a formula clause must not carry 'check' or "
                    f"'utilisation' — split it into two clauses"
                )
        else:
            if not self.check.strip():
                raise DesignCheckError(f"clause {self.id!r}: a check clause needs 'check'")
            if self.formula or self.defines:
                raise DesignCheckError(
                    f"clause {self.id!r}: a check clause must not carry 'formula' or 'defines'"
                )
            if self.utilisation and not self.utilisation.isidentifier():
                raise DesignCheckError(
                    f"clause {self.id!r}: utilisation {self.utilisation!r} is not a valid "
                    f"symbol name"
                )
        for symbol in self.requires:
            if not symbol.isidentifier():
                raise DesignCheckError(
                    f"clause {self.id!r}: requires {symbol!r} is not a valid symbol name"
                )

    @property
    def expression(self) -> str:
        """The one expression this clause contributes to the sheet."""
        return self.formula if self.kind == "formula" else self.check

    @property
    def description(self) -> str:
        """Check-row prose: the citation and what it is for."""
        return f"{self.citation} — {self.title}"


@dataclass(frozen=True)
class SymbolSpec:
    """Where a leaf symbol's value comes from, and in what unit it must arrive.

    ``bind`` is drawn from a closed vocabulary the resolver implements (see
    ``resolve.BINDERS``) — KB files stay reviewable data and never execute.
    """

    symbol: str
    bind: str
    unit: str = ""
    citation: str = ""

    def __post_init__(self) -> None:
        if not self.symbol.isidentifier():
            raise DesignCheckError(f"symbol {self.symbol!r} is not a valid symbol name")
        if not self.bind.strip():
            raise DesignCheckError(f"symbol {self.symbol!r}: 'bind' must name a binding source")


@dataclass(frozen=True)
class BuildingCode:
    """A code *edition* as one immutable value.

    Identity is the edition string: "EC5:2004+A2:2014" is a different object
    from "EC5:2023" and both may sit in the KB at once. Corrections are a new
    KB version, never an in-place edit.
    """

    ref: KbRef
    name: str
    edition: str
    gamma_M: Mapping[str, float]
    k_mod: Mapping[tuple[int, str], float]
    clauses: tuple[Clause, ...] = ()
    symbols: Mapping[str, SymbolSpec] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in (("name", self.name), ("edition", self.edition)):
            if not value.strip():
                raise DesignCheckError(
                    f"BuildingCode {self.ref.address!r}: {name} must be non-empty"
                )
        if not self.gamma_M:
            raise DesignCheckError(
                f"BuildingCode {self.ref.address!r}: gamma_M must declare at least one domain"
            )
        seen: set[str] = set()
        for clause in self.clauses:
            if clause.id in seen:
                raise DesignCheckError(
                    f"BuildingCode {self.ref.address!r}: duplicate clause id {clause.id!r}"
                )
            seen.add(clause.id)

    @property
    def pin(self) -> str:
        """The footer form: ``"codes/ec5 @2004-A2-2014"``."""
        return f"{self.ref.address} @{self.edition}"

    def modification_factor(self, service_class: int, load_duration: str) -> float:
        """``k_mod`` for one (service class, duration) cell, or a named refusal."""
        try:
            return self.k_mod[(service_class, load_duration)]
        except KeyError:
            available = ", ".join(
                f"SC{sc}/{duration}" for sc, duration in sorted(self.k_mod, key=str)
            )
            raise DesignCheckError(
                f"code {self.ref.address!r} has no k_mod for service class "
                f"{service_class} and load duration {load_duration!r}; "
                f"available cells: {available or '(none)'}"
            ) from None

    def partial_factor(self, domain: str) -> float:
        """``gamma_M`` for one domain ("connections"), or a named refusal."""
        try:
            return self.gamma_M[domain]
        except KeyError:
            raise DesignCheckError(
                f"code {self.ref.address!r} has no gamma_M for domain {domain!r}; "
                f"available domains: {', '.join(sorted(self.gamma_M))}"
            ) from None
