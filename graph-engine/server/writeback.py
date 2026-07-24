"""Targeted wiring write-back — patch, insert, or delete only what changed.

ADR 0004 D5 fixes the ``graph → code`` direction as *rewrite the wiring lines
only*; Amendment A1 narrowed that to the **statement** level for value/edge
edits (patch only the assignment lines whose meaning changed, preserving every
surrounding comment). A1 explicitly punted **structural** edits — adding or
removing nodes — to "regenerate the whole wiring block + a logged warning",
eating hand-written comments in the block.

ADR 0011 HD2 makes structural edits the *common* case (whole-graph canvas
editing), so this module extends the planner to handle them in place, in order
of preference per edit:

1. **Pure insertion** (nodes added, none removed) — emit the new assignment
   line(s) and splice them in; **no existing line is touched**, so every comment
   survives. Each new node lands immediately after its deepest upstream
   dependency's assignment (before its first consumer / the ``return``);
   independent nodes go just before the ``return`` (or at block end).
2. **Pure deletion** — splice out exactly the removed statement's AST line span.
   Contiguous ``#`` comment lines *attached* directly above it (no blank line
   between) go with it; anything else stays, even if orphaned. Unattached prose
   is never silently deleted.
3. **Insertion + deletion in one save** (replace-node) — apply the deletes then
   the inserts; still no untouched line is rewritten.
4. **Reorder / anything the statement model can't express** — a rewire that would
   force existing statements out of dependency order, a body the statement model
   can't parse, or a duplicate target: fall back to A1's whole-block
   regeneration, but now **surface it in the save response** (a structured
   ``warning`` on :class:`WritebackResult`, which ``save_graph`` forwards) instead
   of only logging it — a canvas user will hit this path.
5. **Import-block management** — placing a node whose type the module neither
   imports nor defines inserts a ``from <pack> import <fn>`` line (aliased when
   the name would shadow a node id or another local, reusing the ADR 0004 alias
   collision logic). Deleting the last node of a type does **not** remove the
   import. Import edits touch only the import block, never the composite body.

Stdlib only: ``ast`` line spans + text splicing, no CST dependency. Reordering
with comment migration remains the one lossy case, now explicit and surfaced.

The planner (:func:`compute_writeback`) is pure — it takes the module text and a
graph and returns a :class:`WritebackResult` without touching the filesystem —
so a future id-scoped route (ADR 0011 W3) can call it the same way
``save_graph`` does.
"""

from __future__ import annotations

