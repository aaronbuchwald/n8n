"""T7 — ``CheckSet``: *this* code applied to *this* connection under *this* config.

The load-bearing move of the whole design is that the domain layer's output is
a plain :class:`calcsheet.Calc`. Evaluation, ``Result``, utilisation reporting
and every renderer are inherited rather than duplicated, and the proof can
never disagree with the numbers because it *is* the generic one-evaluation
pipeline.

:func:`resolve` is pure:

1. filter the code's clauses by applicability against the connection's facts;
2. order the survivors by ``requires`` (topological, cycles named);
3. bind every leaf symbol to its source, recording each binding;
4. emit the ``Calc`` — bound leaves become ``Input`` rows whose ``ref`` is the
   KB address or the FEM provenance, formula clauses become ``Formula`` rows
   reffed by citation, check clauses plus the config's target become ``Check``
   rows.

Every row the resolver emits carries a ``ref``. A row with an empty gutter can
only come from a hand-authored calc, where it remains the author's business.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from calcsheet import Calc, Check, Formula, Input

from .applicability import applies, facts
from .code import BuildingCode, Clause, SymbolSpec
from .config import DesignConfig
from .connections import ScrewConnection
from .demand import Demand
from .errors import DesignCheckError
from .materials import KbRef, Material
from .units import convert

#: How EC5's duration names read in a table citation.
_DURATION_NAMES = {
    "permanent": "permanent",
    "long": "long-term",
    "medium": "medium-term",
    "short": "short-term",
    "instantaneous": "instantaneous",
}

#: Where a value physically sits, and therefore the unit it is already in.
#: The dimension check at binding compares this against the symbol's declared
#: unit, so a code that asks for `d` in metres still gets the right number.
_STORED_UNITS: Mapping[str, str] = {
    "material.rho_k": "kg/m^3",
    "material.f_mk": "MPa",
    "material.f_c0k": "MPa",
    "material.E_mean": "MPa",
    "material.f_yk": "MPa",
    "material.f_uk": "MPa",
    "material.E": "MPa",
    "material.f_ck": "MPa",
    "material.E_cm": "MPa",
    "fastener.d": "mm",
    "fastener.L": "mm",
    "fastener.steel.f_uk": "MPa",
    "connection.n": "",
    "connection.shear_planes": "",
    "connection.spacing": "mm",
    "connection.angle_to_grain": "deg",
    "code.k_mod": "",
    "config.target_utilisation": "",
}

_GAMMA_PREFIX = "code.gamma_M."

#: The closed binding vocabulary a KB `[symbols]` table may name.
BINDERS: tuple[str, ...] = (*sorted(_STORED_UNITS), "demand.value", f"{_GAMMA_PREFIX}<domain>")


@dataclass(frozen=True)
class Binding:
    """Where one symbol's value came from — the machine-readable ledger.

    What the report shows as gutter text, tooling reads here as data.
    ``value`` is ``None`` for a symbol a clause computes: at resolve time the
    calc has not run, and inventing a number would be the one thing this
    package must never do.
    """

    symbol: str
    origin: str  # "material" | "product" | "connection" | "code" | "demand" | "config" | "clause"
    ref: str
    unit: str = ""
    value: float | None = None
    clause: str = ""

    def __post_init__(self) -> None:
        if not self.ref.strip():
            raise DesignCheckError(
                f"binding for {self.symbol!r} has no ref; the resolver cannot emit a row "
                f"with an empty gutter"
            )


@dataclass(frozen=True)
class CheckSet:
    """The resolution product: what was applied, to what, and the compiled sheet."""

    subject: str
    code: KbRef
    clauses: tuple[Clause, ...]
    bindings: Mapping[str, Binding]
    calc: Calc
    notes: tuple[str, ...] = ()
    pins: tuple[str, ...] = ()

    def evaluate(self):  # -> calcsheet.Result
        """Run the compiled calc once. Sugar over ``check_set.calc.evaluate()``."""
        return self.calc.evaluate()


# -- the clauses the resolver itself contributes ------------------------------
#
# Not code content: distributing the demand over the fastener group, forming
# the utilisation and applying the project's own target are the resolver's job.
# They are Clause values so they pass through exactly the same ordering,
# binding and citation path as anything loaded from the KB.

DEMAND_DISTRIBUTION = Clause(
    id="designcheck-demand",
    citation="demand · shared by the fastener group",
    title="Design shear per fastener",
    kind="formula",
    defines="F_vEd",
    formula="1000 * V_Ed / n",
    unit="N",
    requires=("V_Ed", "n"),
    applies=("connection.kind == 'screw'",),
    notes=(
        "V_Ed is in kN and the resistance in N; the factor 1000 is that conversion, "
        "kept as a visible row rather than hidden inside a binding. The group acts "
        "equally — no effective-number-of-fasteners reduction is applied."
    ),
)

UTILISATION = Clause(
    id="designcheck-eta",
    citation="utilisation",
    title="Design action over design resistance",
    kind="formula",
    defines="eta",
    formula="F_vEd / F_vRd",
    requires=("F_vEd", "F_vRd"),
)


def _target_clause(config: DesignConfig) -> Clause:
    """The owner's "within a desired safety factor", as one more check row."""
    return Clause(
        id="designcheck-target",
        citation=f"design config · SF {config.safety_factor:.3g}",
        title="project target safety factor",
        kind="check",
        check="eta <= eta_max",
        utilisation="eta",
        requires=("eta", "eta_max"),
    )


