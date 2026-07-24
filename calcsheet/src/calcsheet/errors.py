"""The one exception type this package raises."""

from __future__ import annotations


class CalcError(Exception):
    """A calc is malformed or cannot be evaluated.

    Every failure mode — unknown symbol, duplicate symbol, unparseable
    expression, a check that isn't boolean, unsafe markup — surfaces as this
    single type, always with a message naming the offending symbol or
    expression (and, where it helps, the names that *are* available).
    """
