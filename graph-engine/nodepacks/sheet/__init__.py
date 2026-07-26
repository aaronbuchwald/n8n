"""``sheet`` — the calcsheet node pack: a whole calculation, welded or split.

A calculation is declared as data (inputs, formulas, checks), evaluated
**once** through :mod:`calcsheet`, and rendered as a self-contained "C4
four-slot" HTML card with a binary pass/fail verdict. Nothing downstream
re-derives anything — rows, values and verdicts are all pure functions of the
one ``Result``.

Three nodes, two ways to say the same thing (ADR 0021):

* :func:`calc_card` — the one-node convenience form: evaluate **and** render.
* :func:`calc` + :func:`render_html` — the split pair. ``calc`` puts the
  ``Result`` itself on a socket, so a graph can hang a second rendering off the
  same wire (or swap the rendering) without evaluating twice.

Both paths run the *same* two free functions (:func:`_evaluate`,
:func:`_render`), so the split can never drift from the welded form: for equal
inputs the HTML is byte-identical.

**Why the pack is called ``sheet``, not ``calcsheet``.** ``nodepacks/`` is
importable as top-level packages, so a pack directory named ``calcsheet``
would shadow the real library. The pack is ``sheet``; node ids are
``sheet.calc_card`` / ``sheet.calc`` / ``sheet.render_html``.

**Lazy import, by contract.** ``calcsheet`` (and its ``sympy`` /
``latex2mathml`` deps) is imported *inside* the node body, never at module top
level — importing this module and listing its spec works with none of them
installed, exactly like ``nodepacks/sym``. Only *running* the node needs them
(``uv sync --extra sym``).

The formulas/checks mini-syntax and the derived input sockets are documented on
:func:`parse_formulas`, :func:`parse_checks` and :func:`formula_free_symbols`.
"""

from __future__ import annotations

import ast
import builtins
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from engine import DerivedInputs, Renderer, UserError, Widget, node

if TYPE_CHECKING:  # names for annotations only — never imported at run time
    from calcsheet import Result

# -- the mini-syntax ---------------------------------------------------------
#
# One entry per line. For a formula:
#
#     symbol = expression [unit]  # reference
#
# for a check:
#
#     expression [utilisation]  # description
#
# `# text` is the reference (formula) or description (check); a trailing `[...]`
# is the formula's display unit or the check's utilisation symbol. Blank lines
# and whole-line comments are skipped; anything else that does not fit raises a
# UserError naming the line.

# A trailing `[...]` on an entry's expression — one bracket, two meanings by
# entry kind: a formula's display unit, a check's utilisation symbol.
_UNIT = re.compile(r"\[([^\[\]]*)\]\s*$")

# Cap on the authored text so deriving (which runs per keystroke through the
# derive endpoint) stays cheap. Mirrors sym.handcalc's own cap.
_MAX_TEXT_LEN = 10_000

# Significant digits used when `precision` is left unset (a cleared number
# widget commits `null`, which means "not set" — never a crash).
DEFAULT_PRECISION = 3

# Static parameters of the evaluating nodes (`calc_card`, `calc`) a derived
# symbol may not shadow. Both share one signature, so one set covers both.
_STATIC_PARAMS = frozenset({"title", "as_of", "formulas", "checks", "precision"})

# Math names sympy resolves on its own, so they must NOT become sockets — they
# are only left unbound (calcsheet binds *declared* names as plain symbols, so
# an undeclared `sqrt`/`pi` keeps its sympy meaning). Mirrors sym.handcalc's
# whitelist; additive — a name outside it simply becomes a socket, which is
# visible on the canvas.
_MATH_NAMES = frozenset({"sqrt", "sin", "cos", "tan", "log", "exp", "pi"})

# calcsheet's own expression vocabulary — functions it binds when parsing, which
# are therefore calls, not quantities. Spelled out rather than imported from
# `calcsheet.EXPRESSION_FUNCTIONS` because deriving sockets must work with the
# `sym` extra uninstalled (the pack's lazy-import contract); the derive endpoint
# runs per keystroke and may not import sympy.
_CALC_VOCABULARY = frozenset({"MinDefined"})

# Names never turned into sockets: Python builtins + the names above.
_NON_SOCKET_NAMES = frozenset(dir(builtins)) | _MATH_NAMES | _CALC_VOCABULARY


