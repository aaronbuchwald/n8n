"""``sym`` — the symbolic-math node pack (SymPy · forallpeople · handcalcs).

Simple, generic math only: build a symbolic expression, solve/rearrange it,
evaluate it to a number, attach real physical units to values, typeset the
substituted calculation steps, and render everything into a **self-contained
HTML card** (no CDN scripts/styles/fonts — typeset math is emitted as native
MathML, which browsers render with zero JavaScript).

**Lazy imports, by contract.** The heavy dependencies (``sympy``,
``handcalcs``, ``forallpeople``, ``latex2mathml``) are imported *inside* the
node bodies, never at module top level. Importing this module and listing its
node specs therefore works with none of them installed; only *running* a node
that needs a library requires it (install with the ``sym`` extra:
``uv sync --extra sym``). Keep it that way — a top-level heavy import here is
a regression.

Like every pack, each function is an ordinary Python callable first and a node
second — ``@node`` only registers it by its ``module.qualname`` id
(``sym.parse_expr``, ``sym.quantity``, …).
"""

from __future__ import annotations

import html
import itertools
import linecache
import re
import textwrap

from engine import node

# -- SymPy: expressions, solving, numeric evaluation ------------------------


def _sympify(expression):
    """Coerce ``expression`` (str or SymPy object) into a SymPy object.

    A string containing ``=`` becomes an equation (``Eq(lhs, rhs)``); anything
    else is parsed as a plain expression. SymPy objects pass through.
    """
    import sympy

    if isinstance(expression, str):
        if "=" in expression:
            lhs, rhs = expression.split("=", 1)
            return sympy.Eq(sympy.sympify(lhs), sympy.sympify(rhs))
        return sympy.sympify(expression)
    return expression


@node
def parse_expr(text: str = "x") -> object:
    """Parse ``text`` into a SymPy expression (or equation).

    ``"x**2 - 5*x + 6"`` becomes an expression; ``"a = b + c"`` (one ``=``)
    becomes a SymPy ``Eq``. The result is a live SymPy object, meant to be
    wired into :func:`solve_for`, :func:`substitute`, :func:`evaluate_numeric`.
    """
    return _sympify(text)


@node
def solve_for(expression: object = "0", symbol: str = "x") -> list:
    """Solve ``expression`` for ``symbol``; return the list of solutions.

    A plain expression is solved as ``expression == 0``; an equation (from
    ``parse_expr`` on ``"lhs = rhs"``) is solved as written. Solutions are
    SymPy objects (exact where possible: ``x**2 - 5*x + 6`` gives ``[2, 3]``).
    """
    import sympy

    return sympy.solve(_sympify(expression), sympy.Symbol(symbol))


@node
def substitute(expression: object = "0", symbol: str = "x", value: object = 0) -> object:
    """Substitute ``value`` for ``symbol`` in ``expression`` (still symbolic).

    ``value`` may be a number or another symbolic object — wiring a solution
    from :func:`solve_for` (via :func:`pick`) back into the original
    expression is the intended use (then :func:`evaluate_numeric` checks it).
    """
    import sympy

    return _sympify(expression).subs(sympy.Symbol(symbol), value)


@node
def evaluate_numeric(expression: object = "0", subs: dict = None) -> float:
    """Evaluate ``expression`` to a plain ``float`` via ``lambdify``.

    ``subs`` (optional) maps symbol names to numbers, e.g. ``{"x": 2.0}``;
    every free symbol must be covered. The expression is compiled to a numeric
    function with ``sympy.lambdify`` and called once — symbolic in, number out.
    """
    import sympy

    expr = _sympify(expression)
    subs = subs or {}
    symbols = sorted(expr.free_symbols, key=lambda s: s.name)
    missing = [s.name for s in symbols if s.name not in subs]
    if missing:
        raise ValueError(f"no value given for symbol(s) {missing}; add them to subs")
    fn = sympy.lambdify(symbols, expr)
    return float(fn(*(subs[s.name] for s in symbols)))


