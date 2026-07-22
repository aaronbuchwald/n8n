"""Targeted wiring write-back — patch only the composite statements that changed.

ADR 0004 D5 fixes the ``graph → code`` direction as *rewrite the wiring lines
only*. Historically :meth:`server.workspace.Workspace.save_graph` honoured that
at the level of the whole ``@main`` body: it regenerated **every** wiring line
from the graph and spliced them over the composite's body span. Correct as a
projection, but it normalized away every hand-written comment, blank line and
multi-line literal in the body — a single title edit collapsed 34 hand-written
lines to 12 generated ones (review 0005, finding #5). For a tool whose promise
is "the graph edits your source", silently eating a user's comments on the first
chip edit is real data loss.

This module narrows the rewrite to the **statement** level:

* **Value / edge edit (the common case).** When the graph's node *set* matches
  the module's composite — a widget literal changed, an edge was rewired, the
  output moved — only the individual assignment statements whose value actually
  differs are re-emitted (one canonical line each), spliced in place by AST line
  span. Every other statement, and all the comments / blank lines / multi-line
  literals **between** statements, survive byte-for-byte. Statements are compared
  by *parsed meaning* (``from_composite``), not text, so re-quoting or
  reformatting a literal that means the same value is a no-op.

* **Structural change (fallback).** When nodes were added or removed, or the
  return appeared/disappeared, in-place patching can't place the new lines
  without guessing where comments belong, so we fall back to regenerating the
  whole wiring block (the normalized projection ADR 0004 D5 permits) and *report*
  whether that block held comments/blank lines, so the caller can warn instead of
  eating them silently.

Stdlib only: ``ast`` line spans + text splicing, no CST dependency.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from typing import Optional

from engine import (
    Graph,
    NodeRegistry,
    bind,
    composite_call_names,
    find_composite,
    from_composite,
    wiring_lines,
)


@dataclass
class WritebackResult:
    """The outcome of computing a wiring write-back.

    ``text`` is the module source to persist (equal to the input when nothing
    changed — the caller can skip the write). ``strategy`` is one of
    ``"patched"`` (statement-level in-place edit), ``"regenerated"`` (whole-block
    fallback) or ``"unchanged"``. ``dropped_comments`` is only meaningful for the
    fallback: ``True`` when the regenerated block contained comments/blank lines
    that the normalized projection did not carry over.
    """

    text: str
    strategy: str
    changed_ids: list[str] = field(default_factory=list)
    dropped_comments: bool = False
    reason: Optional[str] = None


# ----------------------------------------------------------------------
# text splicing (kept local so this module has no back-dependency on
# workspace.py, which imports it)
# ----------------------------------------------------------------------


def _splice_lines(text: str, start: int, end: int, replacement: list[str]) -> str:
    """Replace 1-based inclusive line range ``start..end`` with ``replacement``.

    Everything outside the range is preserved byte-for-byte.
    """
    lines = text.splitlines(keepends=True)
    new_block = [line if line.endswith("\n") else line + "\n" for line in replacement]
    return "".join(lines[: start - 1] + new_block + lines[end:])


# ----------------------------------------------------------------------
# composite-body statement model
# ----------------------------------------------------------------------


@dataclass
class _Stmt:
    """One wiring statement's 1-based inclusive line span."""

    start: int
    end: int
    node_id: Optional[str] = None  # None for the ``return`` statement
    is_return: bool = False


def _has_docstring(body: list[ast.stmt]) -> bool:
    return bool(body) and (
        isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    )


def _wiring_statements(composite: ast.FunctionDef) -> Optional[list[_Stmt]]:
    """The composite's wiring statements, or ``None`` when the body is not the

    pure ``target = call(...)`` + ``return`` shape the in-place patch understands
    (anything else falls back to whole-block regeneration).
    """
    body = list(composite.body)
    if _has_docstring(body):
        body = body[1:]

    stmts: list[_Stmt] = []
    for st in body:
        if isinstance(st, ast.Pass):
            continue
        if (
            isinstance(st, ast.Assign)
            and len(st.targets) == 1
            and isinstance(st.targets[0], ast.Name)
        ):
            stmts.append(
                _Stmt(st.lineno, st.end_lineno or st.lineno, node_id=st.targets[0].id)
            )
        elif isinstance(st, ast.Return):
            stmts.append(_Stmt(st.lineno, st.end_lineno or st.lineno, is_return=True))
        else:
            return None  # unexpected statement kind → give up on in-place patch
    return stmts


def _wiring_span(composite: ast.FunctionDef) -> Optional[tuple[int, int]]:
    """The 1-based inclusive span of the whole wiring block (docstring excluded)."""
    body = list(composite.body)
    wiring = body[1:] if _has_docstring(body) else body
    if not wiring:
        return None
    return wiring[0].lineno, max(s.end_lineno or s.lineno for s in wiring)


