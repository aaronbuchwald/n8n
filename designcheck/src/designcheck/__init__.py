"""designcheck — building-code clauses, compiled into a calculation.

A knowledge base of materials, fastener products and code clauses; a resolver
that decides which clauses govern *this* connection and binds their symbols to
*these* materials, products, factors and actions; and one output — a plain
:class:`calcsheet.Calc`. Evaluation, the ``Result`` type, utilisation and every
renderer come from ``calcsheet`` unchanged, so the proof cannot disagree with
the numbers: it *is* the generic pipeline.

    from designcheck import (
        DesignConfig, ScrewConnection, StructuralMember, RectSection,
        load_kb, get_code, get_material, get_fastener,
        read_fem_actions, governing_action, resolve,
    )

    kb      = load_kb()
    code    = get_code(kb, "codes/ec5")
    timber  = get_material(kb, "materials/timber/C24")
    screw   = get_fastener(kb, "fasteners/screw/csk-6.0x120")
    ...
    checks  = resolve(code, connection, demand, config)
    result  = checks.calc.evaluate()      # calcsheet from here down

Importing this package has no side effects and touches no clock or network.
The knowledge base is read from disk only when :func:`load_kb` is called.
``designcheck`` depends on ``calcsheet``; nothing depends on ``designcheck``.
"""

from __future__ import annotations

from .applicability import applies, evaluate_predicate, facts
from .code import CLAUSE_KINDS, BuildingCode, Clause, SymbolSpec
from .config import LOAD_DURATIONS, UNITS_POLICIES, DesignConfig
from .connections import ScrewConnection
from .demand import (
    COMPONENT_UNITS,
    ActionRow,
    Demand,
    governing_action,
    parse_fem_actions,
    read_fem_actions,
)
from .errors import DesignCheckError
from .kb import (
    BUILTIN_KB,
    KbRoot,
    KnowledgeBase,
    entries,
    get_code,
    get_fastener,
    get_material,
    load_kb,
)
from .materials import (
    MATERIAL_FAMILIES,
    Concrete,
    FastenerSteel,
    KbRef,
    Material,
    Steel,
    Timber,
)
from .members import MEMBER_ROLES, RectSection, Screw, StructuralMember
from .resolve import BINDERS, Binding, CheckSet, footer_text, resolve
from .units import Unit, convert, parse_unit, split_unit

__all__ = [
    "BINDERS",
    "BUILTIN_KB",
    "CLAUSE_KINDS",
    "COMPONENT_UNITS",
    "LOAD_DURATIONS",
    "MATERIAL_FAMILIES",
    "MEMBER_ROLES",
    "UNITS_POLICIES",
    "ActionRow",
    "Binding",
    "BuildingCode",
    "CheckSet",
    "Clause",
    "Concrete",
    "Demand",
    "DesignCheckError",
    "DesignConfig",
    "FastenerSteel",
    "KbRef",
    "KbRoot",
    "KnowledgeBase",
    "Material",
    "RectSection",
    "Screw",
    "ScrewConnection",
    "Steel",
    "StructuralMember",
    "SymbolSpec",
    "Timber",
    "Unit",
    "applies",
    "convert",
    "entries",
    "evaluate_predicate",
    "facts",
    "footer_text",
    "get_code",
    "get_fastener",
    "get_material",
    "governing_action",
    "load_kb",
    "parse_fem_actions",
    "parse_unit",
    "read_fem_actions",
    "resolve",
    "split_unit",
]
