"""``sheet`` — the calcsheet node pack: a whole calculation as ONE node.

One node, :func:`calc_card`: it declares a calculation as data (inputs,
formulas, checks), evaluates it **once** through :mod:`calcsheet`, and renders
that single result as a self-contained "C4 four-slot" HTML card with a binary
pass/fail verdict. Nothing downstream re-derives anything — rows, values and
verdicts are all pure functions of the one ``Result``.

**Why the pack is called ``sheet``, not ``calcsheet``.** ``nodepacks/`` is
importable as top-level packages, so a pack directory named ``calcsheet``
would shadow the real library. The pack is ``sheet``; node ids are
``sheet.calc_card``.

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
from collections.abc import Sequence
from dataclasses import dataclass

from engine import DerivedInputs, Renderer, UserError, node

# -- the mini-syntax ---------------------------------------------------------
#
# One entry per line. For a formula:
#
#     symbol = expression [unit]  # reference
#
# for a check:
#
#     expression  # description
#
# `# text` is the reference (formula) or description (check); a trailing
# `[unit]` on a formula's expression is its display unit. Blank lines and
# whole-line comments are skipped; anything else that does not fit raises a
# UserError naming the line.

# A trailing `[...]` on a formula expression — its display unit.
_UNIT = re.compile(r"\[([^\[\]]*)\]\s*$")

# Cap on the authored text so deriving (which runs per keystroke through the
# derive endpoint) stays cheap. Mirrors sym.handcalc's own cap.
_MAX_TEXT_LEN = 10_000

# Significant digits used when `precision` is left unset (a cleared number
# widget commits `null`, which means "not set" — never a crash).
DEFAULT_PRECISION = 3

# Static parameters of `calc_card` a derived symbol may not shadow.
_STATIC_PARAMS = frozenset({"title", "as_of", "formulas", "checks", "precision"})

# Math names sympy resolves on its own, so they must NOT become sockets — they
# are only left unbound (calcsheet binds *declared* names as plain symbols, so
# an undeclared `sqrt`/`pi` keeps its sympy meaning). Mirrors sym.handcalc's
# whitelist; additive — a name outside it simply becomes a socket, which is
# visible on the canvas.
_MATH_NAMES = frozenset({"sqrt", "sin", "cos", "tan", "log", "exp", "pi"})

# Names never turned into sockets: Python builtins + the math names above.
_NON_SOCKET_NAMES = frozenset(dir(builtins)) | _MATH_NAMES


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
    """One parsed check entry: a boolean ``expr`` plus its description."""

    lineno: int
    expr: str
    description: str


def _entries(text: str, *, what: str) -> list[tuple[int, str, str]]:
    """Split ``text`` into ``(lineno, body, comment)`` triples, defensively.

    Blank lines and whole-line ``#`` comments (leading whitespace allowed) are
    skipped. The comment is everything after the first ``#``; the body is what
    precedes it.
    """
    if not isinstance(text, str):
        raise UserError(f"calc_card {what!r} must be a string, got {type(text).__name__}")
    if len(text) > _MAX_TEXT_LEN:
        raise UserError(
            f"calc_card {what!r} is too long ({len(text)} chars; limit {_MAX_TEXT_LEN})"
        )

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

    A check must be a relational/boolean expression over the final scope;
    calcsheet rejects a bare quantity ("a number is not a verdict"). Note a
    failing check does NOT fail the run — it renders FAIL on the card.
    """
    checks: list[CheckLine] = []
    for lineno, body, description in _entries(text, what="checks"):
        if "=" in body.replace("==", "").replace("!=", "").replace("<=", "").replace(">=", ""):
            raise UserError(
                f"checks line {lineno}: {body!r} looks like an assignment; a check is "
                f"a comparison such as 'U < 100' (use '==' to test equality)"
            )
        _check_expression(body, what="checks", lineno=lineno)
        checks.append(CheckLine(lineno, body, description))
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

    The deriver for :func:`calc_card` (ADR 0007 D3) — the same contract
    ``sym.handcalc`` uses, so ``F_max``/``C_min`` render as real wired sockets
    on the canvas. A name *read* before any formula defines it is an input; a
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
                    f"parameter {name!r} of calc_card"
                )
            if name not in seen:
                seen.add(name)
                order.append(name)
        defined.add(formula.symbol)

    return [_derived_socket(name) for name in order]


