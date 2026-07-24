"""T9 — ``Demand``: the FEM-derived actions, unit-checked at the boundary.

The file is assumed to already hold **factored design-level combinations**
(ULS rows); generating combinations from characteristic cases is a separable
feature and out of scope. ``governing_action`` takes the largest magnitude and
records *which case governed*, so adding combination generation later is
additive rather than a rewrite.

Column units live in the header brackets (``V_z[kN]``). The reader parses the
bracket, checks the dimension and converts — a ``V_z[mm]`` column dies here
rather than becoming a plausible-looking wrong answer six rows later.
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .errors import DesignCheckError
from .units import convert, split_unit

#: Component -> the unit the row stores it in. Forces in kN, moments in kN·m:
#: the units a structural engineer reads off an FEM report, kept as-is so the
#: GIVEN row in the proof says "4.2 kN" and the kN -> N step is a visible
#: formula row rather than an invisible conversion.
COMPONENT_UNITS = {
    "N": "kN",
    "V_y": "kN",
    "V_z": "kN",
    "M_y": "kNm",
    "M_z": "kNm",
}

_KEY_COLUMNS = ("element", "case")


@dataclass(frozen=True)
class ActionRow:
    """One FEM row: the actions on one element under one load case.

    ``source`` names the file it was read from so a ``Demand`` reduced from
    these rows can cite it without the caller re-supplying what it already knows.
    """

    element: str
    case: str
    N: float  # axial [kN]
    V_y: float  # shear [kN]
    V_z: float  # shear [kN]
    M_y: float  # moment [kN·m]
    M_z: float  # moment [kN·m]
    source: str = ""

    def __post_init__(self) -> None:
        for name, value in (("element", self.element), ("case", self.case)):
            if not value.strip():
                raise DesignCheckError(f"ActionRow.{name} must be non-empty")
        for component in COMPONENT_UNITS:
            value = getattr(self, component)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise DesignCheckError(
                    f"ActionRow {self.element!r}/{self.case!r}: {component} must be a "
                    f"number, got {value!r}"
                )
            if not math.isfinite(value):
                raise DesignCheckError(
                    f"ActionRow {self.element!r}/{self.case!r}: {component} is not finite"
                )

    def component(self, name: str) -> float:
        """One named action component, or a refusal listing the ones there are."""
        if name not in COMPONENT_UNITS:
            raise DesignCheckError(
                f"unknown action component {name!r}; available components: "
                f"{', '.join(COMPONENT_UNITS)}"
            )
        return float(getattr(self, name))


@dataclass(frozen=True)
class Demand:
    """The single reduction the checks consume, with the case that produced it."""

    element: str
    component: str
    value: float
    unit: str
    case: str
    source: str

    def __post_init__(self) -> None:
        for name, value in (
            ("element", self.element),
            ("component", self.component),
            ("case", self.case),
            ("source", self.source),
        ):
            if not value.strip():
                raise DesignCheckError(
                    f"Demand.{name} must be non-empty — an action with no {name} "
                    f"cannot be traced back to the model that produced it"
                )
        if not isinstance(self.value, (int, float)) or isinstance(self.value, bool):
            raise DesignCheckError(f"Demand.value must be a number, got {self.value!r}")
        if not math.isfinite(self.value):
            raise DesignCheckError(f"Demand.value must be finite, got {self.value!r}")

    @property
    def ref(self) -> str:
        """The gutter form: ``"fem_forces.csv · V_z · ULS-2"``."""
        return f"{self.source} · {self.component} · {self.case}"


def parse_fem_actions(text: str, source: str) -> tuple[ActionRow, ...]:
    """Parse FEM CSV text whose header carries units in brackets.

    ``element,case,N[kN],V_y[kN],V_z[kN],M_y[kNm],M_z[kNm]`` — every action
    column must declare a unit of the right dimension; a missing column, a
    foreign unit or a non-numeric cell is refused here, by name.
    """
    if not source.strip():
        raise DesignCheckError("parse_fem_actions needs a source name for provenance")
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise DesignCheckError(f"{source}: the file is empty") from None

    columns: dict[str, int] = {}
    units: dict[str, str] = {}
    for index, cell in enumerate(header):
        name, unit = split_unit(cell.strip())
        if name in columns:
            raise DesignCheckError(f"{source}: duplicate column {name!r}")
        columns[name] = index
        units[name] = unit

    missing = [name for name in (*_KEY_COLUMNS, *COMPONENT_UNITS) if name not in columns]
    if missing:
        raise DesignCheckError(
            f"{source}: missing column(s) {', '.join(repr(name) for name in missing)}; "
            f"header has {', '.join(repr(name) for name in columns)}"
        )
    for component, expected in COMPONENT_UNITS.items():
        if not units[component]:
            raise DesignCheckError(
                f"{source}: column {component!r} declares no unit; write "
                f"'{component}[{expected}]'"
            )
        # Dimension check only — the conversion factor is applied per cell below.
        convert(1.0, units[component], expected, what=f"{source}: column {component!r}")

    rows: list[ActionRow] = []
    for number, record in enumerate(reader, start=2):
        if not any(cell.strip() for cell in record):
            continue
        if len(record) < len(header):
            raise DesignCheckError(
                f"{source} line {number}: expected {len(header)} fields, got {len(record)}"
            )
        where = f"{source} line {number}"
        values: dict[str, float] = {}
        for component, expected in COMPONENT_UNITS.items():
            raw = record[columns[component]].strip()
            try:
                magnitude = float(raw)
            except ValueError:
                raise DesignCheckError(
                    f"{where}: column {component!r} is not a number ({raw!r})"
                ) from None
            values[component] = convert(
                magnitude, units[component], expected, what=f"{where}: column {component!r}"
            )
        rows.append(
            ActionRow(
                element=record[columns["element"]].strip(),
                case=record[columns["case"]].strip(),
                source=source,
                **values,
            )
        )
    if not rows:
        raise DesignCheckError(f"{source}: no action rows after the header")
    return tuple(rows)


def read_fem_actions(path: str | Path) -> tuple[ActionRow, ...]:
    """Read a FEM CSV file; the file name becomes the rows' provenance."""
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as error:
        raise DesignCheckError(f"cannot read FEM actions from {file}: {error}") from error
    return parse_fem_actions(text, source=file.name)


def governing_action(
    rows: Iterable[ActionRow], element: str, component: str
) -> Demand:
    """The largest magnitude of ``component`` on ``element``, and the case that gave it.

    Ties go to the earliest row, so the answer is deterministic for a given
    file. The returned magnitude is unsigned: a check compares capacity to the
    size of the action, not to its sign convention.
    """
    if component not in COMPONENT_UNITS:
        raise DesignCheckError(
            f"unknown action component {component!r}; available components: "
            f"{', '.join(COMPONENT_UNITS)}"
        )
    candidates: Sequence[ActionRow] = [row for row in rows if row.element == element]
    if not candidates:
        raise DesignCheckError(
            f"no FEM rows for element {element!r}"
        )
    worst = max(candidates, key=lambda row: abs(row.component(component)))
    return Demand(
        element=element,
        component=component,
        value=abs(worst.component(component)),
        unit=COMPONENT_UNITS[component],
        case=worst.case,
        source=worst.source or "(unknown source)",
    )