@dataclass(frozen=True)
class FormulaLine:
    """One parsed formula entry: ``symbol = expr`` plus its unit and reference."""

    lineno: int
    symbol: str
    expr: str
    unit: str
    ref: str


@dataclass(frozen=True)
class CheckLine:
    """One parsed check entry: a boolean ``expr``, its description and utilisation.

    ``utilisation`` is the symbol whose value *is* this check's utilisation (the
    governing-chip number); empty when the line does not name one.
    """

    lineno: int
    expr: str
    description: str
    utilisation: str = ""


def _entries(text: str, *, what: str) -> list[tuple[int, str, str]]:
    """Split ``text`` into ``(lineno, body, comment)`` triples, defensively.

    Blank lines and whole-line ``#`` comments (leading whitespace allowed) are
    skipped. The comment is everything after the first ``#``; the body is what
    precedes it.
    """
    if not isinstance(text, str):
        raise UserError(f"{what} must be a string, got {type(text).__name__}")
    if len(text) > _MAX_TEXT_LEN:
        raise UserError(f"{what} is too long ({len(text)} chars; limit {_MAX_TEXT_LEN})")

    out: list[tuple[int, str, str]] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        body, _, comment = line.partition("#")
        out.append((lineno, body.strip(), comment.strip()))
    return out


def _check_expression(expr: str, *, what: str, lineno: int) -> None:
    """Reject an expression that is not parseable Python (so not sympifiable)."""
    try:
        ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise UserError(
            f"{what} line {lineno}: cannot parse expression {expr!r} ({exc.msg})"
        ) from None


def parse_formulas(text: str) -> list[FormulaLine]:
    """Parse the ``formulas`` mini-syntax into ordered :class:`FormulaLine` entries.

    One formula per line::

        r = F_max / C_min  # demand / capacity
        U = 100 * r [%]    # utilisation

    The ``# text`` is the row's **reference** (the card's right-hand gutter); a
    trailing ``[unit]`` on the expression is the row's **unit** (a display
    string — calcsheet does no unit algebra). Symbols are defined in
    declaration order, so a formula may only reference symbols declared before
    it — which is also what makes the earlier ones inputs (see
    :func:`formula_free_symbols`).
    """
    formulas: list[FormulaLine] = []
    seen: set[str] = set()
    for lineno, body, ref in _entries(text, what="formulas"):
        symbol, sep, expr = body.partition("=")
        if not sep:
            raise UserError(
                f"formulas line {lineno}: {body!r} has no '=' — each formula is "
                f"'<symbol> = <expression>' (optionally '[unit]' then '# reference')"
            )
        symbol = symbol.strip()
        if not symbol.isidentifier():
            raise UserError(
                f"formulas line {lineno}: {symbol!r} is not a valid symbol name"
            )
        if symbol in seen:
            raise UserError(
                f"formulas line {lineno}: symbol {symbol!r} is defined twice; "
                f"each symbol may be defined once"
            )

        expr = expr.strip()
        unit_match = _UNIT.search(expr)
        unit = ""
        if unit_match is not None:
            unit = unit_match.group(1).strip()
            expr = expr[: unit_match.start()].strip()
        if not expr:
            raise UserError(
                f"formulas line {lineno}: {symbol!r} has no right-hand side expression"
            )
        _check_expression(expr, what="formulas", lineno=lineno)

        seen.add(symbol)
        formulas.append(FormulaLine(lineno, symbol, expr, unit, ref))
    return formulas


def parse_checks(text: str) -> list[CheckLine]:
    """Parse the ``checks`` mini-syntax into ordered :class:`CheckLine` entries.

    One check per line, the ``# text`` being its **description**::

        U < 100  # capacity not exceeded
        U < 50   # utilisation target

    A trailing ``[symbol]`` names the check's **utilisation** — the symbol whose
    value is the number the governing chip reports::

        eta < 100 [eta]  # reinforcement not required

    Same bracket the formulas use for a unit, in the same trailing position: an
    entry's ``[…]`` annotates the entry. It is optional, and a check without one
    behaves exactly as before (a plain PASS/FAIL, no chip) — the verdict is
    authoritative either way, and the utilisation only augments it.

    A check must be a relational/boolean expression over the final scope;
    calcsheet rejects a bare quantity ("a number is not a verdict"). Note a
    failing check does NOT fail the run — it renders FAIL on the card.
    """
    checks: list[CheckLine] = []
    for lineno, body, description in _entries(text, what="checks"):
        utilisation_match = _UNIT.search(body)
        utilisation = ""
        if utilisation_match is not None:
            utilisation = utilisation_match.group(1).strip()
            body = body[: utilisation_match.start()].strip()
            if not utilisation.isidentifier():
                raise UserError(
                    f"checks line {lineno}: {utilisation!r} is not a valid symbol "
                    f"name; a check's '[...]' names the symbol whose value is its "
                    f"utilisation"
                )
        if not body:
            raise UserError(f"checks line {lineno}: no expression before the '[...]'")
        if "=" in body.replace("==", "").replace("!=", "").replace("<=", "").replace(">=", ""):
            raise UserError(
                f"checks line {lineno}: {body!r} looks like an assignment; a check is "
                f"a comparison such as 'U < 100' (use '==' to test equality)"
            )
        _check_expression(body, what="checks", lineno=lineno)
        checks.append(CheckLine(lineno, body, description, utilisation))
    return checks


