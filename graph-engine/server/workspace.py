"""``Workspace`` — the graph as a direct editor of the source tree (ADR 0004).

The Python authoring module is the single source of truth (D2); the UI graph is
a projection of it. This module owns every **write-back** the server performs:

* ``function_source`` / ``replace_function_source`` — read/replace one ``@node``
  function definition in the real ``.py`` file, splicing text by AST line span
  so everything outside the replaced ``def`` is preserved byte-for-byte.
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
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from engine import (
    Graph,
    NodeRegistry,
    composite_call_names,
    find_composite,
    from_composite,
    wiring_lines,
)

# The graph-engine tree — the default boundary for source writes.
ENGINE_ROOT = Path(__file__).resolve().parents[1]


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

        text = path.read_text(encoding="utf-8")
        fn = _find_def(ast.parse(text), spec["qualname"])
        start, end = _def_span(fn)
        new_text = _splice_lines(text, start, end, new_source.splitlines())
        self._write_and_reload(path, new_text, previous=text, module=spec["module"])
        return self.function_source(spec_id)

    # -- graph persistence (PUT /api/graph) -------------------------------

    def save_graph(self, graph: Graph) -> dict[str, Any]:
        """Rewrite the composite's wiring lines from ``graph`` (ADR 0004 D5).

        The composite's decorator, signature and docstring are kept; only the
        wiring statements are replaced, with lines freshly emitted from the
        graph. Positions are persisted to the layout sidecar, never to the
        Python. Returns the graph re-parsed from the rewritten module — the
        round-trip proof that what was saved is what will be served.
        """
        path = self.module_file()
        self._check_editable(path)

        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        composite = find_composite(tree)

        body = composite.body
        has_doc = (
            isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        )
        wiring = body[1:] if has_doc else body
        indent = " " * (wiring[0].col_offset if wiring else composite.col_offset + 4)
        # Call each node by the name THIS module binds it to (imports from other
        # packs + local defs), so a composite that wires cross-pack nodes (the
        # showcase) round-trips in place — not only all-local composites.
        call_names = composite_call_names(tree, self.module_name)
        lines = wiring_lines(graph, self.registry, call_names=call_names, indent=indent)

        if wiring:
            start, end = wiring[0].lineno, max(s.end_lineno or s.lineno for s in wiring)
            new_text = _splice_lines(text, start, end, lines)
        else:  # docstring-only body → insert after it
            insert_at = (body[0].end_lineno or body[0].lineno) + 1
            new_text = _splice_lines(text, insert_at, insert_at - 1, lines)

        self._write_and_reload(path, new_text, previous=text, module=self.module_name)
        self._save_layout(graph)
        return self.parse_graph()

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
