"""Result <-> a plain JSON dict: the archival form of a completed calculation.

A rendered card is one *view* of a result; this is the result itself, in a
shape ``json.dumps`` accepts and a future version of this package can still
read. The payload is versioned (``{"calcsheet_result": 1, ...}``) so a reader
can refuse what it does not understand instead of guessing, and the round trip
is lossless — ``Result.from_dict(r.to_dict()) == r``.

Nothing here recomputes anything: fields are copied, not re-derived. Lives in
its own module and is reached through :meth:`Result.to_dict`, so ``evaluate``
stays about evaluating.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from .errors import CalcError

if TYPE_CHECKING:  # avoid a serialize <-> evaluate import cycle at runtime
    from .evaluate import CheckResult, Result, Row

# The version key doubles as the "is this ours?" marker: a dict without it is
# not a calcsheet result, whatever else it contains.
RESULT_SCHEMA_KEY = "calcsheet_result"
RESULT_SCHEMA_VERSION = 1


def _text(value: object, *, what: str) -> str:
    if not isinstance(value, str):
        raise CalcError(f"{what} must be a string, got {value!r}")
    return value


def _number(value: object, *, what: str) -> float:
    # bool is an int subclass, and a verdict is not a quantity.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CalcError(f"{what} must be a number, got {value!r}")
    return float(value)


def _whole(value: object, *, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CalcError(f"{what} must be a whole number, got {value!r}")
    return value


def _flag(value: object, *, what: str) -> bool:
    if not isinstance(value, bool):
        raise CalcError(f"{what} must be true or false, got {value!r}")
    return value


def _mapping(value: object, *, what: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise CalcError(f"{what} must be an object, got {value!r}")
    return value


def _sequence(value: object, *, what: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise CalcError(f"{what} must be a list, got {value!r}")
    return value


def _field(data: Mapping[str, object], key: str, *, what: str) -> object:
    if key not in data:
        raise CalcError(f"{what} is missing the key {key!r}")
    return data[key]


def _row_to_dict(row: Row) -> dict[str, object]:
    return {
        "symbol": row.symbol,
        "symbol_mathml": row.symbol_mathml,
        "definition": row.definition,
        "definition_mathml": row.definition_mathml,
        "value": row.value,
        "value_text": row.value_text,
        "unit": row.unit,
        "ref": row.ref,
    }


def _row_from_dict(data: object, *, what: str) -> Row:
    from .evaluate import Row

    row = _mapping(data, what=what)
    return Row(
        symbol=_text(_field(row, "symbol", what=what), what=f"{what} symbol"),
        symbol_mathml=_text(
            _field(row, "symbol_mathml", what=what), what=f"{what} symbol_mathml"
        ),
        definition=_text(
            _field(row, "definition", what=what), what=f"{what} definition"
        ),
        definition_mathml=_text(
            _field(row, "definition_mathml", what=what),
            what=f"{what} definition_mathml",
        ),
        value=_number(_field(row, "value", what=what), what=f"{what} value"),
        value_text=_text(
            _field(row, "value_text", what=what), what=f"{what} value_text"
        ),
        unit=_text(_field(row, "unit", what=what), what=f"{what} unit"),
        ref=_text(_field(row, "ref", what=what), what=f"{what} ref"),
    )


def _check_to_dict(check: CheckResult) -> dict[str, object]:
    return {
        "expr": check.expr,
        "expr_mathml": check.expr_mathml,
        "description": check.description,
        "substituted": check.substituted,
        "passed": check.passed,
    }


def _check_from_dict(data: object, *, what: str) -> CheckResult:
    from .evaluate import CheckResult

    check = _mapping(data, what=what)
    return CheckResult(
        expr=_text(_field(check, "expr", what=what), what=f"{what} expr"),
        expr_mathml=_text(
            _field(check, "expr_mathml", what=what), what=f"{what} expr_mathml"
        ),
        description=_text(
            _field(check, "description", what=what), what=f"{what} description"
        ),
        substituted=_text(
            _field(check, "substituted", what=what), what=f"{what} substituted"
        ),
        passed=_flag(_field(check, "passed", what=what), what=f"{what} passed"),
    )


def result_to_dict(result: Result) -> dict[str, object]:
    """The versioned, ``json.dumps``-able form of a :class:`Result`."""
    return {
        RESULT_SCHEMA_KEY: RESULT_SCHEMA_VERSION,
        "title": result.title,
        "as_of": result.as_of,
        "precision": result.precision,
        "inputs": [_row_to_dict(row) for row in result.inputs],
        "formulas": [_row_to_dict(row) for row in result.formulas],
        "checks": [_check_to_dict(check) for check in result.checks],
        "values": dict(result.values),
        "passed": result.passed,
    }


def result_from_dict(data: Mapping[str, object]) -> Result:
    """Rebuild a :class:`Result` from :func:`result_to_dict`'s output."""
    from .evaluate import Result

    what = "calcsheet result"
    payload = _mapping(data, what=what)
    version = _field(payload, RESULT_SCHEMA_KEY, what=what)
    if version != RESULT_SCHEMA_VERSION:
        raise CalcError(
            f"{what} has schema version {version!r}; this calcsheet reads "
            f"version {RESULT_SCHEMA_VERSION}"
        )

    values = _mapping(_field(payload, "values", what=what), what=f"{what} values")
    return Result(
        title=_text(_field(payload, "title", what=what), what=f"{what} title"),
        as_of=_text(_field(payload, "as_of", what=what), what=f"{what} as_of"),
        precision=_whole(
            _field(payload, "precision", what=what), what=f"{what} precision"
        ),
        inputs=tuple(
            _row_from_dict(row, what=f"{what} input row")
            for row in _sequence(_field(payload, "inputs", what=what), what=what)
        ),
        formulas=tuple(
            _row_from_dict(row, what=f"{what} formula row")
            for row in _sequence(_field(payload, "formulas", what=what), what=what)
        ),
        checks=tuple(
            _check_from_dict(check, what=f"{what} check")
            for check in _sequence(_field(payload, "checks", what=what), what=what)
        ),
        values={
            name: _number(value, what=f"{what} value {name!r}")
            for name, value in values.items()
        },
        passed=_flag(_field(payload, "passed", what=what), what=f"{what} passed"),
    )