# -- derived input sockets (ADR 0007) ----------------------------------------


def _derived_socket(name: str) -> dict:
    """One derived input-spec entry for a free symbol (ADR 0007 frozen shape).

    The declared ``type``/``widget`` describe what the socket *means* — a
    quantity, editable as a number when nothing is wired to it. A wire may also
    deliver that quantity as a value-with-provenance record (see :func:`_given`);
    that is a richer transport of the same number, not a different socket kind,
    so the declaration stays as it is.
    """
    return {
        "name": name,
        "type": "float",
        "kind": "keywordOnly",
        "required": True,
        "default": None,
        "widget": {"kind": "number", "subtype": "float"},
        "derived": True,
    }


def formula_free_symbols(formulas: str) -> list[dict]:
    """Free symbols of ``formulas``, in first-appearance order, as input entries.

    The deriver for :func:`calc_card` **and** :func:`calc` (ADR 0007 D3) — the
    same contract ``sym.handcalc`` uses, so ``F_max``/``C_min`` render as real
    wired sockets on the canvas; the seam moves with the deriving param, so the
    split pair keeps it. A name *read* before any formula defines it is an input; a
    name a previous formula assigned is a computed result, not a socket.
    Builtins are excluded, and a symbol colliding with a static parameter
    raises rather than shadowing it.

    Pure and cheap: expressions are parsed, never evaluated.
    """
    order: list[str] = []
    seen: set[str] = set()
    defined: set[str] = set()

    for formula in parse_formulas(formulas):
        tree = ast.parse(formula.expr, mode="eval")
        loads = [
            n for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
        ]
        loads.sort(key=lambda n: (n.lineno, n.col_offset))
        for name_node in loads:
            name = name_node.id
            if name in defined or name in _NON_SOCKET_NAMES:
                continue
            if name in _STATIC_PARAMS:
                raise UserError(
                    f"rename the symbol {name!r}: it collides with the reserved "
                    f"parameter {name!r} of the calc node"
                )
            if name not in seen:
                seen.add(name)
                order.append(name)
        defined.add(formula.symbol)

    return [_derived_socket(name) for name in order]


# -- card height -------------------------------------------------------------
#
# A `sandbox=""` iframe runs no scripts, so the card cannot measure and report
# its own height. The declared height is what the frontend `html-card` renderer
# sizes its frame to; it was measured in a browser against calcsheet's
# stylesheet (render.py) and is deliberately rounded UP — a card a few px too
# tall shows a sliver of whitespace, one too short scrolls.
DEFAULT_CARD_HEIGHT = 320

# The grouped card's declared height. It is *inherently* a compromise, and
# unlike `DEFAULT_CARD_HEIGHT` it cannot be measured once and be right: a group
# card grows two input rows, two calculation rows and one check per group, and
# the group count is a property of the data. A scriptless iframe cannot report
# its own height, so the frame scrolls when the content is taller — which is the
# survivable failure. This is sized for the two-or-three-group case that
# motivated the node; a longer division scrolls.
GROUP_CARD_HEIGHT = 560


# -- the shared pipeline -----------------------------------------------------
#
# ONE evaluation path and ONE rendering path, called by both the welded
# `calc_card` and the split `calc` + `render_html` pair (ADR 0021 D2). Keeping
# them here is what makes "the split renders exactly what the single node
# renders" true by construction rather than by test.


