"""Literal + call rendering shared by both source emitters (ADR 0020).

A calc literal is line-oriented (``formulas``/``lines`` hold one entry per
line), but ``repr()`` of a multi-line string is a single physical line of
escaped ``\\n``s. ADR 0020 D1 fixes the emitted spelling as **parenthesized
implicit string concatenation**: one ``repr()``-escaped fragment per value line,
each carrying its own ``'\\n'``::

    formulas=(
        'r = F_max / C_min  # demand / capacity\\n'
        'U = 100 * r [%]  # utilisation'
    ),

The value is exact by construction — code indentation is code, never content —
and the group is still a single ``ast.Constant`` (CPython concatenates adjacent
string literals at parse time), so the parse side needs no change at all.

Used by :mod:`engine.composite` (the bijective round-trip surface) and by
:mod:`engine.emit` (the derived ``to_python`` script), so both spell a
multi-line value the same way.
"""

from __future__ import annotations

__all__ = ["INDENT", "is_block_value", "render_literal", "render_call"]

INDENT = "    "


def is_block_value(value: object) -> bool:
    """Does ``value`` take the D1 block form?

    Value-driven and exact (ADR 0020 D2): a ``str`` containing a newline, and
    nothing else — no widget metadata, no length heuristic. Because the
    predicate is a pure function of the value, re-emitting the same value always
    yields the same bytes and the representation cannot oscillate on its own.
    """
    return isinstance(value, str) and "\n" in value


def _fragments(value: str) -> list[str]:
    """Split ``value`` into the physical fragments of its block form.

    Every fragment except the last carries its ``'\\n'`` back; a trailing empty
    last fragment (the value ends with a newline) is dropped — the preceding
    fragment's ``'\\n'`` already encodes it. Splitting on ``'\\n'`` only means a
    ``\\r`` stays visibly escaped inside its fragment (D1/OQ4): nothing is
    normalized, so ``''.join(fragments) == value`` always holds.
    """
    parts = value.split("\n")
    fragments = [part + "\n" for part in parts[:-1]]
    if parts[-1] != "":
        fragments.append(parts[-1])
    return fragments


def render_literal(value: object, indent: str) -> str:
    """Render a widget literal, block form for a multi-line ``str``.

    ``indent`` is the column the *argument* sits at; fragments are one level
    deeper and the closing paren lines up with the argument. Everything that is
    not a multi-line ``str`` — including containers holding one (D2 scope note)
    — keeps plain ``repr()``.
    """
    if not is_block_value(value):
        return repr(value)
    assert isinstance(value, str)
    inner = indent + INDENT
    body = "\n".join(f"{inner}{fragment!r}" for fragment in _fragments(value))
    return f"(\n{body}\n{indent})"


def render_call(call: str, args: list[str], indent: str) -> str:
    """``call(a, b)`` — expanded to one argument per line when any is block form.

    ADR 0020 D3: a statement with at least one block-form literal becomes an
    expanded call (trailing comma, closing paren at the statement's indent); a
    statement without one keeps today's single-line form byte-identically.
    """
    if not any("\n" in arg for arg in args):
        return f"{call}({', '.join(args)})"
    inner = indent + INDENT
    lines = [f"{call}("]
    lines += [f"{inner}{arg}," for arg in args]
    lines.append(f"{indent})")
    return "\n".join(lines)
