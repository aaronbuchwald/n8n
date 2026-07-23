"""``EntryCatalog`` — discovery roots → imported modules → viewable entries (ADR 0009).

Two layers, mirroring how ``@node`` + ``DEFAULT_REGISTRY`` already work:

1. **``@main`` registers** (:data:`engine.ENTRY_POINTS`) — the authoritative
   list: whatever is imported and marked ``@main`` is an entry point, including
   ``--library`` modules the scan never sees.
2. **Scan roots decide what to import** — each root is searched for the bundled
   layout ``<name>/<name>.py`` (exactly the old ``server/demo.py`` ``EXAMPLES``
   convention, minus the hand-maintenance). Candidates go on ``sys.path`` and
   are imported **eagerly at catalog build**; an entry that fails to import is
   *listed* with ``status: "error"`` + the message instead of silently missing
   (report, don't hide).

The catalog also owns the memoized workspace pool ``id → (Workspace,
run_base_dir)``. All workspaces share one registry (spec ids are
module-qualified, collision-proof), each entry keeps its own layout sidecar and
run directory — N coexisting programs at ~zero memory cost.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any, Optional

from engine import DEFAULT_REGISTRY, ENTRY_POINTS, NodeRegistry

from .workspace import ENGINE_ROOT, Workspace, find_repo_root

EXAMPLES_ROOT = ENGINE_ROOT / "examples"
DEFAULT_EXAMPLE = "showcase"

# Deps the sym.* node pack lazy-imports at run time; a graph that uses sym nodes
# is unrunnable without them, so the listing reports it up front (ADR 0009 D5).
_SYM_DEPS = ("sympy", "handcalcs", "forallpeople", "latex2mathml")


class UnknownEntryError(KeyError):
    """The id names no known entry; carries the known ids for the 404 body."""

    def __init__(self, entry_id: str, known: list[str]) -> None:
        super().__init__(entry_id)
        self.entry_id = entry_id
        self.known = known
        self.message = f"unknown graph {entry_id!r}; known ids: {', '.join(known) or '(none)'}"


class EntryLoadError(Exception):
    """The entry exists but is unusable (its import failed) — HTTP 409."""


def _repo_relative(path: Path) -> str:
    root = find_repo_root(path.parent if path.is_file() else path)
    resolved = path.resolve()
    if root is not None and resolved.is_relative_to(root):
        return resolved.relative_to(root).as_posix()
    return str(path)


class EntryCatalog:
    """Discovered entry points over ``roots``, with a memoized workspace pool."""

    def __init__(
        self,
        roots: Optional[list[Path]] = None,
        registry: Optional[NodeRegistry] = None,
        default: str = DEFAULT_EXAMPLE,
    ) -> None:
        self.roots = [Path(r).resolve() for r in (roots or [EXAMPLES_ROOT])]
        self.registry = registry or DEFAULT_REGISTRY
        self.default = default
        self._import_errors: dict[str, str] = {}
        self._scanned_dirs: dict[str, Path] = {}
        self._pool: dict[str, tuple[Workspace, Path]] = {}

    # -- discovery --------------------------------------------------------

    def discover(self) -> "EntryCatalog":
        """Scan every root and eagerly import each ``<name>/<name>.py`` candidate.

        Import errors are captured per entry, never raised — the listing stays
        honest and the server boots regardless. Returns ``self`` for chaining.
        """
        for root in self.roots:
            if not root.is_dir():
                continue
            for candidate in sorted(root.iterdir()):
                module_file = candidate / f"{candidate.name}.py"
                if not (candidate.is_dir() and module_file.is_file()):
                    continue
                name = candidate.name
                previous = self._scanned_dirs.get(name)
                if previous is not None and previous != candidate:
                    # Two roots claim the same module name: first import wins,
                    # the loser is listed as an error rather than guessed at.
                    self._import_errors[name] = (
                        f"duplicate entry id {name!r}: already provided by {previous}"
                    )
                    continue
                loaded = sys.modules.get(name)
                loaded_file = getattr(loaded, "__file__", None) if loaded else None
                if loaded_file is not None and Path(loaded_file).resolve() != module_file.resolve():
                    self._import_errors[name] = (
                        f"module name collision: {name!r} is already imported from {loaded_file}"
                    )
                    continue
                self._scanned_dirs[name] = candidate
                if str(candidate) not in sys.path:
                    sys.path.insert(0, str(candidate))
                try:
                    importlib.import_module(name)
                except Exception as exc:  # capture, don't hide (ADR 0009 D2)
                    self._import_errors[name] = f"{type(exc).__name__}: {exc}"
        return self

    # -- listing ----------------------------------------------------------

    def ids(self) -> list[str]:
        """Every known id: registered ``@main`` modules ∪ import failures."""
        registered = {e["module"] for e in ENTRY_POINTS.entries()}
        return sorted(registered | set(self._import_errors))

    def entries(self) -> list[dict[str, Any]]:
        """The ``GET /api/graphs`` ``entries`` list (the frozen D4 shape).

        Status is recomputed per call: an entry whose module imported but whose
        composite no longer parses (or whose graph needs missing sym deps) is
        reported ``status: "error"`` with the reason, so selection-time
        surprises become listing-time facts.
        """
        out: list[dict[str, Any]] = []
        for ep in ENTRY_POINTS.entries():
            entry_id = ep["module"]
            file = Path(ep["file"]) if ep["file"] else None
            base_dir = self._scanned_dirs.get(entry_id, file.parent if file else ENGINE_ROOT)
            item: dict[str, Any] = {
                "id": entry_id,
                "title": ep["title"],
                "module": ep["module"],
                "qualname": ep["qualname"],
                "path": _repo_relative(file) if file else None,
                "dir": _repo_relative(base_dir),
                "status": "ok",
            }
            error = self._preflight(entry_id)
            if error is not None:
                item["status"] = "error"
                item["error"] = error
            out.append(item)
        for name, message in sorted(self._import_errors.items()):
            directory = self._scanned_dirs.get(name)
            file = directory / f"{name}.py" if directory else None
            out.append(
                {
                    "id": name,
                    "title": name,
                    "module": name,
                    "qualname": None,
                    "path": _repo_relative(file) if file else None,
                    "dir": _repo_relative(directory) if directory else None,
                    "status": "error",
                    "error": message,
                }
            )
        return out

    def _preflight(self, entry_id: str) -> Optional[str]:
        """Why ``entry_id`` isn't currently viewable/runnable, or ``None``."""
        try:
            workspace, _ = self.workspace(entry_id)
            doc = workspace.parse_graph()
        except Exception as exc:  # noqa: BLE001 — report the reason, don't hide it
            return str(exc)
        if any(str(n.get("type", "")).startswith("sym.") for n in doc["nodes"]):
            missing = [m for m in _SYM_DEPS if importlib.util.find_spec(m) is None]
            if missing:
                return (
                    "runs symbolic-math nodes but these deps are missing: "
                    + ", ".join(missing)
                    + " (install the `demo` extra)"
                )
        return None

    # -- the workspace pool ------------------------------------------------

    def workspace(self, entry_id: str) -> tuple[Workspace, Path]:
        """The memoized ``(Workspace, run_base_dir)`` for ``entry_id``.

        Raises :class:`UnknownEntryError` (→ 404) for an id nothing registered,
        :class:`EntryLoadError` (→ 409) for one whose import failed.
        """
        cached = self._pool.get(entry_id)
        if cached is not None:
            return cached
        if entry_id in self._import_errors:
            raise EntryLoadError(
                f"graph {entry_id!r} failed to load: {self._import_errors[entry_id]}"
            )
        if entry_id not in ENTRY_POINTS:
            raise UnknownEntryError(entry_id, self.ids())
        ep = ENTRY_POINTS.get(entry_id)
        module_file = Path(ep["file"]).resolve() if ep["file"] else None
        base_dir = self._scanned_dirs.get(
            entry_id, module_file.parent if module_file else ENGINE_ROOT
        )
        # Roots outside the engine tree (--entries DIR) must stay editable —
        # that is the point of adding them — so they join the write boundary.
        workspace = Workspace(
            self.registry, entry_id, allowed_roots=[ENGINE_ROOT, *self.roots]
        )
        self._pool[entry_id] = (workspace, base_dir)
        return self._pool[entry_id]