def _text_field(record: Mapping, field: str, *, name: str) -> str:
    """One optional display string off a value-with-provenance record."""
    text = record.get(field, "")
    if text is None:
        return ""
    if not isinstance(text, str):
        raise UserError(
            f"input {name!r}: {field!r} must be a string, got {text!r} "
            f"({type(text).__name__})"
        )
    return text


def _given(name: str, value: object):
    """One given quantity, from a bare number or a value-with-provenance record.

    Two spellings, one meaning. A socket fed a bare number behaves exactly as it
    always has. A socket fed a **record** — any mapping with a ``value`` key,
    optionally ``unit`` and ``ref`` — takes the number from ``value`` and the
    row's display unit and reference from the other two. That is the general
    "a value knows where it came from" convention: a source that has provenance
    to offer keeps it attached to the number instead of dropping it on the floor
    (``sources.pick`` hands such a record straight through) — and unrelated keys
    are ignored, so a richer source is not a breaking change.

    Reading the record HERE, at the calc node, is deliberate: the calc is what
    owns the notion of a given with a unit and a reference (calcsheet's
    ``Input``), so nothing upstream has to know what a card wants. ``pick`` just
    picks.

    ``None`` — bare, or as a record's ``value`` — is an EMPTY given, not a bad
    one: the source said "this quantity does not apply to this case" (a JSON
    null). calcsheet renders it as `–`, keeps its unit and reference, and drops
    it out of any ``MinDefined(...)`` naming it. Coercing or rejecting it here
    would erase that statement.
    """
    from calcsheet import Input

    unit = ref = ""
    if isinstance(value, Mapping):
        if "value" not in value:
            raise UserError(
                f"input {name!r} is an object without a 'value' key; a given is "
                f"a number, or a record carrying one as "
                f"{{'value': …, 'unit': …, 'ref': …}} (got keys: "
                f"{', '.join(repr(k) for k in value) or '(none)'})"
            )
        unit = _text_field(value, "unit", name=name)
        ref = _text_field(value, "ref", name=name)
        value = value["value"]

    if value is None:
        return Input(None, ref=ref, unit=unit)
    try:
        return Input(float(value), ref=ref, unit=unit)
    except (TypeError, ValueError):
        raise UserError(
            f"input {name!r} must be a number, got {value!r} "
            f"({type(value).__name__})"
        ) from None


def _evaluate(
    title: str,
    as_of: str,
    formulas: str,
    checks: str,
    precision: int | None,
    values: dict[str, object],
) -> Result:
    """Parse the mini-syntax, build the ``Calc`` and evaluate it once."""
    return _evaluate_parsed(
        title,
        as_of,
        parse_formulas(formulas),
        parse_checks(checks),
        precision,
        values,
    )


def _evaluate_parsed(
    title: str,
    as_of: str,
    parsed_formulas: list[FormulaLine],
    parsed_checks: list[CheckLine],
    precision: int | None,
    values: dict[str, object],
) -> Result:
    """Build the ``Calc`` from already-parsed entries and evaluate it once.

    Split out of :func:`_evaluate` so a node that *derives* its entries — the
    per-group expansion in :func:`group_card` — can hand them over directly
    instead of serialising them back to the mini-syntax for this function to
    re-parse. One evaluation path either way, which is what keeps every card in
    this pack unable to drift from another.
    """
    from calcsheet import Calc, CalcError, Check, Formula, evaluate_calc

    inputs = {name: _given(name, value) for name, value in values.items()}

    calc = Calc(
        title=title,
        as_of=as_of,
        inputs=inputs,
        formulas=[Formula(f.symbol, f.expr, ref=f.ref, unit=f.unit) for f in parsed_formulas],
        checks=[Check(c.expr, c.description, c.utilisation) for c in parsed_checks],
        # An emptied number widget commits `null`, which is the UI's way of
        # saying "not set" — that must mean the default, not a crash.
        precision=DEFAULT_PRECISION if precision is None else precision,
    )
    try:
        return evaluate_calc(calc)
    except CalcError as error:
        # calcsheet's messages already name the offending symbol/expression and
        # list what IS available — surface them as the user's own error.
        raise UserError(str(error)) from None


