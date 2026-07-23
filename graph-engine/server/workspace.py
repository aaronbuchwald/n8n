"""``Workspace`` — the graph as a direct editor of the source tree (ADR 0004).

The Python authoring module is the single source of truth (D2); the UI graph is
a projection of it. This module owns every **write-back** the server performs:

* ``function_source`` / ``replace_function_source`` — read/replace one ``@node``
  function definition in the real ``.py`` file, splicing text by AST line span
  so everything outside the replaced ``def`` is preserved byte-for-byte.
* ``create_function`` — splice a brand-new ``@node`` function into a target
  module (ADR 0011 D7/HD1/W6): insertion-only (no existing line touched), so it
  never disturbs anything ``replace_function_source`` promises to leave alone.
* ``list_target_modules`` — the workspace module + every other module the
  registry currently has types in, filtered to ``allowed_roots`` — the data
  behind the "New node" destination picker (HD1).
* ``save_graph`` — rewrite *only* the ``@main`` composite's wiring lines from a
  graph (D5); node bodies, imports, comments and the composite's own signature/
  docstring are untouched. Layout goes to a ``<module>.layout.json`` sidecar
  (D6), never into the Python.
* ``info`` — the current git branch + the repo-relative path of the module
  being edited, so the UI can show *where* edits will land.

Safety: writes are refused outside the workspace's ``allowed_roots`` (realpath
checked), refused when the submitted source does not parse or does not define
the same function, and rolled back if the rewritten module fails to re-import.
"""

from __future__ import annotations

import ast
import importlib
import json
import logging
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Optional

from engine import EngineError, Graph, NodeRegistry, find_composite, from_composite

from .writeback import compute_writeback

# The graph-engine tree — the default boundary for source writes.
ENGINE_ROOT = Path(__file__).resolve().parents[1]

# ADR 0009 "Concurrency strategy": with several coexisting workspaces over one
# branch, two tabs can write concurrently. Every write-back is a read-modify-
# write of a real file (and a shared module reload), so ALL of them serialize
# on one process-wide lock — global, not per-workspace, because two entries can
# edit the same file through a shared node pack. Between whole operations the
# policy is last-write-wins; reads reparse from disk. Optimistic version/ETag
# gating is deliberately deferred to ADR 0008's seq-gated store.
_WRITE_LOCK = threading.Lock()

logger = logging.getLogger(__name__)