@node
def pick(values: list, index: int = 0) -> object:
    """Pick one element out of a list (e.g. one root from ``solve_for``)."""
    return values[index]


# -- forallpeople: real physical units on values -----------------------------

_env_loaded = False


def _si():
    """Import forallpeople and load its default SI environment once."""
    global _env_loaded
    import forallpeople as si

    if not _env_loaded:
        si.environment("default")  # adds derived units: N, Pa, J, W, ...
        _env_loaded = True
    return si


_UNIT_TOKEN = re.compile(r"^([A-Za-z]+)(?:\^(\d+))?$")


def _unit_factor(si, token: str):
    match = _UNIT_TOKEN.match(token.strip())
    if not match:
        raise ValueError(f"cannot parse unit factor {token!r} (use e.g. 'm', 's^2')")
    name, power = match.groups()
    unit = getattr(si, name, None)
    if unit is None:
        raise ValueError(f"unknown SI unit {name!r}")
    return unit ** int(power or 1)


@node
def quantity(value: float = 0.0, unit: str = "") -> object:
    """Attach a real SI unit to a number (a forallpeople ``Physical``).

    ``unit`` is a simple product/quotient of SI unit names with optional
    integer powers: ``"m"``, ``"m/s"``, ``"kg*m/s^2"`` (``**`` also accepted).
    An empty ``unit`` returns the plain float. Unit-carrying values combine
    through :func:`multiply` and auto-reduce to derived units (kg·m²/s² → J).
    """
    if not unit.strip():
        return float(value)
    si = _si()
    numerator, _, denominator = unit.replace("**", "^").partition("/")
    result = float(value)
    for token in numerator.split("*"):
        result = result * _unit_factor(si, token)
    if denominator:
        for token in denominator.split("*"):
            result = result / _unit_factor(si, token)
    return result


@node
def multiply(a: object = 1.0, b: object = 1.0, factor: float = 1.0) -> object:
    """``factor * a * b`` — units (when present) carry through and reduce.

    Works on plain numbers and unit-carrying quantities alike, so a graph can
    chain e.g. ``multiply(multiply(v, v), m, factor=0.5)`` for ½·m·v².
    """
    return factor * a * b


@node
def describe(value: object = "", label: str = "", precision: int = 4) -> str:
    """Format any value as short text, optionally prefixed ``label = ``.

    Floats are trimmed to ``precision`` significant digits; lists are joined
    with commas; unit-carrying quantities and symbolic objects use their own
    string forms (``9.000 J``, ``x - 2``).
    """

    def fmt(v: object) -> str:
        if isinstance(v, float):
            return f"{v:.{precision}g}"
        return str(v)

    text = ", ".join(fmt(v) for v in value) if isinstance(value, list) else fmt(value)
    return f"{label} = {text}" if label else text


# -- handcalcs: typeset the substituted calculation steps --------------------

_typeset_counter = itertools.count(1)


@node(outputs=["latex", "results"])
def typeset_calc(lines: str, values: dict, precision: int = 3) -> dict:
    """Typeset calculation ``lines`` with ``values`` substituted, via handcalcs.

    ``lines`` is one or more Python assignment lines (``"E_k = 1/2 * m *
    v**2"``); ``values`` maps each free name to its number. handcalcs renders
    the symbolic form, the substituted numbers, and the result as LaTeX
    (socket ``latex``); socket ``results`` carries the computed variables.

    ``lines`` is **executed as Python** to obtain the numbers handcalcs
    substitutes — treat it with exactly the trust you give any ``@node`` body
    (the whole graph is ordinary Python; see ADR 0003 on the future sandbox).
    """
    from handcalcs.decorator import handcalc

    for name in values:
        if not name.isidentifier():
            raise ValueError(f"values key {name!r} is not a valid identifier")
    body = textwrap.indent(textwrap.dedent(lines).strip(), "    ")
    if not body.strip():
        raise ValueError("lines is empty; give at least one assignment line")
    source = f"def _calc({', '.join(values)}):\n{body}\n    return locals()\n"

    # handcalcs reads the function's source via inspect/linecache, so give the
    # compiled code a filename that linecache can resolve.
    filename = f"<sym-typeset-{next(_typeset_counter)}>"
    linecache.cache[filename] = (len(source), None, source.splitlines(True), filename)
    namespace: dict = {}
    exec(compile(source, filename, "exec"), namespace)

    latex, results = handcalc(precision=precision, jupyter_display=False)(
        namespace["_calc"]
    )(**values)
    return {"latex": latex, "results": results}