# -- card height: the surface scales with the content ------------------------
#
# A `sandbox=""` iframe runs no scripts, so the card cannot measure and report
# its own height. The row/check counts are known here, though, and the card's
# CSS is fixed — so the height is computed at render time and published on the
# `height` socket. The frontend `html-card` renderer prefers that per-instance
# value and falls back to the statically declared `config.height`.
#
# The constants below were measured in a browser against calcsheet's stylesheet
# (render.py) and are deliberately rounded UP: a card that is a few px too tall
# shows a sliver of whitespace, while one that is too short scrolls.

_CHROME = 157  # body padding (28+28) + .card__head (58) + .foot (43)
_SECTION = 54  # one .sec: 14+14 padding + .sec__label line + border
_INPUT_ROW = 21  # an input row: symbol = value (no typeset definition)
_FORMULA_ROW = 24  # a formula row, allowing for a fraction in the definition
_ROW_GAP = 12  # .rows{row-gap:12px}
_CHECK_ROW = 44  # one .chk: border + 9+9 padding + the expression line
_CHECK_DESCRIPTION = 20  # .chk__what — the second line, when a check has one
_CHECK_GAP = 8  # .checks{gap:8px}
_MIN_HEIGHT = 160

# The statically declared fallback — what the renderer shows before the first
# run, and for any consumer that ignores the per-instance socket.
DEFAULT_CARD_HEIGHT = 320


def card_height(inputs: int, formulas: int, checks: Sequence[str]) -> int:
    """Pixel height a rendered card needs, from its row and check counts.

    ``checks`` carries each check's description text (a described check renders
    a second line, an undescribed one does not). An empty section is not
    rendered at all, so it costs nothing.
    """
    height = _CHROME
    if inputs:
        height += _SECTION + _INPUT_ROW * inputs + _ROW_GAP * (inputs - 1)
    if formulas:
        height += _SECTION + _FORMULA_ROW * formulas + _ROW_GAP * (formulas - 1)
    if checks:
        height += _SECTION + _CHECK_GAP * (len(checks) - 1)
        height += sum(
            _CHECK_ROW + (_CHECK_DESCRIPTION if description else 0) for description in checks
        )
    return max(height, _MIN_HEIGHT)


# -- the node ----------------------------------------------------------------


@node(
    outputs=["result", "height"],
    dynamic=DerivedInputs(param="formulas", derive=formula_free_symbols),
    renderer=Renderer(
        "html-card",
        socket="result",
        height=DEFAULT_CARD_HEIGHT,
        heightSocket="height",
    ),
)
def calc_card(
    title: str = "Calculation",
    as_of: str = "",
    formulas: str = "",
    checks: str = "",
    precision: int | None = None,
    **values: float,
) -> dict:
    """Evaluate a whole calculation and render it as a self-contained HTML card.

    ``formulas`` and ``checks`` are the mini-syntax documented on
    :func:`parse_formulas` / :func:`parse_checks` — one entry per line, ``#
    text`` being the reference/description and a trailing ``[unit]`` a
    formula's display unit. Every free symbol of ``formulas`` becomes an input
    socket (ADR 0007), so the given quantities are wired from upstream nodes
    rather than restated here.

    ``as_of`` is caller-provided and never read from the clock: an artifact
    that re-renders differently tomorrow is not an artifact.

    A failing check renders **FAIL** on the card and leaves the run green — the
    verdict is card content, not an execution error. Only a malformed calc
    (unknown symbol, unparseable expression, a check that is not a verdict)
    raises.

    Outputs: ``result`` (the HTML document) and ``height`` (the px height the
    card needs, so the sandboxed iframe can size to its content).
    """
    from calcsheet import Calc, CalcError, Check, Formula, Input, evaluate_calc, render_html

    parsed_formulas = parse_formulas(formulas)
    parsed_checks = parse_checks(checks)

    inputs = {}
    for name, value in values.items():
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
        checks=[Check(c.expr, c.description) for c in parsed_checks],
        # An emptied number widget commits `null`, which is the UI's way of
        # saying "not set" — that must mean the default, not a crash.
        precision=DEFAULT_PRECISION if precision is None else precision,
    )
    try:
        result = evaluate_calc(calc)
    except CalcError as error:
        # calcsheet's messages already name the offending symbol/expression and
        # list what IS available — surface them as the user's own error.
        raise UserError(str(error)) from None

    return {
        "result": render_html(result),
        "height": card_height(
            len(result.inputs),
            len(result.formulas),
            [check.description for check in result.checks],
        ),
    }


# All node types this pack defines (handy for registries / snapshots).
NODES = [calc_card]

__all__ = [
    "CheckLine",
    "DEFAULT_CARD_HEIGHT",
    "FormulaLine",
    "NODES",
    "calc_card",
    "card_height",
    "formula_free_symbols",
    "parse_checks",
    "parse_formulas",
]