class SourceEditError(Exception):
    """A rejected source read/write, carrying the HTTP status to reply with."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


# ----------------------------------------------------------------------
# git — current branch reporting
# ----------------------------------------------------------------------


def find_repo_root(start: Path) -> Optional[Path]:
    """Walk up from ``start`` to the first directory containing ``.git``."""
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _git_dir(repo_root: Path) -> Optional[Path]:
    """Resolve ``.git`` — a directory, or (in a worktree) a pointer file."""
    dot_git = repo_root / ".git"
    if dot_git.is_dir():
        return dot_git
    if dot_git.is_file():
        try:
            text = dot_git.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if text.startswith("gitdir:"):
            gitdir = Path(text.split(":", 1)[1].strip())
            return gitdir if gitdir.is_absolute() else (repo_root / gitdir).resolve()
    return None


def _read_head(repo_root: Path) -> tuple[Optional[str], bool]:
    """Fallback branch detection: read ``.git/HEAD`` directly (no git binary)."""
    gitdir = _git_dir(repo_root)
    if gitdir is None:
        return None, False
    try:
        head = (gitdir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None, False
    if head.startswith("ref: refs/heads/"):
        return head[len("ref: refs/heads/"):], False
    return None, True  # a bare commit hash → detached


def git_branch_info(repo_root: Optional[Path]) -> dict[str, Any]:
    """``{"branch", "detached", "commit"}`` for the repo at ``repo_root``.

    Prefers ``git rev-parse``; falls back to reading ``.git/HEAD`` when the git
    binary is unavailable. ``branch`` is ``None`` when detached or unknown.
    """

    def _git(*args: str) -> Optional[str]:
        try:
            proc = subprocess.run(
                ["git", *args], cwd=repo_root, capture_output=True, text=True, timeout=5
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        out = proc.stdout.strip()
        return out if proc.returncode == 0 and out else None

    if repo_root is None:
        return {"branch": None, "detached": False, "commit": None}

    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    commit = _git("rev-parse", "--short", "HEAD")
    if branch is None:
        fallback, detached = _read_head(repo_root)
        return {"branch": fallback, "detached": detached, "commit": commit}
    if branch == "HEAD":  # detached HEAD
        return {"branch": None, "detached": True, "commit": commit}
    return {"branch": branch, "detached": False, "commit": commit}


# ----------------------------------------------------------------------
# AST helpers — locating a def / a composite body span
# ----------------------------------------------------------------------


def _def_span(fn: ast.FunctionDef) -> tuple[int, int]:
    """1-based inclusive line span of a def, decorators included."""
    start = min([fn.lineno, *(d.lineno for d in fn.decorator_list)])
    return start, fn.end_lineno or fn.lineno


def _find_def(tree: ast.Module, qualname: str) -> ast.FunctionDef:
    if "." in qualname:
        raise SourceEditError(
            f"{qualname!r} is not a top-level function; only top-level "
            f"functions are editable",
            status=400,
        )
    for stmt in tree.body:
        if isinstance(stmt, ast.FunctionDef) and stmt.name == qualname:
            return stmt
    raise SourceEditError(
        f"function {qualname!r} was not found in the module", status=404
    )


def _splice_lines(text: str, start: int, end: int, replacement: list[str]) -> str:
    """Replace 1-based inclusive line range ``start..end`` with ``replacement``.

    Everything outside the range is preserved byte-for-byte (splitlines with
    ``keepends`` + join — no reformatting of untouched lines).
    """
    lines = text.splitlines(keepends=True)
    new_block = [line if line.endswith("\n") else line + "\n" for line in replacement]
    return "".join(lines[: start - 1] + new_block + lines[end:])


def _insert_lines(text: str, at_line: int, block: list[str]) -> str:
    """Insert ``block`` immediately before 1-based line ``at_line``.

    Insertion only — no existing line is touched or renumbered away, so this is
    comment/blank-line preserving by construction (ADR 0011 HD2 case 1, applied
    to a new function def rather than a wiring statement).
    """
    lines = text.splitlines(keepends=True)
    new_block = [line if line.endswith("\n") else line + "\n" for line in block]
    return "".join(lines[: at_line - 1] + new_block + lines[at_line - 1 :])


def _top_level_names(tree: ast.Module) -> set[str]:
    """Every top-level name a new function's own name could collide with.

    Defs/classes (by name) and imports (by their local, possibly-aliased name)
    — the collision set ``create_function`` checks a new function's name
    against (D7). Deliberately narrower than :func:`engine.mint.module_collision_set`
    (which guards *node ids*, i.e. composite-body variables): this guards the
    module's top-level *function/class/import* namespace instead.
    """
    names: set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(stmt.name)
        elif isinstance(stmt, ast.Import):
            for alias in stmt.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(stmt, ast.ImportFrom):
            for alias in stmt.names:
                names.add(alias.asname or alias.name)
    return names


# ----------------------------------------------------------------------
# the workspace
# ----------------------------------------------------------------------


class Workspace:
    """One imported authoring module, edited in place on the current branch.

    ``registry`` must be the registry the module's ``@node`` decorators write
    to (in practice ``DEFAULT_REGISTRY``) so re-imports refresh the specs the
    server serves. ``allowed_roots`` bounds where writes may land; it defaults
    to the graph-engine tree.
    """

    def __init__(
        self,
        registry: NodeRegistry,
        module_name: str,
        *,
        allowed_roots: Optional[list[Path]] = None,
    ) -> None:
        self.registry = registry
        self.module_name = module_name
        self.allowed_roots = [p.resolve() for p in (allowed_roots or [ENGINE_ROOT])]

    # -- files & paths ---------------------------------------------------

    def module_file(self) -> Path:
        module = sys.modules.get(self.module_name)
        if module is None or getattr(module, "__file__", None) is None:
            raise SourceEditError(
                f"module {self.module_name!r} is not imported or has no file",
                status=500,
            )
        return Path(module.__file__).resolve()

    def _check_editable(self, path: Path) -> None:
        resolved = path.resolve()
        if not any(resolved.is_relative_to(root) for root in self.allowed_roots):
            raise SourceEditError(
                f"refusing to edit {resolved.name!r}: the file is outside the "
                f"editable workspace",
                status=403,
            )

    def repo_root(self) -> Optional[Path]:
        try:
            return find_repo_root(self.module_file().parent)
        except SourceEditError:
            return None

    def _repo_relative(self, path: Path) -> str:
        root = self.repo_root()
        if root is not None and path.resolve().is_relative_to(root):
            return path.resolve().relative_to(root).as_posix()
        return str(path)

    def layout_file(self) -> Path:
        return self.module_file().with_suffix(".layout.json")

    def info(self) -> dict[str, Any]:
        """The ``GET /api/workspace`` payload: branch + edited module paths."""
        try:
            module_path = self.module_file()
            modules = [
                {"module": self.module_name, "path": self._repo_relative(module_path)}
            ]
        except SourceEditError:
            modules = []
        return {**git_branch_info(self.repo_root()), "modules": modules}

    # -- spec resolution -------------------------------------------------

    def _spec(self, spec_id: str) -> dict:
        if spec_id not in self.registry:
            raise SourceEditError(f"unknown node type {spec_id!r}", status=404)
        spec = self.registry.spec(spec_id)
        if spec["module"] != self.module_name:
            # The spec's own module decides which file we touch; anything not
            # imported (or outside the roots) is rejected below.
            module = sys.modules.get(spec["module"])
            if module is None or getattr(module, "__file__", None) is None:
                raise SourceEditError(
                    f"the module of {spec_id!r} ({spec['module']!r}) is not an "
                    f"editable file",
                    status=403,
                )
        return spec

    def _file_for(self, spec: dict) -> Path:
        if spec["module"] == self.module_name:
            return self.module_file()
        module = sys.modules[spec["module"]]
        return Path(module.__file__).resolve()

    # -- node-body editing (GET/PUT /api/source/{spec_id}) ----------------

    def function_source(self, spec_id: str) -> dict[str, Any]:
        """The exact source of one ``@node`` function, with file + line range."""
        spec = self._spec(spec_id)
        path = self._file_for(spec)
        self._check_editable(path)
        text = path.read_text(encoding="utf-8")
        fn = _find_def(ast.parse(text), spec["qualname"])
        start, end = _def_span(fn)
        lines = text.splitlines(keepends=True)
        return {
            "specId": spec_id,
            "module": spec["module"],
            "qualname": spec["qualname"],
            "path": self._repo_relative(path),
            "startLine": start,
            "endLine": end,
            "source": "".join(lines[start - 1 : end]),
        }

    def _validate_replacement(self, spec: dict, new_source: str) -> ast.FunctionDef:
        try:
            new_tree = ast.parse(new_source)
        except SyntaxError as exc:
            raise SourceEditError(f"the submitted source does not parse: {exc}") from exc
        defs = [s for s in new_tree.body if isinstance(s, ast.FunctionDef)]
        if len(new_tree.body) != 1 or len(defs) != 1:
            raise SourceEditError(
                "the submitted source must contain exactly one top-level "
                "function definition"
            )
        new_def = defs[0]
        if new_def.name != spec["qualname"]:
            raise SourceEditError(
                f"the submitted source defines {new_def.name!r}; it must keep "
                f"the name {spec['qualname']!r}"
            )
        if not new_def.decorator_list:
            raise SourceEditError(
                "the submitted source dropped the decorator — keep @node so "
                "the function stays registered"
            )
        return new_def

    def replace_function_source(self, spec_id: str, new_source: str) -> dict[str, Any]:
        """Write an edited ``def`` back into the real file, then re-introspect.

        Only the located function's line span is replaced; the rest of the file
        is preserved byte-for-byte. The module is re-imported so the registry
        (and therefore ``/api/specs`` and ``/api/run``) reflect the change; a
        re-import failure restores the previous file content.
        """
        spec = self._spec(spec_id)
        path = self._file_for(spec)
        self._check_editable(path)
        self._validate_replacement(spec, new_source)

        with _WRITE_LOCK:  # serialize the read-modify-write (ADR 0009)
            text = path.read_text(encoding="utf-8")
            fn = _find_def(ast.parse(text), spec["qualname"])
            start, end = _def_span(fn)
            new_text = _splice_lines(text, start, end, new_source.splitlines())
            self._write_and_reload(path, new_text, previous=text, module=spec["module"])
        return self.function_source(spec_id)

    # -- new-function authoring (POST /api/source — ADR 0011 D7/HD1/W6) ---

    def list_target_modules(self) -> list[dict[str, Any]]:
        """Modules eligible to receive a new ``@node`` (the HD1 picker's data).

        The workspace's own module (always first — the HD1 default) plus every
        other module the registry currently has types registered in, filtered to
        files that resolve inside ``allowed_roots``. A module outside the roots,
        or with no resolvable file (not actually imported), is omitted — offering
        it would only lead to :meth:`create_function` refusing it anyway; the
        picker and the write share this one source of truth.
        """
        ordered = [self.module_name]
        seen = {self.module_name}
        for spec in self.registry.specs().values():
            name = spec["module"]
            if name not in seen:
                seen.add(name)
                ordered.append(name)

        targets: list[dict[str, Any]] = []
        for name in ordered:
            module = sys.modules.get(name)
            file = getattr(module, "__file__", None) if module is not None else None
            if file is None:
                continue
            resolved = Path(file).resolve()
            if not any(resolved.is_relative_to(root) for root in self.allowed_roots):
                continue
            targets.append({"module": name, "path": self._repo_relative(resolved)})
        return targets

    def _resolve_target_module(self, module: Optional[str]) -> tuple[str, Path]:
        """The ``(module name, file path)`` a new ``@node`` should land on (HD1).

        Defaults to the workspace's own module. An explicit ``module`` must
        already be imported (the picker only ever offers modules the process has
        already loaded — see :meth:`list_target_modules`); anything else is
        rejected rather than guessed at or auto-imported. ``allowed_roots`` is
        enforced by the caller via ``_check_editable``, same as every other write.
        """
        target = module or self.module_name
        if target == self.module_name:
            return target, self.module_file()
        mod = sys.modules.get(target)
        file = getattr(mod, "__file__", None) if mod is not None else None
        if file is None:
            raise SourceEditError(
                f"module {target!r} is not imported or has no file, so a new "
                f"function can't be written there",
                status=404,
            )
        return target, Path(file).resolve()

    def _validate_new_function(self, existing_tree: ast.Module, new_source: str) -> ast.FunctionDef:
        """Validate a brand-new ``@node`` before it is spliced into a module.

        Mirrors ``_validate_replacement``'s parse/shape/decorator checks, plus
        the check unique to creation: the name must not already exist as a
        top-level def/class/import in the target module (D7) — an existing name
        is never silently shadowed or overwritten; ``PUT /api/source/{id}`` is
        the endpoint for editing something that already exists.
        """
        try:
            new_tree = ast.parse(new_source)
        except SyntaxError as exc:
            raise SourceEditError(f"the submitted source does not parse: {exc}") from exc
        defs = [s for s in new_tree.body if isinstance(s, ast.FunctionDef)]
        if len(new_tree.body) != 1 or len(defs) != 1:
            raise SourceEditError(
                "the submitted source must contain exactly one top-level "
                "function definition"
            )
        new_def = defs[0]
        if not new_def.decorator_list:
            raise SourceEditError(
                "the submitted source has no decorator — add @node so the "
                "function registers as a node type"
            )
        if new_def.name in _top_level_names(existing_tree):
            raise SourceEditError(
                f"{new_def.name!r} already exists in the target module — edit "
                f"it with PUT /api/source/{{id}} instead of creating a new function"
            )
        return new_def

    def create_function(self, new_source: str, *, module: Optional[str] = None) -> dict[str, Any]:
        """Splice a brand-new ``@node`` function into a target module.

        ``module`` defaults to the workspace's own module (HD1 default (a)); an
        explicit value must resolve to an already-imported module inside
        ``allowed_roots`` (:meth:`list_target_modules` lists the legitimate
        choices a picker should offer). The new def is spliced **immediately
        above** the module's ``@main``/``@graph`` composite — bodies first,
        wiring last, matching every hand-authored example module (D7) — or
        appended at EOF when the module has no single composite (a pure node
        pack). Only the new lines are touched; everything else in the file is
        preserved byte-for-byte (insertion, not replacement).

        Reload + rollback mirror :meth:`replace_function_source` exactly: a
        def that parses but fails to *execute* on import (e.g. a raising
        default argument) restores the previous file content and 422s, so a
        broken new function never leaves the module unimportable. Returns the
        freshly registered function's :meth:`function_source` payload
        (path/line-range/source), the same shape an edit's response carries.
        """
        target_module, path = self._resolve_target_module(module)
        self._check_editable(path)

        with _WRITE_LOCK:  # serialize the read-modify-write (ADR 0009)
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text)
            new_def = self._validate_new_function(tree, new_source)

            block = new_source.rstrip("\n").splitlines()
            try:
                composite = find_composite(tree)
            except EngineError:
                # No single @main/@graph composite (a pure pack module, or one
                # that doesn't parse to a composite yet) — append at EOF (D7).
                new_text = text if text.endswith("\n") else text + "\n"
                if new_text.strip():
                    new_text += "\n\n"
                new_text += "\n".join(block) + "\n"
            else:
                at_line = min(
                    [composite.lineno, *(d.lineno for d in composite.decorator_list)]
                )
                new_text = _insert_lines(text, at_line, [*block, "", ""])

            self._write_and_reload(path, new_text, previous=text, module=target_module)

        return self.function_source(f"{target_module}.{new_def.name}")

    # -- graph persistence (PUT /api/graph) -------------------------------

    def save_graph(self, graph: Graph) -> dict[str, Any]:
        """Rewrite the composite's wiring from ``graph`` (ADR 0004 D5 / 0011 HD2).

        Value/edge edits patch only the statements that changed; structural edits
        splice new nodes in / removed nodes out by AST line span, so every
        surrounding comment, blank line and multi-line literal in the ``@main``
        body survives byte-for-byte (see :mod:`server.writeback`). A node type the
        module can't yet call gains an import line. Only a save the statement model
        can't express in place (a reorder, a duplicate target, an unparseable
        body) falls back to regenerating the whole wiring block — the normalized
        projection ADR 0004 D5 permits. That fallback is no longer silent: the
        loss is logged **and** surfaced in the response under ``writeback`` (a
        structured, UI-showable warning; ADR 0011 HD2 §4) so a canvas user sees
        it. Positions go to the layout sidecar, never the Python. Returns the
        graph re-parsed from the rewritten module — the round-trip proof that what
        was saved is what will be served.
        """
        path = self.module_file()
        self._check_editable(path)

        with _WRITE_LOCK:  # serialize the read-modify-write (ADR 0009)
            text = path.read_text(encoding="utf-8")
            result = compute_writeback(text, graph, self.registry, self.module_name)

            if result.warning is not None:
                logger.warning(
                    "PUT /api/graph: %s could not be applied in place, so the @main "
                    "wiring block was regenerated and its hand-written comments/blank "
                    "lines were not preserved (ADR 0004 D5 normalization). %s",
                    self._repo_relative(path),
                    result.reason or "",
                )

            if result.text != text:
                self._write_and_reload(
                    path, result.text, previous=text, module=self.module_name
                )
            self._save_layout(graph)
        doc = self.parse_graph()
        # W2→W3 seam: only the lossy fallback carries a warning; every lossless
        # strategy returns the bare projection so the round-trip stays an identity
        # (``GET == PUT`` holds). W3 lifts this onto the PUT envelope; until then
        # the field rides alongside the graph the route already wraps.
        if result.warning is not None:
            doc["writeback"] = result.warning
        return doc

    def _save_layout(self, graph: Graph) -> None:
        positions = {n.id: n.position for n in graph.nodes if n.position is not None}
        layout = self.layout_file()
        if positions:
            layout.write_text(json.dumps(positions, indent=2) + "\n", encoding="utf-8")
        elif layout.exists():
            layout.unlink()

    def parse_graph(self) -> dict[str, Any]:
        """Project the module back to graph JSON (D4), merging sidecar layout."""
        text = self.module_file().read_text(encoding="utf-8")
        doc = from_composite(text, self.registry, module_name=self.module_name).to_dict()
        layout = self.layout_file()
        if layout.exists():
            try:
                positions = json.loads(layout.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                positions = {}
            for node in doc["nodes"]:
                if node["id"] in positions:
                    node["position"] = positions[node["id"]]
        return doc

    # -- write + re-import, with rollback ---------------------------------

    def _reload(self, module: str) -> None:
        self.registry.unregister_module(module)
        importlib.reload(sys.modules[module])

    def _write_and_reload(
        self, path: Path, new_text: str, *, previous: str, module: str
    ) -> None:
        path.write_text(new_text, encoding="utf-8")
        try:
            self._reload(module)
        except Exception as exc:
            # The edit parsed but the module failed to execute (e.g. a default
            # argument raising at def time). Put the old content back so the
            # source tree is never left broken.
            path.write_text(previous, encoding="utf-8")
            try:
                self._reload(module)
            except Exception:  # pragma: no cover - restore is best effort
                pass
            raise SourceEditError(
                f"the edited module failed to load ({exc}); the file was restored",
                status=422,
            ) from exc
