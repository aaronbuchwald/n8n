"""One evaluation, one result.

The rendered string never drives a decision: rows, values and verdicts are all
pure functions of the single :class:`Result` produced here, so the card cannot
disagree with the numbers it was built from.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .errors import CalcError
from .mathml import (
    assert_plain_mathml,
    bound_sides,
    evaluate_numeric,
    expression_mathml,
    free_names,
    is_boolean,
    is_symbol_named,
    parse_expression,
    substitute,
    symbol_mathml,
)
from .model import Calc, Check

# Identifiers in the author's own expression text, replaced one pass at a time
# so a substituted number can never be re-substituted.
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")


@dataclass(frozen=True)
class Row:
    """One four-slot row: ``symbol │ definition │ value + unit │ reference``.

    Input rows carry an empty ``definition`` (a given has no right-hand side);
    formula rows carry both. Both MathML fields are ready-to-embed markup.
    """

    symbol: str
    symbol_mathml: str
    definition: str
    definition_mathml: str
    value: float
    value_text: str
    unit: str
    ref: str


@dataclass(frozen=True)
class CheckResult:
    """One design check and its verdict.

    ``passed`` is the verdict and is authoritative. ``utilisation`` and
    ``limit`` are the same fact as a margin an engineer can read and tooling
    can rank — present only when the check declared a utilisation symbol and
    (for ``limit``) the check is an inequality bounding it.
    """

    expr: str
    expr_mathml: str
    description: str
    substituted: str  # e.g. "57.1 < 50 = False"
    passed: bool
    utilisation: float | None = None
    limit: float | None = None


@dataclass(frozen=True)
class Result:
    """Everything a renderer needs — and nothing it has to recompute.

    ``governing`` is ``(check expression, utilisation)`` for the worst check
    that reported one — the critical case a reviewer looks for first. It is
    ``None`` when no check declared a utilisation; ``passed`` does not depend
    on it.
    """

    title: str
    as_of: str
    precision: int
    inputs: tuple[Row, ...]
    formulas: tuple[Row, ...]
    checks: tuple[CheckResult, ...]
    values: Mapping[str, float] = field(default_factory=dict)
    passed: bool = True
    governing: tuple[str, float] | None = None

    def to_dict(self) -> dict[str, object]:
        """This result as a versioned, ``json.dumps``-able dict."""
        from .serialize import result_to_dict

        return result_to_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> Result:
        """Rebuild a result from :meth:`to_dict` — lossless both ways."""
        from .serialize import result_from_dict

        return result_from_dict(data)


def format_value(value: object, precision: int) -> str:
    """Format a value for display: floats to ``precision`` significant digits.

    ``0.5714…`` -> ``0.571``, ``57.14…`` -> ``57.1``, ``120`` -> ``120``.
    """
    if isinstance(value, float):
        return f"{value:.{precision}g}"
    return str(value)


def _known(scope: Mapping[str, float]) -> str:
    return ", ".join(scope) or "(none)"


def _require_known(expr, scope: Mapping[str, float], *, what: str) -> None:
    """Reject a reference to a name the scope does not (yet) hold."""
    unknown = sorted(free_names(expr) - set(scope))
    if unknown:
        raise CalcError(
            f"{what}: unknown symbol(s) {', '.join(repr(n) for n in unknown)}; "
            f"available names: {_known(scope)} "
            f"(formulas evaluate in declaration order, so a formula may only "
            f"reference symbols declared before it)"
        )


def _substituted_text(text: str, scope: Mapping[str, float], precision: int) -> str:
    """The author's expression with every known symbol replaced by its value."""

    def replace(match: re.Match[str]) -> str:
        name = match.group(0)
        if name in scope:
            return format_value(scope[name], precision)
        return name

    return _IDENTIFIER.sub(replace, text)


def _row(
    symbol: str,
    definition: str,
    definition_mathml: str,
    value: float,
    unit: str,
    ref: str,
    precision: int,
) -> Row:
    symbol_markup = symbol_mathml(symbol)
    assert_plain_mathml(symbol_markup)
    if definition_mathml:
        assert_plain_mathml(definition_mathml)
    return Row(
        symbol=symbol,
        symbol_mathml=symbol_markup,
        definition=definition,
        definition_mathml=definition_mathml,
        value=value,
        value_text=format_value(value, precision),
        unit=unit,
        ref=ref,
    )


