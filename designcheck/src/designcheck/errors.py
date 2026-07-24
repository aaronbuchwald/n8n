"""The one exception type this package raises."""

from __future__ import annotations


class DesignCheckError(Exception):
    """A domain value, a knowledge-base entry or a resolution is malformed.

    Every failure mode — an invalid member, a KB entry that is missing or
    carries a wrong dimension, an unknown applicability predicate, a clause
    cycle, an unbindable symbol — surfaces as this single type, always naming
    the offending entry, clause or symbol. Mirrors ``calcsheet.CalcError``:
    one type, messages that say what to fix.
    """
