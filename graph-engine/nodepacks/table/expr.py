"""The constrained expression grammar for ``filter``/``derive`` (ADR 0005 C-D1).

A closed subset of Python expression syntax over column names, parsed with
stdlib :mod:`ast` and validated by a whitelist walker *before* anything is
ever evaluated — never ``eval()`` of arbitrary text.

**Allowed:**

* arithmetic ``+ - * / % **``, unary ``-``;
* comparisons ``== != < <= > >=`` (including chained comparisons);
* boolean ``and or not``;
* names — must be an existing column of the table the expression runs
  against;
* ``int``/``float``/``str``/``bool`` constants;
* calls to exactly ``abs``, ``round``, ``min``, ``max`` (positional args
  only — no ``**kwargs``, no ``*args``).

**Rejected** (``UserError`` naming the offending construct): attribute
access, subscripts (beyond the whitelist above — there is no column
subscript syntax, columns are plain names), lambdas, comprehensions,
f-strings, unknown names, calls to anything outside the fixed four,
``None``/bytes/complex literals, walrus assignment, ternaries, imports —
i.e. everything not explicitly listed above.

The expression **text** is the bijective literal (same status as the recipe
dict itself, and the sym expression string in ADR 0005 Part B): it round-trips
character-for-character through the graph/composite literal, and is
*deliberately* not Excel formula syntax — a small grammar we fully own.
"""

from __future__ import annotations

import ast
from typing import Any, Callable

from engine import UserError

# The fixed, closed function whitelist (ADR 0005 C-D1). Adding a function is a
# deliberate, versioned change to this grammar — not a runtime option.
ALLOWED_FUNCS: dict[str, Callable[..., Any]] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
}

_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow)
_ALLOWED_BOOLOPS = (ast.And, ast.Or)
_ALLOWED_CMPOPS = (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)
_ALLOWED_UNARYOPS = (ast.USub, ast.Not)
_LITERAL_TYPES = (bool, int, float, str)  # bool checked before int (bool <: int)


def _op_name(op: ast.AST) -> str:
    return type(op).__name__


def _check(node: ast.AST, columns: frozenset[str]) -> None:
    """Whitelist-walk one AST node; raise :class:`UserError` on anything else.

    Default-deny: any node type not explicitly handled below falls through to
    the final ``else`` and is rejected by name, so a new/unknown ast node kind
    (a future Python grammar addition, a construct we simply didn't list) is
    refused rather than silently allowed.
    """
    if isinstance(node, ast.Expression):
        _check(node.body, columns)
    elif isinstance(node, ast.Constant):
        value = node.value
        if not isinstance(value, _LITERAL_TYPES):
            raise UserError(
                f"unsupported literal {value!r} in expression "
                "(only int/float/str/bool constants are allowed)"
            )
    elif isinstance(node, ast.Name):
        if node.id not in columns:
            raise UserError(
                f"unknown name {node.id!r} in expression; "
                f"available columns: {sorted(columns)}"
            )
    elif isinstance(node, ast.BinOp):
        if not isinstance(node.op, _ALLOWED_BINOPS):
            raise UserError(
                f"unsupported operator {_op_name(node.op)} in expression "
                "(allowed: + - * / % **)"
            )
        _check(node.left, columns)
        _check(node.right, columns)
    elif isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, _ALLOWED_UNARYOPS):
            raise UserError(
                f"unsupported unary operator {_op_name(node.op)} in expression "
                "(allowed: unary -, not)"
            )
        _check(node.operand, columns)
    elif isinstance(node, ast.BoolOp):
        if not isinstance(node.op, _ALLOWED_BOOLOPS):
            raise UserError(f"unsupported boolean operator {_op_name(node.op)}")
        for value in node.values:
            _check(value, columns)
    elif isinstance(node, ast.Compare):
        _check(node.left, columns)
        for op, comparator in zip(node.ops, node.comparators):
            if not isinstance(op, _ALLOWED_CMPOPS):
                raise UserError(
                    f"unsupported comparison operator {_op_name(op)} in expression "
                    "(allowed: == != < <= > >=)"
                )
            _check(comparator, columns)
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_FUNCS:
            called = getattr(node.func, "id", None) or _op_name(node.func)
            raise UserError(
                f"call to {called!r} is not supported in expressions; "
                f"allowed functions: {sorted(ALLOWED_FUNCS)}"
            )
        if node.keywords:
            raise UserError("keyword arguments are not supported in expression calls")
        for arg in node.args:
            if isinstance(arg, ast.Starred):
                raise UserError("*args is not supported in expression calls")
            _check(arg, columns)
    else:
        raise UserError(
            f"unsupported expression syntax: {_op_name(node)} is not allowed "
            "(attribute access, subscripts, comprehensions, lambdas, imports, "
            "f-strings, and ternaries are all rejected)"
        )


class CompiledExpr:
    """A validated expression, compiled once and callable per row.

    Evaluation runs with an empty ``__builtins__`` and a locals dict limited to
    the whitelisted functions plus the row's own columns — nothing else is
    reachable, so ``eval`` here is safe *because* :func:`compile_expr` already
    rejected every unsafe construct in the source text.
    """

    __slots__ = ("source", "_code")

    def __init__(self, source: str, tree: ast.Expression) -> None:
        self.source = source
        self._code = compile(tree, "<recipe-expr>", "eval")

    def __call__(self, row: dict) -> Any:
        try:
            return eval(self._code, {"__builtins__": {}}, {**ALLOWED_FUNCS, **row})  # noqa: S307
        except UserError:
            raise
        except Exception as exc:  # column present but value incompatible (e.g. str * str)
            raise UserError(f"error evaluating {self.source!r}: {exc}") from exc

    def __repr__(self) -> str:
        return f"CompiledExpr({self.source!r})"


def compile_expr(expr: str, columns: list[str]) -> CompiledExpr:
    """Parse, whitelist-validate, and compile ``expr`` against ``columns``.

    Raises :class:`UserError` for a syntax error, or for any construct outside
    the grammar documented at module level.
    """
    if not isinstance(expr, str) or not expr.strip():
        raise UserError("expression must be a non-empty string")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise UserError(f"invalid expression syntax {expr!r}: {exc.msg}") from exc
    _check(tree, frozenset(columns))
    return CompiledExpr(expr, tree)
