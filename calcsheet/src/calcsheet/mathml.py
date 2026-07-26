"""Expression text -> sympy -> LaTeX -> native MathML.

MathML is why a rendered card can honestly call itself self-contained:
browsers typeset it with zero JavaScript, so there is no CDN, no web font and
no runtime script anywhere in the output. sympy owns parsing and LaTeX;
``latex2mathml`` owns the LaTeX -> MathML step.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping

import latex2mathml.converter
import sympy
from sympy.core.basic import Basic
from sympy.core.relational import Relational
from sympy.logic.boolalg import Boolean

from .errors import CalcError

# handcalcs-style LaTeX blocks arrive wrapped in `$$`/`\[` and may carry an
# `aligned` environment; both are stripped before conversion.
_LATEX_WRAPPERS = re.compile(r"(^\s*(\$\$|\\\[)\s*)|(\s*(\$\$|\\\])\s*$)")
_ALIGNED = re.compile(r"\\(?:begin|end)\{aligned\}")

# Anything that could reach the network or execute — the self-contained
# guarantee is only worth stating if it is enforced.
_UNSAFE_MARKUP = ("<script", "onerror", "onload", "href=", "src=", "http")


# -- the expression vocabulary -----------------------------------------------
#
# Names an author may call that are NOT sympy's own. Everything here is a real
# sympy object with a real printer, so the card typesets it the way sympy
# typesets anything else — no post-hoc string surgery on the LaTeX.


class MinDefined(sympy.Function):
    r"""``MinDefined(a, b, …)`` — the minimum over the arguments that *apply*.

    Engineering sheets state a rule over quantities that may not exist for the
    case at hand: ``l_r = min(30, l, l_1/2)`` where the member has no second
    bearing length, so the sheet prints ``l_1 = –``. The rule is still the
    rule — it is printed in full — and only the arguments that depend on an
    empty given drop out before the minimum is taken. That dropping is
    :func:`resolve_min_defined`; this class is just the vocabulary word.

    Stays deliberately **unevaluated** (no ``eval``): the card typesets the
    ORIGINAL call so the general rule stays visible, while the value comes from
    the resolved one. :meth:`_latex` prints ``\min\left(…\right)`` through the
    printer, so each argument is rendered by sympy's own rules and the result is
    built, never patched.

    Deliberately **no** ``MaxDefined``: nothing needs the symmetric twin yet,
    and a vocabulary word with no caller is a guess about the future rather than
    a feature. Add it when a sheet actually asks for it.
    """

    def _latex(self, printer) -> str:
        arguments = ", ".join(printer._print(argument) for argument in self.args)
        return rf"\min\left({arguments}\right)"


# The vocabulary, as a mapping, so `parse_expression` and anything that wants to
# *list* what an author may call read the same one source.
EXPRESSION_FUNCTIONS: dict[str, object] = {"MinDefined": MinDefined}


def symbol_table(names: Iterable[str]) -> dict[str, sympy.Symbol]:
    """Bind every declared name to a plain symbol.

    Without this, sympy would silently read declared names as its own
    constants (``E`` as Euler's number, ``I`` as the imaginary unit) and the
    calc would compute something the author never wrote. Names the calc does
    *not* declare still resolve normally, which is what makes ``pi`` and
    ``sqrt(2)`` usable in an expression.
    """
    return {name: sympy.Symbol(name) for name in names}


def parse_expression(text: str, names: Iterable[str], *, what: str) -> Basic:
    """Parse ``text`` into a sympy object, or raise :class:`CalcError`.

    ``what`` labels the offending item in the error message (``"formula
    'r'"``). Expression text is author-supplied data and is parsed by
    ``sympify``, i.e. with the same trust you would give any Python source in
    the same file.

    The vocabulary (:data:`EXPRESSION_FUNCTIONS`) is bound first and the calc's
    own declared names second, so a calc that declares a symbol called
    ``MinDefined`` still gets a plain symbol — declared names always win, which
    is the same rule :func:`symbol_table` applies to sympy's constants.
    """
    scope: dict[str, object] = dict(EXPRESSION_FUNCTIONS)
    scope.update(symbol_table(names))
    try:
        return sympy.sympify(text, locals=scope)
    except Exception as error:  # sympy raises SympifyError, SyntaxError, TypeError…
        raise CalcError(
            f"{what}: cannot parse expression {text!r} ({type(error).__name__}: {error})"
        ) from error


def free_names(expr: Basic) -> set[str]:
    """The symbol names ``expr`` depends on."""
    return {symbol.name for symbol in expr.free_symbols}


def resolve_min_defined(expr: Basic, empty: Collection[str], *, what: str) -> Basic:
    """``expr`` with every :class:`MinDefined` reduced to a plain ``sympy.Min``.

    An argument is dropped when its **free symbols** include an empty given, so
    a sub-expression counts: with ``l_1`` empty, ``MinDefined(30, l, l_1/2)``
    resolves to ``Min(30, l)``. Everything else is rebuilt unchanged, so a
    ``MinDefined`` nested anywhere in the tree is resolved too.

    The result is what gets *evaluated*; callers keep the original ``expr`` for
    the card, which is how the row can show the whole rule and the value of the
    part that applies. Dropping *every* argument leaves no rule at all, so that
    raises rather than inventing a number.
    """
    empty = set(empty)

    def resolve(node: Basic) -> Basic:
        if isinstance(node, MinDefined):
            kept = [arg for arg in node.args if not (free_names(arg) & empty)]
            if not kept:
                blocking = ", ".join(repr(n) for n in sorted(free_names(node) & empty))
                raise CalcError(
                    f"{what}: every argument of {node} depends on an empty given "
                    f"({blocking}), so the minimum is over nothing; give one of "
                    f"them a value, or drop the formula for this case"
                )
            return sympy.Min(*(resolve(arg) for arg in kept))
        if node.args:
            return node.func(*(resolve(arg) for arg in node.args))
        return node

    return resolve(expr)


def assert_no_empty(expr: Basic, empty: Collection[str], *, what: str) -> None:
    """Reject an empty given used outside :class:`MinDefined`.

    Run against the **resolved** expression, where every ``MinDefined`` has
    already dropped what it could: anything empty still standing there is being
    asked to be a number, and an empty given has none. Formulas therefore can
    never evaluate to empty — only givens are ever empty.
    """
    used = sorted(free_names(expr) & set(empty))
    if used:
        raise CalcError(
            f"{what}: {', '.join(repr(name) for name in used)} has no value on "
            f"this sheet, and an empty given may only appear inside "
            f"MinDefined(...), where the argument holding it is dropped"
        )


def evaluate_numeric(
    expr: Basic, scope: Mapping[str, float | None], *, what: str
) -> float:
    """Evaluate ``expr`` to a plain ``float`` with ``scope`` substituted.

    Compiles the expression once with ``lambdify`` and calls it — symbolic in,
    number out. Every free symbol must be present in ``scope``; callers check
    that first so the message can name what is missing.
    """
    symbols = sorted(expr.free_symbols, key=lambda s: s.name)
    try:
        fn = sympy.lambdify(symbols, expr)
        return float(fn(*(scope[s.name] for s in symbols)))
    except Exception as error:
        raise CalcError(
            f"{what}: cannot evaluate {expr} to a number "
            f"({type(error).__name__}: {error})"
        ) from error


def substitute(expr: Basic, scope: Mapping[str, float | None]) -> Basic:
    """Substitute ``scope`` into ``expr``, still symbolically.

    Used for checks: substituting a relational collapses it to a sympy
    ``BooleanTrue``/``BooleanFalse`` that ``bool()`` reads directly.
    """
    return expr.subs({sympy.Symbol(name): value for name, value in scope.items()})


def is_boolean(expr: Basic) -> bool:
    """True when ``expr`` is a verdict (relational or boolean), not a quantity."""
    return isinstance(expr, Boolean)


def is_symbol_named(expr: Basic, name: str) -> bool:
    """True when ``expr`` is exactly the bare symbol ``name`` (not ``2 * name``)."""
    return isinstance(expr, sympy.Symbol) and expr.name == name


def bound_sides(expr: Basic) -> tuple[Basic, Basic] | None:
    """``(bounded, bound)`` when ``expr`` says "this must not exceed that".

    ``eta <= 1.0`` and ``1.0 >= eta`` both give ``(eta, 1.0)``; ``a == b`` and
    ``And(...)`` give ``None``. Callers use this to name a check's limit, so
    only inequalities — where "the other side" is a real ceiling — qualify.
    """
    if not isinstance(expr, Relational):
        return None
    if expr.rel_op in ("<", "<="):
        return expr.lhs, expr.rhs
    if expr.rel_op in (">", ">="):
        return expr.rhs, expr.lhs
    return None


def latex_to_mathml(latex: str, display: str = "block") -> str:
    """Convert LaTeX math to native MathML (zero-JS, CDN-free rendering).

    Accepts a bare expression or a multi-row block: wrappers are stripped and
    each ``\\\\`` row converts to its own ``<math>`` element. The MathML
    namespace attribute is dropped — it is implied in HTML parsing, and keeps
    the output free of any ``http`` reference.

    ``display`` is ``"block"`` for standalone equations and ``"inline"`` for
    the four-slot rows, where the math sits in a grid cell and must share the
    row's baseline rather than form its own centred block.
    """
    body = _ALIGNED.sub("", _LATEX_WRAPPERS.sub("", latex.strip()))
    rows = [row.strip().replace("&", "") for row in body.split("\\\\")]
    blocks = []
    for row in rows:
        if not row:
            continue
        markup = latex2mathml.converter.convert(row, display=display)
        blocks.append(markup.replace(' xmlns="http://www.w3.org/1998/Math/MathML"', ""))
    return "\n".join(blocks)


def expression_mathml(expr: Basic, display: str = "inline") -> str:
    """MathML for a sympy object, via its LaTeX form.

    Underscored names become subscripts for free: sympy prints ``F_max`` as
    ``F_{max}``, which MathML renders as F with a "max" subscript.
    """
    return latex_to_mathml(sympy.latex(expr), display=display)


def symbol_mathml(name: str, display: str = "inline") -> str:
    """MathML for a bare symbol name (``"F_max"`` -> F with subscript "max")."""
    return expression_mathml(sympy.Symbol(name), display=display)


def assert_plain_mathml(markup: str) -> None:
    """Refuse anything that is not pure MathML markup.

    Ported from the graph engine's card renderer: the card embeds this markup
    verbatim, so scripts, event handlers and URLs are rejected outright rather
    than escaped. Keeping the guard here means the "no network, no JS"
    promise is checked on every render, not just asserted in a README.
    """
    lowered = markup.lower()
    for bad in _UNSAFE_MARKUP:
        if bad in lowered:
            raise CalcError(
                f"math markup must be plain MathML (from latex_to_mathml); "
                f"found {bad!r} in {markup[:120]!r}"
            )
