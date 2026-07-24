"""T8 — the knowledge base: versioned TOML on disk, loaded into typed values.

Entries are addressed ``"<kind>/<family>/<id>"`` (``"materials/timber/C24"``,
``"fasteners/screw/csk-6.0x120"``) or ``"<kind>/<id>"`` for codes
(``"codes/ec5"``), and resolved against a **snapshot version** declared once
per KB root in its ``kb.toml``. Every loaded value carries a
:class:`~designcheck.materials.KbRef`, so the report footer can pin the run and
a reviewer can reproduce it from the module plus the KB version.

A user overlay directory has the same layout and comes *earlier* in the search
path, so it wins by address without anybody forking the shipped tables. The KB
is read at run time and never serialised into a graph; only *addresses* are
literals.

Numbers here are the second boundary (after FEM ingest) where a unit slip can
enter, so every numeric property declares its unit in the key —
``"rho_k[kg/m^3]" = 350.0`` — and is dimension-checked against the schema.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .code import BuildingCode, Clause, SymbolSpec
from .errors import DesignCheckError
from .materials import Concrete, FastenerSteel, KbRef, Material, Steel, Timber
from .members import Screw
from .units import convert, split_unit

# The package is a plain directory on disk (never zip-imported), so the shipped
# KB is addressable as a path.
BUILTIN_KB = Path(__file__).resolve().parent / "kb"

MANIFEST = "kb.toml"

#: address family -> the file that holds it. Explicit rather than derived,
#: because "screw" entries live in "screws.toml" and no naming rule survives
#: contact with real plural forms.
_FAMILY_FILES: dict[tuple[str, str], str] = {
    ("materials", "timber"): "materials/timber.toml",
    ("materials", "steel"): "materials/steel.toml",
    ("materials", "concrete"): "materials/concrete.toml",
    ("fasteners", "screw"): "fasteners/screws.toml",
}

_TWO_SEGMENT_KINDS = ("codes",)


@dataclass(frozen=True)
class _Schema:
    """What one entry family must and may declare."""

    kind: str
    numeric: Mapping[str, str]  # field -> the unit it is stored in
    text: tuple[str, ...]  # required text fields
    optional_text: tuple[str, ...] = ()


_TIMBER = _Schema(
    kind="Timber",
    numeric={"rho_k": "kg/m^3", "f_mk": "MPa", "f_c0k": "MPa", "E_mean": "MPa"},
    text=("source", "grade"),
    optional_text=("description",),
)
_STEEL = _Schema(
    kind="Steel",
    numeric={"f_yk": "MPa", "f_uk": "MPa", "E": "MPa"},
    text=("source", "grade"),
    optional_text=("description",),
)
_CONCRETE = _Schema(
    kind="Concrete",
    numeric={"f_ck": "MPa", "E_cm": "MPa"},
    text=("source", "grade"),
    optional_text=("description",),
)
_SCREW = _Schema(
    kind="Screw",
    numeric={"d": "mm", "L": "mm", "f_uk": "MPa"},
    text=("source",),
    optional_text=("description", "steel_source"),
)


@dataclass(frozen=True)
class KbRoot:
    """One searchable knowledge-base directory and the snapshot it declares."""

    path: Path
    version: str
    name: str


@dataclass(frozen=True)
class KnowledgeBase:
    """An ordered search path of roots; the first root holding an address wins."""

    roots: tuple[KbRoot, ...]

    def __post_init__(self) -> None:
        if not self.roots:
            raise DesignCheckError("a knowledge base needs at least one root")

    @property
    def version(self) -> str:
        """The shipped snapshot version — the last root, which is always the builtin."""
        return self.roots[-1].version

    @property
    def pins(self) -> tuple[str, ...]:
        """One footer pin per root, in search order: ``("kb 2024.1",)``."""
        return tuple(f"kb {root.version}" for root in self.roots)


def load_kb(overlays: Sequence[str | Path] = ()) -> KnowledgeBase:
    """Open the shipped KB, with zero or more overlay directories ahead of it."""
    roots = [_root(Path(overlay)) for overlay in overlays]
    roots.append(_root(BUILTIN_KB))
    return KnowledgeBase(roots=tuple(roots))


def get_material(kb: KnowledgeBase, address: str) -> Material:
    """Load a material entry: ``"materials/timber/C24"``."""
    kind, family, entry_id = _address(address, expected_kind="materials")
    table, root = _entry(kb, address, kind, family, entry_id)
    schema = {"timber": _TIMBER, "steel": _STEEL, "concrete": _CONCRETE}[family]
    numbers, texts = _values(table, address, schema)
    ref = KbRef(address=address, version=root.version, source=texts["source"])
    if family == "timber":
        return Timber(ref=ref, grade=texts["grade"], **numbers)
    if family == "steel":
        return Steel(ref=ref, grade=texts["grade"], **numbers)
    return Concrete(ref=ref, grade=texts["grade"], **numbers)


def get_fastener(kb: KnowledgeBase, address: str) -> Screw:
    """Load a fastener product whole — geometry and its steel arrive together."""
    kind, family, entry_id = _address(address, expected_kind="fasteners")
    table, root = _entry(kb, address, kind, family, entry_id)
    numbers, texts = _values(table, address, _SCREW)
    ref = KbRef(address=address, version=root.version, source=texts["source"])
    steel_ref = KbRef(
        address=address,
        version=root.version,
        source=texts.get("steel_source", texts["source"]),
    )
    return Screw(
        ref=ref,
        d=numbers["d"],
        L=numbers["L"],
        steel=FastenerSteel(ref=steel_ref, f_uk=numbers["f_uk"]),
    )


def get_code(kb: KnowledgeBase, address: str) -> BuildingCode:
    """Load a building code edition: factor tables, clauses and its symbol dictionary."""
    kind, _, entry_id = _address(address, expected_kind="codes")
    table, root = _entry(kb, address, kind, "", entry_id)
    where = f"KB entry {address!r}"

    ref = KbRef(
        address=address,
        version=root.version,
        source=_text(table, "source", where),
    )
    return BuildingCode(
        ref=ref,
        name=_text(table, "name", where),
        edition=_text(table, "edition", where),
        gamma_M=_factor_table(table.get("gamma_M"), "gamma_M", where),
        k_mod=_k_mod(table.get("k_mod"), where),
        clauses=_clauses(table.get("clauses", []), where),
        symbols=_symbols(table.get("symbols", {}), where),
    )


# -- addressing --------------------------------------------------------------


def _address(address: str, *, expected_kind: str) -> tuple[str, str, str]:
    segments = [segment for segment in address.split("/") if segment]
    wanted = 2 if expected_kind in _TWO_SEGMENT_KINDS else 3
    if len(segments) != wanted or segments[0] != expected_kind:
        shape = (
            f"{expected_kind}/<id>"
            if wanted == 2
            else f"{expected_kind}/<family>/<id>"
        )
        raise DesignCheckError(
            f"KB address {address!r} is not of the form {shape!r}"
        )
    if wanted == 2:
        return segments[0], "", segments[1]
    return segments[0], segments[1], segments[2]


def _root(path: Path) -> KbRoot:
    if not path.is_dir():
        raise DesignCheckError(f"knowledge-base root {path} does not exist")
    manifest = path / MANIFEST
    if not manifest.is_file():
        raise DesignCheckError(
            f"knowledge-base root {path} has no {MANIFEST}; a root must declare its "
            f"snapshot version so loaded values can be pinned"
        )
    data = _toml(manifest)
    version = data.get("version")
    if not isinstance(version, str) or not version.strip():
        raise DesignCheckError(f"{manifest}: 'version' must be a non-empty string")
    name = data.get("name", path.name)
    if not isinstance(name, str):
        raise DesignCheckError(f"{manifest}: 'name' must be a string")
    return KbRoot(path=path, version=version, name=name)


def _relative_file(address: str, kind: str, family: str, entry_id: str) -> str:
    if kind in _TWO_SEGMENT_KINDS:
        return f"{kind}/{entry_id}.toml"
    try:
        return _FAMILY_FILES[(kind, family)]
    except KeyError:
        known = ", ".join(f"{k}/{f}" for k, f in sorted(_FAMILY_FILES))
        raise DesignCheckError(
            f"KB address {address!r}: unknown family {kind}/{family}; known families: "
            f"{known}, codes"
        ) from None


def _entry(
    kb: KnowledgeBase, address: str, kind: str, family: str, entry_id: str
) -> tuple[Mapping[str, object], KbRoot]:
    """The first root holding ``address``, and its raw table."""
    relative = _relative_file(address, kind, family, entry_id)
    available: list[str] = []
    for root in kb.roots:
        file = root.path / relative
        if not file.is_file():
            continue
        document = _toml(file)
        if kind in _TWO_SEGMENT_KINDS:
            return document, root
        table = document.get(entry_id)
        if isinstance(table, dict):
            return table, root
        available.extend(key for key in document if isinstance(document[key], dict))
    raise DesignCheckError(
        f"KB entry {address!r} not found in {', '.join(str(r.path) for r in kb.roots)}"
        + (f"; {relative} offers: {', '.join(sorted(set(available)))}" if available else "")
    )


def _toml(file: Path) -> dict[str, object]:
    try:
        with file.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as error:
        raise DesignCheckError(f"{file}: not valid TOML ({error})") from error
    except OSError as error:
        raise DesignCheckError(f"cannot read {file}: {error}") from error


# -- entry decoding ----------------------------------------------------------


def _values(
    table: Mapping[str, object], address: str, schema: _Schema
) -> tuple[dict[str, float], dict[str, str]]:
    """Split one entry into dimension-checked numbers and its text metadata."""
    where = f"KB entry {address!r}"
    numbers: dict[str, float] = {}
    texts: dict[str, str] = {}
    allowed_text = (*schema.text, *schema.optional_text)

    for raw_key, value in table.items():
        name, unit = split_unit(raw_key)
        if isinstance(value, bool):
            raise DesignCheckError(f"{where}: field {name!r} must be a number or a string")
        if isinstance(value, (int, float)):
            expected = schema.numeric.get(name)
            if expected is None:
                raise DesignCheckError(
                    f"{where}: unknown numeric field {name!r} for a {schema.kind}; "
                    f"expected one of {', '.join(sorted(schema.numeric))}"
                )
            if not unit and expected:
                raise DesignCheckError(
                    f"{where}: field {name!r} declares no unit; write "
                    f"'{name}[{expected}]' so its dimension can be checked"
                )
            numbers[name] = convert(
                float(value), unit, expected, what=f"{where}: field {name!r}"
            )
        elif isinstance(value, str):
            if unit:
                raise DesignCheckError(f"{where}: text field {name!r} must not carry a unit")
            if name not in allowed_text:
                raise DesignCheckError(
                    f"{where}: unknown field {name!r} for a {schema.kind}; expected one of "
                    f"{', '.join(sorted((*allowed_text, *schema.numeric)))}"
                )
            texts[name] = value
        else:
            raise DesignCheckError(
                f"{where}: field {name!r} must be a number or a string, got "
                f"{type(value).__name__}"
            )

    missing = [name for name in schema.numeric if name not in numbers]
    missing += [name for name in schema.text if name not in texts]
    if missing:
        raise DesignCheckError(
            f"{where}: missing field(s) {', '.join(repr(name) for name in missing)} "
            f"for a {schema.kind}"
        )
    return numbers, texts


def _text(table: Mapping[str, object], key: str, where: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DesignCheckError(f"{where}: '{key}' must be a non-empty string")
    return value


def _factor_table(value: object, key: str, where: str) -> dict[str, float]:
    if not isinstance(value, dict) or not value:
        raise DesignCheckError(f"{where}: '{key}' must be a non-empty table of factors")
    factors: dict[str, float] = {}
    for name, factor in value.items():
        if isinstance(factor, bool) or not isinstance(factor, (int, float)):
            raise DesignCheckError(f"{where}: {key}.{name} must be a number, got {factor!r}")
        factors[name] = float(factor)
    return factors


def _k_mod(value: object, where: str) -> dict[tuple[int, str], float]:
    """``"2/medium" = 0.80`` -> ``{(2, "medium"): 0.80}``."""
    raw = _factor_table(value, "k_mod", where)
    cells: dict[tuple[int, str], float] = {}
    for key, factor in raw.items():
        service_class, _, duration = key.partition("/")
        if not duration or not service_class.isdigit():
            raise DesignCheckError(
                f"{where}: k_mod key {key!r} must read '<service class>/<load duration>', "
                f"e.g. '2/medium'"
            )
        cells[(int(service_class), duration)] = factor
    return cells


def _clauses(value: object, where: str) -> tuple[Clause, ...]:
    if not isinstance(value, list):
        raise DesignCheckError(f"{where}: 'clauses' must be an array of tables")
    clauses: list[Clause] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise DesignCheckError(f"{where}: clause #{index + 1} must be a table")
        try:
            clauses.append(
                Clause(
                    id=_str(item, "id", where, index),
                    citation=_str(item, "citation", where, index),
                    title=_str(item, "title", where, index),
                    kind=_str(item, "kind", where, index),
                    formula=_str(item, "formula", where, index, default=""),
                    defines=_str(item, "defines", where, index, default=""),
                    check=_str(item, "check", where, index, default=""),
                    utilisation=_str(item, "utilisation", where, index, default=""),
                    unit=_str(item, "unit", where, index, default=""),
                    requires=_str_tuple(item, "requires", where, index),
                    applies=_str_tuple(item, "applies", where, index),
                    notes=_str(item, "notes", where, index, default=""),
                )
            )
        except DesignCheckError as error:
            raise DesignCheckError(f"{where}: {error}") from error
    return tuple(clauses)


def _symbols(value: object, where: str) -> dict[str, SymbolSpec]:
    if not isinstance(value, dict):
        raise DesignCheckError(f"{where}: 'symbols' must be a table of symbol definitions")
    specs: dict[str, SymbolSpec] = {}
    for symbol, spec in value.items():
        if not isinstance(spec, dict):
            raise DesignCheckError(f"{where}: symbols.{symbol} must be a table")
        try:
            specs[symbol] = SymbolSpec(
                symbol=symbol,
                bind=_text(spec, "bind", f"{where}: symbols.{symbol}"),
                unit=str(spec.get("unit", "")),
                citation=str(spec.get("citation", "")),
            )
        except DesignCheckError as error:
            raise DesignCheckError(f"{where}: {error}") from error
    return specs


def _str(
    item: Mapping[str, object], key: str, where: str, index: int, *, default: str | None = None
) -> str:
    value = item.get(key, default)
    if not isinstance(value, str):
        raise DesignCheckError(
            f"clause #{index + 1}: '{key}' must be a string (in {where})"
        )
    return value


def _str_tuple(item: Mapping[str, object], key: str, where: str, index: int) -> tuple[str, ...]:
    value = item.get(key, [])
    if not isinstance(value, list) or not all(isinstance(entry, str) for entry in value):
        raise DesignCheckError(
            f"clause #{index + 1}: '{key}' must be an array of strings (in {where})"
        )
    return tuple(value)


def entries(kb: KnowledgeBase, kind: str, family: str = "") -> tuple[str, ...]:
    """Every address of one family across the search path — for listings and errors."""
    if kind in _TWO_SEGMENT_KINDS:
        found = {
            f"{kind}/{file.stem}"
            for root in kb.roots
            for file in sorted((root.path / kind).glob("*.toml"))
        }
        return tuple(sorted(found))
    relative = _relative_file(f"{kind}/{family}/<id>", kind, family, "")
    addresses: set[str] = set()
    for root in kb.roots:
        file = root.path / relative
        if file.is_file():
            addresses.update(
                f"{kind}/{family}/{key}"
                for key, table in _toml(file).items()
                if isinstance(table, dict)
            )
    return tuple(sorted(addresses))