import ast
import json
from collections import defaultdict
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
    changed — the caller can skip the write). ``strategy`` is one of:

    * ``"unchanged"`` — the graph already matches the module.
    * ``"patched"`` — statement-level in-place value/edge edit (A1).
    * ``"inserted"`` — one or more nodes (and/or the ``return``) were spliced in
      without touching any existing line.
    * ``"deleted"`` — one or more nodes (and/or the ``return``) were spliced out.
    * ``"restructured"`` — a save that both inserted and deleted (e.g. replace
      a node) with no untouched line rewritten.
    * ``"regenerated"`` — the whole-block fallback (case 4).

    ``changed_ids`` / ``added_ids`` / ``removed_ids`` name the nodes each op
    touched; ``imported`` lists any ``from … import …`` lines added to make a
    freshly placed type callable. ``dropped_comments`` is only meaningful for the
    fallback: ``True`` when the regenerated block contained comments/blank lines
    the normalized projection did not carry over. ``warning`` is the structured,
    UI-surfacable signal for that lossy fallback (``None`` on every lossless
    path); ``save_graph`` forwards it into the PUT response so the normalization
    is never silent in the canvas.
    """

    text: str
    strategy: str
    changed_ids: list[str] = field(default_factory=list)
    added_ids: list[str] = field(default_factory=list)
    removed_ids: list[str] = field(default_factory=list)
    imported: list[str] = field(default_factory=list)
    dropped_comments: bool = False
    reason: Optional[str] = None
    warning: Optional[dict] = None


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


def _ensure_newlines(lines: list[str]) -> list[str]:
    return [line if line.endswith("\n") else line + "\n" for line in lines]


def _assemble(
    text: str,
    replacements: list[tuple[int, int, list[str]]],
    insertions: list[tuple[int, list[str]]],
) -> str:
    """Rebuild ``text`` applying span replacements and before-line insertions.

    A **replacement** ``(start, end, lines)`` swaps the 1-based inclusive line
    range ``start..end`` for ``lines`` (``[]`` deletes the range). An
    **insertion** ``(before, lines)`` emits ``lines`` immediately before original
    1-based line ``before`` (``before == N+1`` appends at end). Both address the
    *original* line numbers, so a caller composes the whole plan against one
    coordinate system; a single forward pass then applies everything, sidestepping
    the line-shift bookkeeping of iterative splicing. Untouched lines are copied
    byte-for-byte.
    """
    if not replacements and not insertions:
        return text

    lines = text.splitlines(keepends=True)
    total = len(lines)

    rep_by_start: dict[int, tuple[int, list[str]]] = {}
    for start, end, repl in replacements:
        rep_by_start[start] = (end, repl)
    ins_by_before: dict[int, list[str]] = defaultdict(list)
    for before, repl in insertions:
        ins_by_before[before].extend(repl)

    out: list[str] = []

    def _emit_insert(at: int) -> None:
        if at in ins_by_before:
            if out and not out[-1].endswith("\n"):
                out[-1] += "\n"
            out.extend(_ensure_newlines(ins_by_before[at]))

    i = 1
    while i <= total:
        _emit_insert(i)
        if i in rep_by_start:
            end, repl = rep_by_start[i]
            out.extend(_ensure_newlines(repl))
            i = end + 1
            continue
        out.append(lines[i - 1])
        i += 1
    _emit_insert(total + 1)
    return "".join(out)


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


def node_statement_span(
    composite: ast.FunctionDef, node_id: str
) -> Optional[tuple[int, int]]:
    """The 1-based inclusive line span of ``node_id``'s wiring statement, or ``None``.

    Reuses the statement model the in-place write-back planner uses to address
    each node's assignment (:func:`_wiring_statements`), so the read-only
    call-site route (ADR 0015 D2) locates a node's ``@main`` statement the exact
    same way a value edit's patch does. Falls back to a direct assignment scan
    when the body isn't the clean ``target = call(...)`` shape the patch model
    requires, so a lookup still resolves the span for the read-only view.
    """
    stmts = _wiring_statements(composite)
    if stmts is not None:
        for s in stmts:
            if s.node_id == node_id:
                return s.start, s.end
    for st in composite.body:
        if (
            isinstance(st, ast.Assign)
            and len(st.targets) == 1
            and isinstance(st.targets[0], ast.Name)
            and st.targets[0].id == node_id
        ):
            return st.lineno, st.end_lineno or st.lineno
    return None


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


def _attached_comment_start(text_lines: list[str], stmt_start: int) -> int:
    """First line of the ``#`` comment block directly above ``stmt_start``.

    Walks upward over contiguous comment lines with no blank line between them;
    stops at the first blank line or code (ADR 0011 HD2 §2 comment policy). When
    nothing is attached, returns ``stmt_start`` unchanged.
    """
    start = stmt_start
    i = stmt_start - 1
    while i >= 1 and text_lines[i - 1].strip().startswith("#"):
        start = i
        i -= 1
    return start


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
# import-block management (HD2 §5)
# ----------------------------------------------------------------------


def _composite_param_names(composite: ast.FunctionDef) -> set[str]:
    args = composite.args
    names = {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs}
    if args.vararg:
        names.add(args.vararg.arg)
    if args.kwarg:
        names.add(args.kwarg.arg)
    return names


def _plan_imports(
    tree: ast.Module,
    bound,
    call_names: dict[str, str],
    reserved: set[str],
) -> tuple[list[str], Optional[int], dict[str, str]]:
    """Import lines to add for node types the module can't yet call.

    Returns ``(import_lines, before_line, added_call_names)``. A type already in
    ``call_names`` (imported or locally defined) needs nothing. For a missing
    type the local call name is its ``qualname``, aliased to the first
    ``qualname_N`` that avoids ``reserved`` (existing locals ∪ node ids ∪
    composite params) so it never shadows a node-id variable — the same collision
    rule ``engine.composite._aliases`` applies when emitting a fresh module. New
    lines are appended after the module's last existing import; nothing else in
    the header moves.
    """
    used: dict[str, dict] = {}
    for node in bound.nodes:
        used.setdefault(node.type, node.spec)
    missing = [(t, s) for t, s in used.items() if t not in call_names]
    if not missing:
        return [], None, {}

    taken = set(reserved)
    added: dict[str, str] = {}
    lines: list[str] = []
    for type_id, spec in missing:
        base = spec["qualname"]
        alias, n = base, 1
        while alias in taken:
            n += 1
            alias = f"{base}_{n}"
        taken.add(alias)
        added[type_id] = alias
        suffix = "" if alias == base else f" as {alias}"
        lines.append(f"from {spec['module']} import {base}{suffix}")

    import_ends = [
        s.end_lineno or s.lineno
        for s in tree.body
        if isinstance(s, (ast.Import, ast.ImportFrom))
    ]
    before = (max(import_ends) + 1) if import_ends else find_composite(tree).lineno
    return lines, before, added


# ----------------------------------------------------------------------
# the in-place body planner (patch / insert / delete)
# ----------------------------------------------------------------------


@dataclass
class _BodyPlan:
    replacements: list[tuple[int, int, list[str]]]
    insertions: list[tuple[int, list[str]]]
    strategy: str
    changed_ids: list[str]
    added_ids: list[str]
    removed_ids: list[str]


def _plan_body(
    text: str,
    composite: ast.FunctionDef,
    bound,
    graph: Graph,
    registry: NodeRegistry,
    module_name: str,
    line_by_id: dict[str, str],
    return_line: Optional[str],
) -> Optional[_BodyPlan]:
    """Plan the body edits in place, or ``None`` to signal the block-regen fallback.

    Handles value/edge patches, node insertions and deletions (and the
    appearance/disappearance of the ``return``) as line-span edits against the
    original text. Returns ``None`` — deferring to whole-block regeneration — when
    the body isn't the simple assignment/return shape, has a duplicate target, is
    empty, or when the requested wiring would force existing statements out of
    dependency order (a reorder the in-place model can't express).
    """
    stmts = _wiring_statements(composite)
    if stmts is None:
        return None
    span = _wiring_span(composite)
    if span is None:
        return None  # empty body → regenerate inserts the whole block
    block_start, block_end = span

    assign_stmts = [s for s in stmts if not s.is_return]
    return_stmt = next((s for s in stmts if s.is_return), None)

    file_ids = [s.node_id for s in assign_stmts]
    if len(file_ids) != len(set(file_ids)):
        return None  # duplicate targets → not a clean statement model

    graph_ids = {n.id for n in graph.nodes}
    survivor_stmts = [s for s in assign_stmts if s.node_id in graph_ids]
    removed_stmts = [s for s in assign_stmts if s.node_id not in graph_ids]
    file_id_set = set(file_ids)
    added_ids = [n.id for n in bound.nodes if n.id not in file_id_set]

    text_lines = text.splitlines()
    replacements: list[tuple[int, int, list[str]]] = []
    changed: list[str] = []
    removed: list[str] = [s.node_id for s in removed_stmts if s.node_id]

    # --- deletions: statement span + its attached leading comments ---------
    for s in removed_stmts:
        cstart = _attached_comment_start(text_lines, s.start)
        replacements.append((cstart, s.end, []))

    # --- patches: survivors whose parsed meaning changed -------------------
    current = from_composite(text, registry, module_name=module_name)
    for s in survivor_stmts:
        assert s.node_id is not None
        if _signature(current, s.node_id) != _signature(graph, s.node_id):
            replacements.append((s.start, s.end, [line_by_id[s.node_id]]))
            changed.append(s.node_id)

    # --- return handling ---------------------------------------------------
    graph_has_output = bound.output is not None
    return_deleted = False
    return_inserted = False
    if return_stmt is not None and not graph_has_output:
        cstart = _attached_comment_start(text_lines, return_stmt.start)
        replacements.append((cstart, return_stmt.end, []))
        return_deleted = True
    elif return_stmt is not None and graph_has_output:
        if current.output != graph.output and return_line is not None:
            replacements.append((return_stmt.start, return_stmt.end, [return_line]))
            changed.append("<return>")
    elif return_stmt is None and graph_has_output and return_line is not None:
        return_inserted = True

    # --- insertions: added nodes, each after its deepest dependency ---------
    survivor_end = {s.node_id: s.end for s in survivor_stmts}
    return_at = return_stmt.start if return_stmt is not None else None
    placed_after: dict[str, int] = {}
    insert_entries: list[tuple[int, int, str, str]] = []  # (before, seq, id, line)
    seq = 0
    for nid in added_ids:
        deps = [e.source for e in graph.incoming(nid)]
        candidates = [
            survivor_end[d] if d in survivor_end else placed_after[d]
            for d in deps
            if d in survivor_end or d in placed_after
        ]
        if candidates:
            after = max(candidates)
            before = after + 1
            placed_after[nid] = after
        elif return_at is not None:
            before = return_at
            placed_after[nid] = before - 1
        else:
            before = block_end + 1
            placed_after[nid] = block_end
        insert_entries.append((before, seq, nid, line_by_id[nid]))
        seq += 1

    if return_inserted:
        assert return_line is not None
        insert_entries.append((block_end + 1, seq, "<return>", return_line))
        seq += 1

    # --- reject an insertion that would land inside a deleted/replaced span --
    for before, _seq, _nid, _line in insert_entries:
        for start, end, repl in replacements:
            if not repl and start < before <= end:
                return None  # regenerate instead of swallowing the inserted line

    # --- validate the resulting body is still a valid dependency order -----
    order = _projected_order(survivor_stmts, insert_entries)
    if not _is_topological(order, graph):
        return None  # reorder needed → fallback (surfaced by the caller)

    insertions = _group_insertions(insert_entries)

    inserted_any = bool(added_ids) or return_inserted
    removed_any = bool(removed_stmts) or return_deleted
    if inserted_any and removed_any:
        strategy = "restructured"
    elif inserted_any:
        strategy = "inserted"
    elif removed_any:
        strategy = "deleted"
    elif changed:
        strategy = "patched"
    else:
        strategy = "unchanged"

    return _BodyPlan(
        replacements=replacements,
        insertions=insertions,
        strategy=strategy,
        changed_ids=changed,
        added_ids=list(added_ids),
        removed_ids=removed,
    )


def _projected_order(
    survivor_stmts: list[_Stmt],
    insert_entries: list[tuple[int, int, str, str]],
) -> list[str]:
    """The node-id order the assembler will produce (survivors + insertions)."""
    events: list[tuple[int, int, int, str]] = []
    for s in survivor_stmts:
        assert s.node_id is not None
        events.append((s.start, 1, 0, s.node_id))  # after any insertion at its line
    for before, seq, nid, _line in insert_entries:
        if nid == "<return>":
            continue
        events.append((before, 0, seq, nid))  # before the survivor at that line
    events.sort()
    return [nid for *_rest, nid in events]


def _is_topological(order: list[str], graph: Graph) -> bool:
    pos = {nid: i for i, nid in enumerate(order)}
    for nid in order:
        for e in graph.incoming(nid):
            if e.source not in pos or pos[e.source] > pos[nid]:
                return False
    return True


def _group_insertions(
    insert_entries: list[tuple[int, int, str, str]],
) -> list[tuple[int, list[str]]]:
    buckets: dict[int, list[str]] = defaultdict(list)
    for before, _seq, _nid, line in sorted(insert_entries, key=lambda e: (e[0], e[1])):
        buckets[before].append(line)
    return list(buckets.items())


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

    Emits fresh wiring lines from ``graph`` and decides, per statement, whether to
    patch a changed line in place, splice a new node in, splice a removed node
    out, or — when the requested wiring can't be expressed as in-place edits —
    regenerate the whole block (surfaced via ``WritebackResult.warning``). Node
    types the module can't yet call gain a ``from … import …`` line (HD2 §5).
    Raises :class:`engine.EngineError` for a graph that cannot be wired (a node id
    shadowing its function); the caller surfaces that as a 422 with the file
    untouched.
    """
    tree = ast.parse(text)
    composite = find_composite(tree)
    base_call_names = composite_call_names(tree, module_name)
    indent = _indent_of(composite)

    # Bind once; emit from the bound graph so line order matches node order.
    # Partial (ADR 0011 D6): a freshly placed node with unwired required inputs
    # must still SAVE — emit already tolerates missing inputs (`_arg_exprs`
    # emits only provided ones), so the written Python is honest: `v = fn()`.
    # Genuinely broken wiring (unknown type/socket, double-wire, cycle) still
    # raises and reaches the caller as a 422 with the file untouched.
    bound = bind(graph, registry, partial=True)

    # Import management first, so a freshly placed type is callable when we emit.
    reserved = (
        set(base_call_names.values())
        | {n.id for n in bound.nodes}
        | _composite_param_names(composite)
    )
    import_lines, import_before, added_names = _plan_imports(
        tree, bound, base_call_names, reserved
    )
    call_names = {**base_call_names, **added_names}
    import_insertions: list[tuple[int, list[str]]] = (
        [(import_before, import_lines)] if import_lines and import_before else []
    )

    emitted = wiring_lines(bound, registry, call_names=call_names, indent=indent)
    n_nodes = len(bound.nodes)
    line_by_id = {bound.nodes[i].id: emitted[i] for i in range(n_nodes)}
    return_line = emitted[n_nodes] if bound.output is not None else None

    plan = _plan_body(
        text, composite, bound, graph, registry, module_name, line_by_id, return_line
    )
    if plan is None:
        return _regenerate(text, composite, emitted, import_insertions, import_lines)

    insertions = plan.insertions + import_insertions
    new_text = _assemble(text, plan.replacements, insertions)
    if new_text == text:
        return WritebackResult(text=text, strategy="unchanged")
    return WritebackResult(
        text=new_text,
        strategy=plan.strategy,
        changed_ids=plan.changed_ids,
        added_ids=plan.added_ids,
        removed_ids=plan.removed_ids,
        imported=import_lines,
    )


def _regenerate(
    text: str,
    composite: ast.FunctionDef,
    emitted: list[str],
    import_insertions: list[tuple[int, list[str]]],
    import_lines: list[str],
) -> WritebackResult:
    """Whole-block fallback: regenerate the wiring block (ADR 0004 D5 / A1).

    Confined to the composite body (imports, if any, are appended separately).
    When the block held comments/blank lines the projection can't carry over, the
    loss is reported both as ``dropped_comments`` and as a structured ``warning``
    the caller surfaces in the save response (ADR 0011 HD2 §4) — never silent.
    """
    span = _wiring_span(composite)
    replacements: list[tuple[int, int, list[str]]] = []
    insertions: list[tuple[int, list[str]]] = list(import_insertions)

    if span is None:
        body = list(composite.body)
        if _has_docstring(body):
            insert_at = (body[0].end_lineno or body[0].lineno) + 1
        else:
            insert_at = composite.lineno + 1
        insertions.append((insert_at, emitted))
        dropped = False
        reason = "empty composite body"
    else:
        start, end = span
        dropped = _block_has_comments_or_blanks(text, start, end)
        replacements.append((start, end, emitted))
        reason = (
            "the wiring block was regenerated because the edit could not be "
            "applied in place (a reorder, a duplicate target, or a body the "
            "statement model can't express)"
        )

    new_text = _assemble(text, replacements, insertions)
    warning = None
    if dropped:
        warning = {
            "code": "wiring-block-regenerated",
            "message": (
                "Saved, but hand-written comments/blank lines in the wiring "
                "block were not preserved — this edit could not be applied "
                "line-by-line, so the block was regenerated (ADR 0004 D5)."
            ),
            "droppedComments": True,
            "reason": reason,
        }
    return WritebackResult(
        text=new_text,
        strategy="regenerated",
        dropped_comments=dropped,
        reason=reason,
        warning=warning,
        imported=import_lines,
    )