def resolve(
    code: BuildingCode,
    connection: ScrewConnection,
    demand: Demand,
    config: DesignConfig,
    *,
    subject: str = "",
) -> CheckSet:
    """Compile the applicable clauses into a ready-to-evaluate ``Calc``."""
    _agree(code, connection, demand, config)

    known = facts(connection, config)
    candidates = [
        *code.clauses,
        DEMAND_DISTRIBUTION,
        UTILISATION,
        _target_clause(config),
    ]
    applicable = tuple(
        clause
        for clause in candidates
        if applies(clause.applies, known, what=f"clause {clause.id!r}")
    )
    ordered = _order(applicable)

    bindings: dict[str, Binding] = {}
    for symbol in _leaves(ordered, code):
        bindings[symbol] = _bind(
            code.symbols[symbol], code, connection, demand, config
        )
    for clause in ordered:
        if clause.kind == "formula":
            bindings[clause.defines] = Binding(
                symbol=clause.defines,
                origin="clause",
                ref=clause.citation,
                unit=clause.unit,
                clause=clause.id,
            )

    resolved_subject = subject or f"Screw connection {connection.name} — {demand.component}"
    return CheckSet(
        subject=resolved_subject,
        code=code.ref,
        clauses=ordered,
        bindings=bindings,
        calc=_calc(resolved_subject, code, ordered, bindings, config),
        notes=tuple(clause.notes for clause in ordered if clause.notes),
        pins=_pins(code, connection, config),
    )


def footer_text(check_set: CheckSet) -> str:
    """The run's pins and the clause fine print, ready for ``HtmlOptions.footer``."""
    return " · ".join(check_set.pins) + (
        (" — " + " ".join(check_set.notes)) if check_set.notes else ""
    )


# -- consistency --------------------------------------------------------------


def _agree(
    code: BuildingCode,
    connection: ScrewConnection,
    demand: Demand,
    config: DesignConfig,
) -> None:
    """Refuse the three mismatches that would produce a plausible wrong answer."""
    if config.code_address != code.ref.address:
        raise DesignCheckError(
            f"config pins code {config.code_address!r} but the resolved code is "
            f"{code.ref.address!r}"
        )
    if config.code_edition and config.code_edition != code.edition:
        raise DesignCheckError(
            f"config pins edition {config.code_edition!r} of {code.ref.address!r} but the "
            f"KB holds edition {code.edition!r}"
        )
    if demand.element != connection.name:
        raise DesignCheckError(
            f"demand is for element {demand.element!r} but the connection is "
            f"{connection.name!r}; checking one connection with another's actions is "
            f"never intended"
        )


