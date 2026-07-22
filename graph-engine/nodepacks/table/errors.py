"""``UserError`` — bad recipe/expression input from the *user*, not a code bug.

``engine.errors`` doesn't define a dedicated "this is the user's fault" error
yet (that seam is Stream A's territory per ADR 0005 Part A, not yet landed as
of this pack). ADR 0005 Part C nonetheless names the exception ``UserError``
throughout (unknown op/version, unsafe expression syntax, unknown column, ...),
so this small local class gives that exact name and behaviour now. It
subclasses :class:`engine.EngineError` so it is still catchable as an engine
error everywhere that already expects one; when/if ``engine`` grows its own
``UserError``, this can be re-pointed at it with no call-site changes.
"""

from __future__ import annotations

from engine import EngineError


class UserError(EngineError):
    """Raised for user-caused failures: bad recipe shape, unsafe expression
    syntax, unknown column/op/function, wrong version, etc. Never raised for
    engine/programming bugs."""