def _render(
    result: Result, *, header: str = "", footer: str = "", theme: str | None = None
) -> str:
    """Render ``result`` as the self-contained HTML card.

    ``theme=None`` means "whatever calcsheet defaults to" — the default is not
    restated here, so there is no second place for it to drift.
    """
    from calcsheet import CalcError, HtmlOptions, Result
    from calcsheet import render_html as render_html_card

    if not isinstance(result, Result):
        raise UserError(
            f"the 'result' input must be a calcsheet Result (wire it from a "
            f"calc node), got {type(result).__name__}"
        )
    theme_option = {} if theme is None else {"theme": theme}
    try:
        options = HtmlOptions(header=header, footer=footer, **theme_option)
    except CalcError as error:
        # The only rejectable option is an unknown theme, and its message
        # already lists the available ones.
        raise UserError(str(error)) from None
    return render_html_card(result, options)


# -- per-group expansion (the group summary card) -----------------------------
#
# One calculation is authored ONCE, for one group, and instantiated for each of
# the N groups a grouping strategy returned (see `nodepacks/grouping` and
# `docs/grouping-strategies.md`). The expansion below is the whole mechanism:
# it decides which of the author's formulas actually vary with the group, copies
# only those, and leaves everything the groups share computed exactly once.

# The key that marks a wire value as a *population of groups* rather than one
# given. `grouping.group` is what puts it there.
GROUPS_KEY = "groups"

# The symbol prefix of the per-group "how many member ends fell in this group"
# row, and the unit it displays. The count is a row of the card rather than a
# note beside it because a reviewer checking that the groups partition the
# population has to be able to add the column up.
COUNT_SYMBOL = "n"
COUNT_UNIT = "ends"


def _is_groups_record(value: object) -> bool:
    """Does this socket value carry N groups rather than one quantity?"""
    return isinstance(value, Mapping) and GROUPS_KEY in value


def _varying_socket(values: Mapping[str, object]) -> tuple[str, Mapping]:
    """The one socket fed a groups record — the given that varies per group.

    Discovered from the wire rather than named by a separate parameter, and
    that is deliberate: on the canvas the difference between the single-group
    card and the grouped one is *which node the force wire comes from*, and
    nothing else. Naming the symbol again in a literal would be a second place
    to keep in sync with the formulas.
    """
    found = [(name, value) for name, value in values.items() if _is_groups_record(value)]
    if not found:
        raise UserError(
            "no input carries a group population: wire grouping.group's result "
            "into the given that varies per group (the force, typically), and "
            "leave the givens every group shares as they are"
        )
    if len(found) > 1:
        names = ", ".join(repr(name) for name, _ in found)
        raise UserError(
            f"inputs {names} all carry a group population; exactly one given "
            f"may vary per group — a second varying quantity would mean the "
            f"groups are not one division of one population"
        )
    return found[0]


def _validate_groups(record: Mapping) -> list[Mapping]:
    """Check a groups record's shape and return its groups."""
    groups = record.get(GROUPS_KEY)
    if not isinstance(groups, (list, tuple)) or not groups:
        raise UserError(
            f"the group population's {GROUPS_KEY!r} must be a non-empty list, "
            f"got {groups!r}"
        )
    for index, group in enumerate(groups):
        if not isinstance(group, Mapping):
            raise UserError(
                f"group {index} is {type(group).__name__}, not an object"
            )
        for field in ("key", "label", "count", "governing"):
            if field not in group:
                raise UserError(f"group {index} has no {field!r} key")
        if not isinstance(group["key"], str) or not group["key"].isidentifier():
            raise UserError(
                f"group {index} has key {group['key']!r}, which is not a valid "
                f"symbol suffix; a group's key becomes part of its symbols"
            )
    return list(groups)


def _loaded_names(expr: str) -> set[str]:
    """Every name an expression *reads* (a superset is fine; we only test it)."""
    tree = ast.parse(expr, mode="eval")
    return {
        n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    }


def _rename(expr: str, mapping: Mapping[str, str]) -> str:
    """``expr`` with the named symbols renamed, everything else byte-identical.

    Spliced by the AST's own column offsets rather than regex-replaced or
    round-tripped through ``ast.unparse``: the expression text is what the card
    typesets, so an author's spacing and parentheses must survive a rename that
    only touches identifiers. Entries are single-line by construction (the
    mini-syntax is one per line), so a column offset indexes ``expr`` directly.
    """
    tree = ast.parse(expr, mode="eval")
    edits = sorted(
        (
            (n.col_offset, n.end_col_offset, mapping[n.id])
            for n in ast.walk(tree)
            if isinstance(n, ast.Name)
            and isinstance(n.ctx, ast.Load)
            and n.id in mapping
        ),
        reverse=True,
    )
    for start, end, replacement in edits:
        expr = expr[:start] + replacement + expr[end:]
    return expr