# -- ordering -----------------------------------------------------------------


def _order(clauses: Sequence[Clause]) -> tuple[Clause, ...]:
    """Depth-first topological order: dependencies first, declaration order otherwise.

    Depth-first (rather than a ready-queue) keeps a clause next to the clause
    that needs it, which is how an engineer reads a proof top to bottom.
    """
    producer: dict[str, Clause] = {}
    for clause in clauses:
        if clause.kind != "formula":
            continue
        if clause.defines in producer:
            raise DesignCheckError(
                f"clauses {producer[clause.defines].id!r} and {clause.id!r} both define "
                f"{clause.defines!r}; a symbol may be defined once"
            )
        producer[clause.defines] = clause

    ordered: list[Clause] = []
    state: dict[str, str] = {}

    def visit(clause: Clause, trail: tuple[str, ...]) -> None:
        seen = state.get(clause.id)
        if seen == "done":
            return
        if seen == "visiting":
            cycle = " -> ".join((*trail[trail.index(clause.id):], clause.id))
            raise DesignCheckError(f"clauses form a cycle: {cycle}")
        state[clause.id] = "visiting"
        for symbol in clause.requires:
            upstream = producer.get(symbol)
            if upstream is not None:
                visit(upstream, (*trail, clause.id))
        state[clause.id] = "done"
        ordered.append(clause)

    for clause in clauses:
        visit(clause, ())
    return tuple(ordered)


def _leaves(ordered: Sequence[Clause], code: BuildingCode) -> tuple[str, ...]:
    """Required symbols no clause defines, in the code's own declaration order.

    The KB's ``[symbols]`` order is the GIVEN order of the proof — a curated
    reading order beats whichever clause happened to mention a symbol first.
    """
    defined = {clause.defines for clause in ordered if clause.kind == "formula"}
    first_use: dict[str, str] = {}
    for clause in ordered:
        for symbol in clause.requires:
            first_use.setdefault(symbol, clause.id)
    needed = {symbol for symbol in first_use if symbol not in defined}

    unbound = sorted(needed - set(code.symbols))
    if unbound:
        detail = ", ".join(
            f"{symbol!r} (required by clause {first_use[symbol]!r})" for symbol in unbound
        )
        raise DesignCheckError(
            f"unsatisfiable symbol(s): {detail}; no applicable clause defines them and "
            f"code {code.ref.address!r} declares no binding for them"
        )
    return tuple(symbol for symbol in code.symbols if symbol in needed)


# -- binding ------------------------------------------------------------------


def _bind(
    spec: SymbolSpec,
    code: BuildingCode,
    connection: ScrewConnection,
    demand: Demand,
    config: DesignConfig,
) -> Binding:
    """One leaf symbol -> its value, unit, provenance and origin."""
    what = f"symbol {spec.symbol!r} (bind {spec.bind!r})"
    value, source_unit, ref, origin = _fetch(spec, code, connection, demand, config, what)
    return Binding(
        symbol=spec.symbol,
        origin=origin,
        ref=ref,
        unit=spec.unit,
        value=convert(value, source_unit, spec.unit, what=what),
    )


