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
    """One derived input-spec entry for a free symbol (ADR 0007 frozen shape)."""
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


# -- the shared pipeline -----------------------------------------------------
#
# ONE evaluation path and ONE rendering path, called by both the welded
# `calc_card` and the split `calc` + `render_html` pair (ADR 0021 D2). Keeping
# them here is what makes "the split renders exactly what the single node
# renders" true by construction rather than by test.


def _evaluate(
    title: str,
    as_of: str,
    formulas: str,
    checks: str,
    precision: int | None,
    values: dict[str, float],
) -> Result:
    """Parse the mini-syntax, build the ``Calc`` and evaluate it once."""
    from calcsheet import Calc, CalcError, Check, Formula, Input, evaluate_calc

    parsed_formulas = parse_formulas(formulas)
    parsed_checks = parse_checks(checks)

    inputs = {}
    for name, value in values.items():
        # `None` is an EMPTY given, not a bad one: an upstream source said "this
        # quantity does not apply to this case" (a JSON null), and calcsheet
        # renders it as `–` and drops it out of any MinDefined(...) that names
        # it. Coercing or rejecting it here would erase that statement.
        if value is None:
            inputs[name] = Input(None)
            continue
        try:
            inputs[name] = Input(float(value))
        except (TypeError, ValueError):
            raise UserError(
                f"input {name!r} must be a number, got {value!r} "
                f"({type(value).__name__})"
            ) from None

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


def _render(result: Result, *, header: str, footer: str, theme: str) -> str:
    """Render ``result`` as the self-contained HTML card."""
    from calcsheet import CalcError, HtmlOptions, Result
    from calcsheet import render_html as render_html_card

    if not isinstance(result, Result):
        raise UserError(
            f"the 'result' input must be a calcsheet Result (wire it from a "
            f"calc node), got {type(result).__name__}"
        )
    try:
        options = HtmlOptions(theme=theme, header=header, footer=footer)
    except CalcError as error:
        # The only rejectable option is an unknown theme, and its message
        # already lists the available ones.
        raise UserError(str(error)) from None
    return render_html_card(result, options)


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
    **values: float | None,
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
    return _render(result, header="", footer="", theme="auto")


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
    **values: float | None,
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


# The renderer declaration belongs to the node that actually produces HTML —
# here, not on `calc`, whose `Result` socket is data (ADR 0010 D1 / 0021 D3).
@node(renderer=Renderer("html-card", socket="result", height=DEFAULT_CARD_HEIGHT))
def render_html(
    result: Result,
    header: str = "",
    footer: str = "",
    theme: str = "auto",
) -> str:
    """Render a :func:`calc` ``Result`` as a self-contained HTML card.

    The options are this node's own literals (ADR 0021 D3): flat scalars, so
    each gets a widget for free and the whole set round-trips the graph⟷source
    bijection. ``header`` is a banner above the card, ``footer`` the fine-print
    slot under the verdict, ``theme`` one of ``auto`` / ``light`` / ``dark``.
    They are presentation only and live here alone — the calculation upstream
    knows nothing about them.

    Deterministic: the same ``Result`` and options render byte-identical HTML,
    and with every option left at its default that HTML is exactly what
    :func:`calc_card` emits.
    """
    return _render(result, header=header, footer=footer, theme=theme)


# All node types this pack defines (handy for registries / snapshots).
NODES = [calc_card, calc, render_html]

__all__ = [
    "CheckLine",
    "DEFAULT_CARD_HEIGHT",
    "FormulaLine",
    "NODES",
    "calc",
    "calc_card",
    "formula_free_symbols",
    "parse_checks",
    "parse_formulas",
    "render_html",
]