def _expand_for_groups(
    formulas: list[FormulaLine],
    checks: list[CheckLine],
    varying: str,
    groups: list[Mapping],
) -> tuple[list[FormulaLine], list[CheckLine], list[str]]:
    """Instantiate a one-group calculation for N groups.

    A formula is **varying** when it reads the varying given or any symbol a
    varying formula already produced; everything else is **shared** and is
    computed once. That rule is what makes "all groups share one geometry" fall
    out of the arithmetic instead of being asserted: ``l_ef``/``A_ef`` do not
    mention the force, so there is exactly one of each on the card, and only
    ``sigma_c90d``/``eta`` are copied per group.

    Shared formulas keep their authored order and are emitted first, which is
    always sound: a shared formula can only depend on inputs and other shared
    formulas, so hoisting them cannot move a symbol behind its use.

    A check is copied per group on the same rule, with the group's label folded
    into its description; a check that mentions no varying symbol (a geometry
    sanity check, say) stays a single row.

    Returns the expanded formulas, the expanded checks, and the varying symbols
    (so the caller knows which names it must supply per group).
    """
    varying_symbols: set[str] = {varying}
    shared: list[FormulaLine] = []
    per_group: list[FormulaLine] = []
    for formula in formulas:
        if _loaded_names(formula.expr) & varying_symbols:
            varying_symbols.add(formula.symbol)
            per_group.append(formula)
        else:
            shared.append(formula)

    declared = {f.symbol for f in formulas}
    keys = [str(group["key"]) for group in groups]

    def suffixed(symbol: str, key: str) -> str:
        name = f"{symbol}_{key}"
        if name in declared:
            raise UserError(
                f"expanding {symbol!r} for group {key!r} would produce "
                f"{name!r}, which the formulas already define; rename one of "
                f"them (a group's key becomes a symbol suffix)"
            )
        return name

    out_formulas = list(shared)
    for key in keys:
        rename = {symbol: suffixed(symbol, key) for symbol in varying_symbols}
        for formula in per_group:
            out_formulas.append(
                FormulaLine(
                    lineno=formula.lineno,
                    symbol=rename[formula.symbol],
                    expr=_rename(formula.expr, rename),
                    unit=formula.unit,
                    ref=formula.ref,
                )
            )

    out_checks: list[CheckLine] = []
    for check in checks:
        names = _loaded_names(check.expr)
        if check.utilisation:
            names.add(check.utilisation)
        if not (names & varying_symbols):
            out_checks.append(check)
            continue
        for key, group in zip(keys, groups):
            rename = {symbol: suffixed(symbol, key) for symbol in varying_symbols}
            label = str(group["label"])
            out_checks.append(
                CheckLine(
                    lineno=check.lineno,
                    expr=_rename(check.expr, rename),
                    description=f"{label} — {check.description}"
                    if check.description
                    else label,
                    utilisation=rename.get(check.utilisation, check.utilisation),
                )
            )

    return out_formulas, out_checks, sorted(varying_symbols)


def _group_values(
    values: Mapping[str, object], varying: str, groups: list[Mapping]
) -> dict[str, object]:
    """The card's givens: the shared ones, with the varying one expanded in place.

    The per-group rows are inserted exactly where the varying given sat, so the
    grouped card reads like the single-group card with one row opened out into N
    blocks. Each block is two rows — how many member ends fell in the group
    (referenced by its label/range) and the force that governs it (referenced by
    the member, node, position and load case it was read from). Those two rows
    are the whole provenance chain from the export to the design, side by side.
    """
    out: dict[str, object] = {}
    for name, value in values.items():
        if name != varying:
            out[name] = value
            continue
        for group in groups:
            key = str(group["key"])
            out[f"{COUNT_SYMBOL}_{key}"] = {
                "value": group["count"],
                "unit": COUNT_UNIT,
                "ref": str(group["label"]),
            }
            governing = group["governing"]
            if not isinstance(governing, Mapping):
                raise UserError(
                    f"group {key!r} has no governing record; a group's "
                    f"'governing' is the force record its design is sized for"
                )
            out[f"{varying}_{key}"] = governing
    return out