# -- rendering: LaTeX -> native MathML -> self-contained HTML ---------------

_LATEX_WRAPPERS = re.compile(r"(^\s*(\$\$|\\\[)\s*)|(\s*(\$\$|\\\])\s*$)")
_ALIGNED = re.compile(r"\\(?:begin|end)\{aligned\}")


@node
def latex_to_mathml(latex: str = "") -> str:
    """Convert LaTeX math to native MathML (zero-JS, CDN-free rendering).

    Accepts a bare expression or a handcalcs block (``$$ \\begin{aligned}…``):
    wrappers are stripped and each ``\\\\`` row converts to its own
    ``<math display="block">`` element. The MathML namespace attribute is
    dropped — it is implied in HTML parsing, and keeps the output free of any
    ``http`` reference.
    """
    import latex2mathml.converter

    body = _ALIGNED.sub("", _LATEX_WRAPPERS.sub("", latex.strip()))
    rows = [row.strip().replace("&", "") for row in body.split("\\\\")]
    blocks = []
    for row in rows:
        if not row:
            continue
        mathml = latex2mathml.converter.convert(row, display="block")
        blocks.append(mathml.replace(' xmlns="http://www.w3.org/1998/Math/MathML"', ""))
    return "\n".join(blocks)


@node
def join_text(a: str = "", b: str = "", c: str = "", sep: str = " · ") -> str:
    """Join up to three text fragments with ``sep``, skipping empty ones."""
    return sep.join(part for part in (a, b, c) if part)


@node
def render_math_card(title: str = "Calculation", mathml: str = "", caption: str = "") -> str:
    """Render a self-contained HTML card: title, MathML block, caption.

    Inline CSS only — no external scripts, styles or fonts, so the card is
    safe to embed anywhere offline. ``title`` and ``caption`` are HTML-escaped.
    ``mathml`` is trusted markup from :func:`latex_to_mathml`; anything that
    is not pure ``<math>`` markup (scripts, event handlers, URLs) is refused
    to keep the self-contained guarantee honest.
    """
    lowered = mathml.lower()
    if any(bad in lowered for bad in ("<script", "onerror", "onload", "href=", "src=", "http")):
        raise ValueError("mathml must be plain MathML markup (from latex_to_mathml)")
    return (
        '<div style="font-family:system-ui,-apple-system,sans-serif;'
        "max-width:28rem;padding:1rem;border:1px solid #ddd;border-radius:8px;"
        'box-shadow:0 1px 3px rgba(0,0,0,.08)">'
        f'<h1 style="font-size:1rem;margin:0 0 .5rem">{html.escape(title)}</h1>'
        f'<div style="overflow-x:auto;font-size:1.05rem">{mathml}</div>'
        f'<p style="margin:.5rem 0 0;color:#666;font-size:.85rem">{html.escape(caption)}</p>'
        "</div>"
    )


# All node types this pack defines (handy for registries / snapshots).
NODES = [
    parse_expr,
    solve_for,
    substitute,
    evaluate_numeric,
    pick,
    quantity,
    multiply,
    describe,
    typeset_calc,
    latex_to_mathml,
    join_text,
    render_math_card,
]

__all__ = [
    "parse_expr",
    "solve_for",
    "substitute",
    "evaluate_numeric",
    "pick",
    "quantity",
    "multiply",
    "describe",
    "typeset_calc",
    "latex_to_mathml",
    "join_text",
    "render_math_card",
    "NODES",
]
