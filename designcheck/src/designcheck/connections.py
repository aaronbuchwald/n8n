"""T4 — ``ScrewConnection``: the thing the proof is *about*.

It exists as one object so a check set can be resolved against it rather than
against loose parameters, and so clause applicability has somewhere to ask its
questions: which material families meet here, how thick is the fastener, how
many shear planes, at what angle to the grain.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .errors import DesignCheckError
from .members import Screw, StructuralMember


@dataclass(frozen=True)
class ScrewConnection:
    """``members`` is ordered head-side first; ``n`` fasteners share the load."""

    name: str
    fastener: Screw
    members: tuple[StructuralMember, ...]
    n: int
    shear_planes: int
    spacing: float  # in-row spacing [mm]
    angle_to_grain: float  # load-to-grain angle [deg]

    #: What applicability predicates match on; sibling connection kinds
    #: (bolted, dowelled, nailed) are future dataclasses with their own tag.
    kind: str = "screw"

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise DesignCheckError(
                "ScrewConnection.name must be non-empty — it is what ties the "
                "connection to the FEM element id"
            )
        if not isinstance(self.fastener, Screw):
            raise DesignCheckError(
                f"ScrewConnection.fastener must be a Screw, got "
                f"{type(self.fastener).__name__} (connection {self.name!r})"
            )
        for count, label in ((self.n, "n"), (self.shear_planes, "shear_planes")):
            if isinstance(count, bool) or not isinstance(count, int) or count < 1:
                raise DesignCheckError(
                    f"ScrewConnection.{label} must be a whole number of at least 1, "
                    f"got {count!r} (connection {self.name!r})"
                )
        # n shear planes need n+1 members: it is the one geometric consistency
        # rule that cannot be recovered from anything else on the object.
        if len(self.members) != self.shear_planes + 1:
            raise DesignCheckError(
                f"ScrewConnection {self.name!r}: {self.shear_planes} shear plane(s) need "
                f"{self.shear_planes + 1} members, got {len(self.members)}"
            )
        if not all(isinstance(member, StructuralMember) for member in self.members):
            raise DesignCheckError(
                f"ScrewConnection {self.name!r}: every member must be a StructuralMember"
            )
        if not math.isfinite(self.spacing) or self.spacing <= 0:
            raise DesignCheckError(
                f"ScrewConnection {self.name!r}: spacing must be positive, got {self.spacing!r}"
            )
        if not math.isfinite(self.angle_to_grain) or not 0 <= self.angle_to_grain <= 180:
            raise DesignCheckError(
                f"ScrewConnection {self.name!r}: angle_to_grain must be 0..180 deg, "
                f"got {self.angle_to_grain!r}"
            )

    @property
    def all_timber(self) -> bool:
        """True when every joined member is timber — what timber clauses demand."""
        return all(member.is_timber for member in self.members)