def _grouping_footnote(record: Mapping, groups: list[Mapping]) -> str:
    """The card's fine print: which rule divided the population, and how far.

    A reviewer must be able to check the division, not just read its result, so
    the strategy's name **and its exact parameters** go on the artifact rather
    than living only in the inputs file.
    """
    strategy = record.get("strategy", "?")
    params = record.get("params") or {}
    detail = ""
    if isinstance(params, Mapping) and params:
        detail = " (" + ", ".join(f"{k}={v!r}" for k, v in params.items()) + ")"
    total = record.get("count")
    counted = total if isinstance(total, int) else sum(int(g["count"]) for g in groups)
    plural = "" if len(groups) == 1 else "s"
    return (
        f"Grouped by {strategy!r}{detail} — {counted} member ends in "
        f"{len(groups)} group{plural}."
    )


# -- the nodes ---------------------------------------------------------------


# `formulas`/`checks` are inherently MULTI-LINE literals — one entry per line is
# the whole mini-syntax — so they declare the line-oriented calc editor instead
# of falling through to the type-derived single-line text box (ADR 0018 D2).
# `formulas` is also the deriving param, so the same declaration buys live
# line-numbered `parse_formulas` errors and socket chips; `checks` takes the
# plain multi-line branch. `language` selects the frontend's `calcsheet`
# preview dialect (`# reference` and `[unit]` are structure, not math).
#
# One declaration, shared by the two evaluating nodes: their signatures are the
# same, so their widgets must be too.
_CALC_WIDGETS = {
    "formulas": Widget(
        "calc",
        language="calcsheet",
        multiline=True,
        placeholder="symbol = expression [unit]  # reference",
    ),
    "checks": Widget(
        "calc",
        language="calcsheet",
        multiline=True,
        placeholder="expression  # description",
    ),
}


@node(
    widgets=_CALC_WIDGETS,
    dynamic=DerivedInputs(param="formulas", derive=formula_free_symbols),
    renderer=Renderer("html-card", socket="result", height=DEFAULT_CARD_HEIGHT),
)
def calc_card(
    title: str = "Calculation",
    as_of: str = "",
    formulas: str = "",
    checks: str = "",
    precision: int | None = None,
    **values: float | dict | None,
) -> str:
    """Evaluate a whole calculation and render it as a self-contained HTML card.

    ``formulas`` and ``checks`` are the mini-syntax documented on
    :func:`parse_formulas` / :func:`parse_checks` — one entry per line, ``#
    text`` being the reference/description and a trailing ``[unit]`` a
    formula's display unit. Every free symbol of ``formulas`` becomes an input
    socket (ADR 0007), so the given quantities are wired from upstream nodes
    rather than restated here. A given arriving as ``None`` is **empty** — not
    applicable to this case — and renders as ``–``; it is usable only inside
    ``MinDefined(...)``, which drops the arguments depending on it.

    ``as_of`` is caller-provided and never read from the clock: an artifact
    that re-renders differently tomorrow is not an artifact.

    A failing check renders **FAIL** on the card and leaves the run green — the
    verdict is card content, not an execution error. Only a malformed calc
    (unknown symbol, unparseable expression, a check that is not a verdict)
    raises.

    The one-node convenience form: :func:`calc` + :func:`render_html` do the
    same two steps with the ``Result`` on a wire between them. Its single
    ``result`` output is the HTML document.
    """
    result = _evaluate(title, as_of, formulas, checks, precision, values)
    # No options: the card comes out exactly as calcsheet renders it by default.
    return _render(result)


@node(
    widgets=_CALC_WIDGETS,
    dynamic=DerivedInputs(param="formulas", derive=formula_free_symbols),
)
def calc(
    title: str = "Calculation",
    as_of: str = "",
    formulas: str = "",
    checks: str = "",
    precision: int | None = None,
    **values: float | dict | None,
) -> Result:
    """Evaluate a whole calculation and emit the ``Result`` — no rendering here.

    Same authoring surface as :func:`calc_card` (the mini-syntax of
    :func:`parse_formulas` / :func:`parse_checks`, the derived symbol sockets of
    ADR 0007, the never-from-the-clock ``as_of``); what differs is the product.
    The ``result`` socket carries the completed calculation itself — rows,
    values, verdicts and pre-minted markup — so any number of renderings can
    hang off the one evaluation.

    A failing check is part of that result (``passed`` is False), not an
    execution error. Only a malformed calc raises.
    """
    return _evaluate(title, as_of, formulas, checks, precision, values)