def _fetch(
    spec: SymbolSpec,
    code: BuildingCode,
    connection: ScrewConnection,
    demand: Demand,
    config: DesignConfig,
    what: str,
) -> tuple[float, str, str, str]:
    bind = spec.bind

    if bind.startswith(_GAMMA_PREFIX):
        domain = bind[len(_GAMMA_PREFIX) :]
        citation = spec.citation or f"{code.name} · partial factors"
        return code.partial_factor(domain), "", f"{citation} · {domain}", "code"

    if bind == "demand.value":
        return demand.value, demand.unit, demand.ref, "demand"

    if bind not in _STORED_UNITS:
        raise DesignCheckError(
            f"{what}: unknown binding source; the closed vocabulary is "
            f"{', '.join(BINDERS)}"
        )
    stored = _STORED_UNITS[bind]

    if bind == "code.k_mod":
        citation = spec.citation or f"{code.name} · modification factors"
        duration = _DURATION_NAMES.get(config.load_duration, config.load_duration)
        return (
            code.modification_factor(config.service_class, config.load_duration),
            stored,
            f"{citation} · SC{config.service_class}, {duration}",
            "code",
        )

    if bind.startswith("config."):
        return (
            _attribute(config, bind[len("config.") :], what),
            stored,
            f"design config · SF {config.safety_factor:.3g}",
            "config",
        )

    if bind.startswith("connection."):
        return (
            _attribute(connection, bind[len("connection.") :], what),
            stored,
            f"connection {connection.name}",
            "connection",
        )

    if bind == "fastener.steel.f_uk":
        screw = connection.fastener
        return screw.steel.f_uk, stored, f"kb: {screw.steel.ref.pin}", "product"

    if bind.startswith("fastener."):
        screw = connection.fastener
        return (
            _attribute(screw, bind[len("fastener.") :], what),
            stored,
            f"kb: {screw.ref.pin}",
            "product",
        )

    material = _shared_material(connection, what)
    return (
        _attribute(material, bind[len("material.") :], what),
        stored,
        f"kb: {material.ref.pin}",
        "material",
    )


def _attribute(owner: object, name: str, what: str) -> float:
    value = getattr(owner, name, None)
    if value is None:
        raise DesignCheckError(
            f"{what}: {type(owner).__name__} has no property {name!r}"
        )
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DesignCheckError(
            f"{what}: {type(owner).__name__}.{name} is {value!r}, not a number"
        )
    return float(value)


def _shared_material(connection: ScrewConnection, what: str) -> Material:
    """The connection's one material.

    v1 binds ``material.*`` only when every joined member agrees. A mixed
    connection (timber to steel, or two timber grades) needs clauses that say
    *which* member each property comes from, and that is a per-clause decision
    this subset does not make.
    """
    distinct = {member.material for member in connection.members}
    if len(distinct) != 1:
        grades = ", ".join(
            sorted(f"{member.name}: {member.material.ref.address}" for member in connection.members)
        )
        raise DesignCheckError(
            f"{what}: connection {connection.name!r} joins members of different materials "
            f"({grades}); v1 binds material properties only when they agree"
        )
    return distinct.pop()


# -- emission -----------------------------------------------------------------


def _calc(
    subject: str,
    code: BuildingCode,
    ordered: Sequence[Clause],
    bindings: Mapping[str, Binding],
    config: DesignConfig,
) -> Calc:
    inputs = {
        symbol: Input(value=binding.value, ref=binding.ref, unit=binding.unit)
        for symbol, binding in bindings.items()
        if binding.origin != "clause" and binding.value is not None
    }
    return Calc(
        title=f"{subject} · {code.name}",
        as_of=config.as_of,
        inputs=inputs,
        formulas=tuple(
            Formula(
                symbol=clause.defines,
                expr=clause.formula,
                ref=clause.citation,
                unit=clause.unit,
            )
            for clause in ordered
            if clause.kind == "formula"
        ),
        checks=tuple(
            Check(
                expr=clause.check,
                description=clause.description,
                utilisation=clause.utilisation,
            )
            for clause in ordered
            if clause.kind == "check"
        ),
    )


def _pins(
    code: BuildingCode, connection: ScrewConnection, config: DesignConfig
) -> tuple[str, ...]:
    """Snapshot version(s), the code edition and ``as_of`` — the run, reproducible."""
    refs: list[KbRef] = [code.ref, connection.fastener.ref]
    refs.extend(member.material.ref for member in connection.members)
    versions = sorted({ref.version for ref in refs})
    return (*(f"kb {version}" for version in versions), code.pin, f"as_of {config.as_of}")
