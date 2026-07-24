"""T2 — ``Material``: a closed tagged union, one dataclass per family.

Timber has grain-direction strengths, fastener steel has an ultimate tensile
strength, concrete has a cylinder strength; a ``dict[str, float]`` would throw
away exactly the type safety this layer exists to add. Every family shares the
``KbRef`` identity header, so any KB-loaded value can say where it came from.

**Characteristic values only.** No material stores a design value —
``X_d = k_mod · X_k / gamma_M`` happens once, as visible rows of the sheet
(ADR 0022, "Characteristic vs design").
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .errors import DesignCheckError


@dataclass(frozen=True)
class KbRef:
    """Identity header carried by every knowledge-base value.

    ``version`` is the **KB snapshot** the entry was pinned from ("2024.1"),
    not the edition of whatever the entry describes; a building code carries
    its own edition separately.
    """

    address: str
    version: str
    source: str

    def __post_init__(self) -> None:
        for field, value in (
            ("address", self.address),
            ("version", self.version),
            ("source", self.source),
        ):
            if not value.strip():
                raise DesignCheckError(
                    f"KbRef.{field} must be non-empty — a KB value with no "
                    f"{field} cannot be traced (address={self.address!r})"
                )

    @property
    def pin(self) -> str:
        """The gutter form: ``"materials/timber/C24 @2024.1"``."""
        return f"{self.address} @{self.version}"


def _positive(owner: str, **values: float) -> None:
    for name, value in values.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise DesignCheckError(f"{owner}.{name} must be a number, got {value!r}")
        if not math.isfinite(value) or value <= 0:
            raise DesignCheckError(f"{owner}.{name} must be a positive number, got {value!r}")


@dataclass(frozen=True)
class Timber:
    """Solid timber of one strength class — characteristic values, EN 338 shape."""

    ref: KbRef
    grade: str
    rho_k: float  # characteristic density [kg/m^3]
    f_mk: float  # bending strength [MPa]
    f_c0k: float  # compression parallel to grain [MPa]
    E_mean: float  # mean modulus of elasticity [MPa]

    def __post_init__(self) -> None:
        if not self.grade.strip():
            raise DesignCheckError("Timber.grade must be non-empty, e.g. 'C24'")
        _positive(
            "Timber",
            rho_k=self.rho_k,
            f_mk=self.f_mk,
            f_c0k=self.f_c0k,
            E_mean=self.E_mean,
        )


@dataclass(frozen=True)
class FastenerSteel:
    """The steel of a fastener product — its tensile strength drives yielding."""

    ref: KbRef
    f_uk: float  # ultimate tensile strength [MPa]

    def __post_init__(self) -> None:
        _positive("FastenerSteel", f_uk=self.f_uk)


@dataclass(frozen=True)
class Steel:
    """Structural steel — declared so the union is real; no KB entries ship in v1."""

    ref: KbRef
    grade: str
    f_yk: float  # yield strength [MPa]
    f_uk: float  # ultimate tensile strength [MPa]
    E: float  # modulus of elasticity [MPa]

    def __post_init__(self) -> None:
        if not self.grade.strip():
            raise DesignCheckError("Steel.grade must be non-empty, e.g. 'S355'")
        _positive("Steel", f_yk=self.f_yk, f_uk=self.f_uk, E=self.E)


@dataclass(frozen=True)
class Concrete:
    """Concrete — declared so the union is real; no KB entries ship in v1."""

    ref: KbRef
    grade: str
    f_ck: float  # characteristic cylinder compressive strength [MPa]
    E_cm: float  # secant modulus [MPa]

    def __post_init__(self) -> None:
        if not self.grade.strip():
            raise DesignCheckError("Concrete.grade must be non-empty, e.g. 'C30/37'")
        _positive("Concrete", f_ck=self.f_ck, E_cm=self.E_cm)


# Closed per release: adding a family is an additive dataclass plus a KB
# schema, never an edit to an existing one.
Material = Timber | Steel | Concrete | FastenerSteel

MATERIAL_FAMILIES: tuple[type, ...] = (Timber, Steel, Concrete, FastenerSteel)