def _indent_of(composite: ast.FunctionDef) -> str:
    body = list(composite.body)
    wiring = body[1:] if _has_docstring(body) else body
    col = wiring[0].col_offset if wiring else composite.col_offset + 4
    return " " * col


def _block_has_comments_or_blanks(text: str, start: int, end: int) -> bool:
    """Does the 1-based inclusive span hold a comment or blank line?"""
    for line in text.splitlines()[start - 1 : end]:
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#"):
            return True
    return False


def _signature(graph: Graph, node_id: str) -> tuple:
    """A node's wiring identity: type, widget literals, and incoming edges.

    Two nodes with equal signatures emit a byte-identical assignment line, so a
    changed signature is exactly when a statement needs re-emitting. Comparing
    parsed meaning (not source text) means a re-quoted or reformatted literal
    that denotes the same value is *not* treated as a change.
    """
    node = graph.node(node_id)
    edges = tuple(
        sorted(
            (e.target_input, e.source, e.source_output)
            for e in graph.incoming(node_id)
        )
    )
    literals = json.dumps(node.inputs, sort_keys=True, default=repr)
    return (node.type, literals, edges)


# ----------------------------------------------------------------------
# the write-back planner
# ----------------------------------------------------------------------


def compute_writeback(
    text: str,
    graph: Graph,
    registry: NodeRegistry,
    module_name: str,
) -> WritebackResult:
    """Plan the module rewrite for saving ``graph`` back to its authoring module.

    Emits fresh wiring lines from ``graph`` and decides, per statement, whether
    to splice a changed line in place (preserving surrounding comments and
    formatting) or — for a structural change — regenerate the whole block. Raises
    :class:`engine.EngineError` for a graph that cannot be wired in place (a node
    id shadowing its function, a type the module neither imports nor defines);
    the caller surfaces that as a 422 with the file untouched.
    """
    tree = ast.parse(text)
    composite = find_composite(tree)
    call_names = composite_call_names(tree, module_name)
    indent = _indent_of(composite)

    # Bind once; emit from the bound graph so line order matches node order.
    bound = bind(graph, registry)
    emitted = wiring_lines(bound, registry, call_names=call_names, indent=indent)
    n_nodes = len(bound.nodes)
    line_by_id = {bound.nodes[i].id: emitted[i] for i in range(n_nodes)}
    return_line = emitted[n_nodes] if bound.output is not None else None

    stmts = _wiring_statements(composite)
    graph_ids = {node.id for node in graph.nodes}

    def _regenerate() -> WritebackResult:
        span = _wiring_span(composite)
        if span is None:
            # Docstring-only / empty body → insert after the docstring (or the
            # def line for a truly empty body), matching the original behaviour.
            body = list(composite.body)
            if _has_docstring(body):
                insert_at = (body[0].end_lineno or body[0].lineno) + 1
            else:
                insert_at = composite.lineno + 1
            new_text = _splice_lines(text, insert_at, insert_at - 1, emitted)
            return WritebackResult(
                text=new_text,
                strategy="regenerated",
                dropped_comments=False,
                reason="empty composite body",
            )
        start, end = span
        dropped = _block_has_comments_or_blanks(text, start, end)
        new_text = _splice_lines(text, start, end, emitted)
        return WritebackResult(
            text=new_text,
            strategy="regenerated",
            dropped_comments=dropped,
            reason="node set or return presence changed",
        )

    if stmts is None:
        return _regenerate()

    assign_stmts = [s for s in stmts if not s.is_return]
    return_stmts = [s for s in stmts if s.is_return]
    file_ids = [s.node_id for s in assign_stmts]

    structural_change = (
        set(file_ids) != graph_ids
        or len(file_ids) != len(set(file_ids))
        or len(return_stmts) > 1
        or (len(return_stmts) == 1) != (bound.output is not None)
    )
    if structural_change:
        return _regenerate()

    # In-place patch: re-emit only the statements whose meaning changed.
    current = from_composite(text, registry, module_name=module_name)
    edits: list[tuple[int, int, list[str]]] = []
    changed: list[str] = []

    for s in assign_stmts:
        assert s.node_id is not None
        if _signature(current, s.node_id) != _signature(graph, s.node_id):
            edits.append((s.start, s.end, [line_by_id[s.node_id]]))
            changed.append(s.node_id)

    if return_stmts and current.output != graph.output and return_line is not None:
        rs = return_stmts[0]
        edits.append((rs.start, rs.end, [return_line]))
        changed.append("<return>")

    if not edits:
        return WritebackResult(text=text, strategy="unchanged")

    # Apply bottom-up so earlier spans keep their line numbers.
    new_text = text
    for start, end, replacement in sorted(edits, key=lambda e: e[0], reverse=True):
        new_text = _splice_lines(new_text, start, end, replacement)
    return WritebackResult(text=new_text, strategy="patched", changed_ids=changed)