def _margin(
    check: Check, expr, scope: Mapping[str, float], *, what: str
) -> tuple[float | None, float | None]:
    """A check's utilisation and the limit it is measured against.

    Both are ``None`` for a check that declared no utilisation symbol — the
    binary verdict is unaffected either way. ``limit`` additionally needs the
    check to be an inequality bounding that very symbol (``eta <= 1.0``), so
    the two numbers are genuinely comparable; anything else reports the
    utilisation alone rather than a misleading pairing.
    """
    if not check.utilisation:
        return None, None
    if check.utilisation not in scope:
        raise CalcError(
            f"{what}: utilisation symbol {check.utilisation!r} is not defined; "
            f"available names: {_known(scope)}"
        )
    utilisation = scope[check.utilisation]

    sides = bound_sides(expr)
    if sides is None:
        return utilisation, None
    bounded, bound = sides
    if not is_symbol_named(bounded, check.utilisation):
        return utilisation, None
    if check.utilisation in free_names(bound):
        return utilisation, None
    return utilisation, evaluate_numeric(bound, scope, what=what)


def _governing(checks: Sequence[CheckResult]) -> tuple[str, float] | None:
    """The worst reported utilisation and the check it came from.

    Two checks can share one utilisation symbol against different limits
    (``eta <= 1.0`` and ``eta <= 0.833``); the tighter limit is the one that
    actually binds, so it wins the tie. Anything still tied goes to the
    earlier check, keeping the answer deterministic.
    """
    worst: CheckResult | None = None
    for check in checks:
        if check.utilisation is None:
            continue
        if worst is None or check.utilisation > worst.utilisation:
            worst = check
        elif check.utilisation == worst.utilisation and _tighter(check, worst):
            worst = check
    return None if worst is None else (worst.expr, worst.utilisation)


def _tighter(check: CheckResult, than: CheckResult) -> bool:
    """True when ``check`` binds harder — a stated limit beats none."""
    if check.limit is None:
        return False
    return than.limit is None or check.limit < than.limit


def evaluate_calc(calc: Calc) -> Result:
    """Evaluate ``calc`` once: inputs seed the scope, formulas thread through it.

    Formulas run in declaration order over ONE scope and each result joins it;
    checks then run against that final scope. Any false check makes the whole
    calc fail — the severity is binary by design.
    """
    # Type first, then range: comparing a non-number to an int raises a raw
    # TypeError whose message says nothing about which field is wrong.
    if isinstance(calc.precision, bool) or not isinstance(calc.precision, int):
        raise CalcError(
            f"precision must be a whole number, got {calc.precision!r}"
            f" ({type(calc.precision).__name__})"
        )
    if calc.precision < 1:
        raise CalcError(f"precision must be at least 1, got {calc.precision}")

    scope: dict[str, float] = {}
    input_rows: list[Row] = []
    for symbol, given in calc.inputs.items():
        if not symbol.isidentifier():
            raise CalcError(f"input {symbol!r} is not a valid symbol name")
        scope[symbol] = given.value
        input_rows.append(
            _row(symbol, "", "", given.value, given.unit, given.ref, calc.precision)
        )

    formula_rows: list[Row] = []
    for formula in calc.formulas:
        what = f"formula {formula.symbol!r}"
        if not formula.symbol.isidentifier():
            raise CalcError(f"{what} is not a valid symbol name")
        if formula.symbol in scope:
            raise CalcError(
                f"{what} redefines an existing symbol; each symbol may be "
                f"defined once (already defined: {_known(scope)})"
            )
        expr = parse_expression(formula.expr, scope, what=what)
        _require_known(expr, scope, what=what)
        value = evaluate_numeric(expr, scope, what=what)
        scope[formula.symbol] = value
        formula_rows.append(
            _row(
                formula.symbol,
                formula.expr,
                expression_mathml(expr),
                value,
                formula.unit,
                formula.ref,
                calc.precision,
            )
        )

    check_results: list[CheckResult] = []
    for check in calc.checks:
        what = f"check {check.expr!r}"
        expr = parse_expression(check.expr, scope, what=what)
        if not is_boolean(expr):
            raise CalcError(
                f"{what} is not a boolean; a check must be a relational or "
                f"boolean expression such as 'U < 100'"
            )
        _require_known(expr, scope, what=what)
        substituted = substitute(expr, {name: scope[name] for name in free_names(expr)})
        try:
            passed = bool(substituted)
        except TypeError as error:
            raise CalcError(
                f"{what} did not reduce to True/False (got {substituted})"
            ) from error
        markup = expression_mathml(expr)
        assert_plain_mathml(markup)
        utilisation, limit = _margin(check, expr, scope, what=what)
        check_results.append(
            CheckResult(
                expr=check.expr,
                expr_mathml=markup,
                description=check.description,
                substituted=(
                    f"{_substituted_text(check.expr, scope, calc.precision)} = {passed}"
                ),
                passed=passed,
                utilisation=utilisation,
                limit=limit,
            )
        )

    return Result(
        title=calc.title,
        as_of=calc.as_of,
        precision=calc.precision,
        inputs=tuple(input_rows),
        formulas=tuple(formula_rows),
        checks=tuple(check_results),
        values=dict(scope),
        passed=all(check.passed for check in check_results),
        governing=_governing(check_results),
    )