@node(
    widgets=_CALC_WIDGETS,
    dynamic=DerivedInputs(param="formulas", derive=formula_free_symbols),
    renderer=Renderer("html-card", socket="result", height=GROUP_CARD_HEIGHT),
)
def group_card(
    title: str = "Calculation",
    as_of: str = "",
    formulas: str = "",
    checks: str = "",
    precision: int | None = None,
    **values: float | dict | None,
) -> str:
    """One calculation, run for every group of a population — as **one** card.

    Authoring is exactly :func:`calc_card`'s: the same ``formulas`` / ``checks``
    mini-syntax, the same derived symbol sockets (ADR 0007), the same
    caller-provided ``as_of``. The calculation is written **once, for one
    group**. What differs is that one of those sockets is fed a *group
    population* — the record ``grouping.group`` produces — instead of a single
    quantity, and the node then runs the calculation for each group.

    So the diff between designing one connection and designing N is one wire::

        F_c90d=governing   # rfem.governing_force  -> one design, sheet.calc_card
        F_c90d=groups      # grouping.group        -> N designs, sheet.group_card

    **How many groups there are is a property of the data, never of the graph.**
    Moving a threshold in the project's inputs changes the number of rows on the
    card and nothing about the canvas. That is why this is one node emitting one
    card rather than N per-group nodes: a graph whose shape tracked a tier list
    could not be edited without re-authoring it every time the list moved.

    **What the card shows, per group.** Its label (for tiers, the load range);
    how many member ends fell in it; the governing force with the member, node,
    position and load case it was read from; the utilisation the check reports;
    and that check's verdict. The shared givens and every formula that does not
    depend on the group appear exactly **once** — the groups share one geometry,
    and the card says so by not repeating it. The fine print names the strategy
    and its parameters, so the division itself can be checked and not merely
    read.

    **The accepted cost** (the owner's explicit trade): the per-group arithmetic
    happens inside this node instead of being individually openable on the
    canvas. The card carries that burden — every intermediate value is a row on
    it, subscripted with the group's key.

    A failing check renders **FAIL** for its group and leaves the run green,
    exactly as in :func:`calc_card`: the verdict is card content, not an
    execution error. A group that fails does not suppress the others — all N
    verdicts are on the one card, and the overall verdict is the conjunction.
    """
    varying, record = _varying_socket(values)
    groups = _validate_groups(record)

    parsed_formulas, parsed_checks, _ = _expand_for_groups(
        parse_formulas(formulas), parse_checks(checks), varying, groups
    )
    result = _evaluate_parsed(
        title,
        as_of,
        parsed_formulas,
        parsed_checks,
        precision,
        _group_values(values, varying, groups),
    )
    return _render(
        result, header="", footer=_grouping_footnote(record, groups), theme="auto"
    )


# The renderer declaration belongs to the node that actually produces HTML —
# here, not on `calc`, whose `Result` socket is data (ADR 0010 D1 / 0021 D3).
@node(renderer=Renderer("html-card", socket="result", height=DEFAULT_CARD_HEIGHT))
def render_html(
    result: Result,
    header: str = "",
    footer: str = "",
    theme: str = "light",
) -> str:
    """Render a :func:`calc` ``Result`` as a self-contained HTML card.

    The options are this node's own literals (ADR 0021 D3): flat scalars, so
    each gets a widget for free and the whole set round-trips the graph⟷source
    bijection. ``header`` is a banner above the card, ``footer`` the fine-print
    slot under the verdict, ``theme`` one of ``auto`` / ``light`` / ``dark``.
    They are presentation only and live here alone — the calculation upstream
    knows nothing about them.

    ``theme`` must be a literal scalar to be a node param, so calcsheet's
    default is mirrored here rather than deferred to; ``light`` is that default
    because a card is a document, not a panel of the editor around it.

    Deterministic: the same ``Result`` and options render byte-identical HTML,
    and with every option left at its default that HTML is exactly what
    :func:`calc_card` emits.
    """
    return _render(result, header=header, footer=footer, theme=theme)


# All node types this pack defines (handy for registries / snapshots).
NODES = [calc_card, calc, group_card, render_html]

__all__ = [
    "CheckLine",
    "COUNT_SYMBOL",
    "COUNT_UNIT",
    "DEFAULT_CARD_HEIGHT",
    "FormulaLine",
    "GROUPS_KEY",
    "GROUP_CARD_HEIGHT",
    "NODES",
    "calc",
    "calc_card",
    "formula_free_symbols",
    "group_card",
    "parse_checks",
    "parse_formulas",
    "render_html",
]
