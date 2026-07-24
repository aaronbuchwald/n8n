"""T3 — members: authored geometry plus a wired KB material, and the fastener product.

The origin split is the point. A column or beam is *authored* — its section
dimensions and length are project literals — but its material is a resolved KB
value. A screw is a *product*: geometry and steel grade are looked up whole,
because a 6.0 x 120 countersunk screw is not something a project invents.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .errors import DesignCheckError
from .materials import FastenerSteel, KbRef, Material, Timber

# What a `StructuralMember` can be for. Kept closed: clause applicability and
# the resolver's member-role reasoning both read it.
MEMBER_ROLES = ("column", "beam")


def _positive(owner: str, **values: float) -> None:
    for name, value in values.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise DesignCheckError(f"{owner}.{name} must be a number, got {value!r}")
        if not math.isfinite(value) or value <= 0:
            raise DesignCheckError(f"{owner}.{name} must be a positive number, got {value!r}")


@dataclass(frozen=True)
class RectSection:
    """A rectangular cross-section [mm]."""

    b: float  # width [mm]
    h: float  # depth [mm]

    def __post_init__(self) -> None:
        _positive("RectSection", b=self.b, h=self.h)

    @property
    def area(self) -> float:
        """Gross area [mm^2]."""
        return self.b * self.h


@dataclass(frozen=True)
class StructuralMember:
    """A column or beam: ``name`` ties it to the FEM model's element ids."""

    name: str
    role: str
    section: RectSection
    material: Material
    length: float  # [mm]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise DesignCheckError(
                "StructuralMember.name must be non-empty — it is what ties the member "
                "to the FEM element id"
            )
        if self.role not in MEMBER_ROLES:
            raise DesignCheckError(
                f"StructuralMember.role {self.role!r} is not one of {', '.join(MEMBER_ROLES)} "
                f"(member {self.name!r})"
            )
        if not isinstance(self.section, RectSection):
            raise DesignCheckError(
                f"StructuralMember.section must be a RectSection, got "
                f"{type(self.section).__name__} (member {self.name!r})"
            )
        _positive(f"StructuralMember {self.name!r}", length=self.length)

    @property
    def is_timber(self) -> bool:
        return isinstance(self.material, Timber)


@dataclass(frozen=True)
class Screw:
    """A screw product, looked up whole: geometry and steel arrive together."""

    ref: KbRef
    d: float  # outer thread diameter [mm]
    L: float  # length [mm]
    steel: FastenerSteel

    def __post_init__(self) -> None:
        _positive(f"Screw {self.ref.address!r}", d=self.d, L=self.L)
        if not isinstance(self.steel, FastenerSteel):
            raise DesignCheckError(
                f"Screw.steel must be a FastenerSteel, got {type(self.steel).__name__} "
                f"(screw {self.ref.address!r})"
            )
        if self.L <= self.d:
            raise DesignCheckError(
                f"Screw {self.ref.address!r}: length L={self.L} mm must exceed diameter "
                f"d={self.d} mm"
            )

    @property
    def f_uk(self) -> float:
        """Its steel's ultimate tensile strength [MPa] — the value clauses read."""
        return self.steel.f_uk
