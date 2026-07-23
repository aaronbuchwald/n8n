"""``mint_node_id`` — name a palette-created node so its source stays valid.

A drop from the palette (ADR 0011 HD4) has to invent a node id. That id becomes
the **variable name** the node is assigned to in the ``@main`` composite body
(ADR 0004 D3), so it must be:

* a valid Python identifier (never a digit-leading name or a keyword), and
* free of every collision that :func:`engine.composite.wiring_lines` would reject
  or that would silently mis-bind the emitted source.

The scheme (HD4): snake_case of the spec's short name, deduped with a numeric
suffix — first ``total``, then ``total_2``, ``total_3`` (matching the
``_aliases`` suffix style). Non-identifier characters are sanitised; a name that
would start with a digit or collide with a keyword is prefixed ``n_``.

The collision set has **four** classes, all of which must be avoided:

1. existing node ids (two nodes can't share a variable name),
2. the module's local **call names** (``composite_call_names``) — a node id equal
   to a called function shadows it: ``total = total(vals)`` reads the unbound
   local, the exact case ``wiring_lines`` refuses,
3. the composite's **parameter names** — same shadowing hazard against the
   function's own arguments,
4. **builtins referenced in the composite body** — shadowing one there breaks
   the wiring the same way.

Because classes 2–4 live in the *module*, not the graph, minting is
module-aware: :func:`module_collision_set` builds the set from the authoring
module's source, and :func:`mint_node_id` mints against it. That is what makes
this a server-assisted operation (ADR 0011 HD4) — the endpoint wiring is W3;
this is only the engine primitive.
"""

from __future__ import annotations

import ast
import builtins
import keyword
import re
from typing import Iterable

from .composite import composite_call_names, find_composite

__all__ = ["mint_node_id", "module_collision_set"]

_BUILTIN_NAMES = frozenset(dir(builtins))
_NON_IDENT = re.compile(r"\W")
# camelCase / PascalCase word boundaries, so ``ReadValues`` -> ``read_values``.
_CAMEL_TAIL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_CAMEL_ACRONYM = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")


def _snake(short_name: str) -> str:
    """Best-effort snake_case of a spec short name (HD4).

    Splits camel/Pascal boundaries, lowercases, and maps every non-identifier
    character to ``_``; runs of underscores collapse and edges are trimmed. The
    result may still be empty or digit-leading — :func:`_valid_identifier`
    finishes the job.
    """
    text = short_name.strip()
    text = _CAMEL_ACRONYM.sub("_", text)
    text = _CAMEL_TAIL.sub("_", text)
    text = _NON_IDENT.sub("_", text.lower())
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def _valid_identifier(base: str) -> str:
    """Coerce ``base`` into a legal, non-keyword Python identifier.

    Empty falls back to ``node``; a digit-leading or keyword name is prefixed
    ``n_`` (mirrors ``engine.emit._var``), so the minted id is always usable as a
    bare variable in the composite body.
    """
    if not base:
        base = "node"
    if base[0].isdigit() or keyword.iskeyword(base):
        base = f"n_{base}"
    return base


def mint_node_id(short_name: str, taken: Iterable[str] = ()) -> str:
    """Mint a collision-free node id from a spec's ``short_name``.

    ``taken`` is the collision set — pass :func:`module_collision_set` (or any
    iterable) so all four HD4 classes are dodged. Returns the sanitised
    snake_case name, or that name with a ``_2``/``_3``/… suffix when it is
    already taken. Always a valid, non-keyword Python identifier.
    """
    taken = set(taken)
    base = _valid_identifier(_snake(short_name))
    if base not in taken:
        return base
    n = 1
    candidate = base
    while candidate in taken:
        n += 1
        candidate = f"{base}_{n}"
    return candidate


def _composite_param_names(composite: ast.FunctionDef) -> set[str]:
    """Every parameter name of the composite (all kinds, plus *args/**kwargs)."""
    args = composite.args
    names = {
        a.arg
        for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)
    }
    if args.vararg is not None:
        names.add(args.vararg.arg)
    if args.kwarg is not None:
        names.add(args.kwarg.arg)
    return names


def _composite_target_ids(composite: ast.FunctionDef) -> set[str]:
    """Assignment targets in the composite body — the existing node ids in source."""
    ids: set[str] = set()
    for stmt in composite.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    ids.add(target.id)
    return ids


def _referenced_builtins(composite: ast.FunctionDef) -> set[str]:
    """Builtins referenced by name in the composite body (HD4 class 4)."""
    return {
        node.id
        for node in ast.walk(composite)
        if isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Load)
        and node.id in _BUILTIN_NAMES
    }


def module_collision_set(
    source: str,
    module_name: str,
    *,
    node_ids: Iterable[str] = (),
    extra: Iterable[str] = (),
) -> set[str]:
    """Build the HD4 collision set from an authoring module's ``source``.

    The union of all four classes a minted id must avoid: ``node_ids`` (the
    current graph's ids) and the composite's own assignment targets; the module's
    local call names (:func:`composite_call_names` — imports + local ``@node``
    defs); the composite's parameter names; and builtins referenced in the
    composite body. ``extra`` lets a caller reserve additional names the source
    doesn't yet show — e.g. the call name a not-yet-imported dropped type will be
    wired under, so its id never shadows its own future import.

    Pass the result to :func:`mint_node_id`. Raises the same errors as
    :func:`engine.composite.find_composite` when ``source`` has no single
    composite.
    """
    tree = ast.parse(source)
    composite = find_composite(tree)
    names: set[str] = set(node_ids)
    names.update(extra)
    names.update(composite_call_names(tree, module_name).values())
    names.update(_composite_target_ids(composite))
    names.update(_composite_param_names(composite))
    names.update(_referenced_builtins(composite))
    return names
