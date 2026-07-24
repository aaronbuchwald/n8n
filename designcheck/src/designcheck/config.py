"""T1 — ``DesignConfig``: the run-level knobs, and the only type that is entirely literals."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .errors import DesignCheckError

# Code-agnostic names for the "how long does the load act" knob every code has
# in some form; the chosen code interprets them (EC5 reads them into Table 3.1).
LOAD_DURATIONS = ("permanent", "long", "medium", "short", "instantaneous")

# The only units policy in v1: N, mm, MPa. Named rather than assumed so a
# second policy is an added constant, not a rewrite.
UNITS_POLICIES = ("SI-structural",)


@dataclass(frozen=True)
class DesignConfig:
    """Per-graph configuration: flat scalars, so every field is a plain widget.

    ``code`` is a KB address with an optional pinned edition
    (``"codes/ec5"`` or ``"codes/ec5@2004-A2-2014"``); pinning makes the run
    refuse a KB whose EC5 entry has since moved to another edition.
    ``as_of`` is caller-provided and never derived from the clock — the
    artifact must not re-render differently tomorrow.
    """

    code: str
    service_class: int
    load_duration: str
    target_utilisation: float
    as_of: str
    units: str = "SI-structural"
    project: str = ""
    kb_overlays: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise DesignCheckError("DesignConfig.code must be a KB address, e.g. 'codes/ec5'")
        if isinstance(self.service_class, bool) or not isinstance(self.service_class, int):
            raise DesignCheckError(
                f"DesignConfig.service_class must be a whole number, got {self.service_class!r}"
            )
        if self.service_class < 1:
            raise DesignCheckError(
                f"DesignConfig.service_class must be at least 1, got {self.service_class}"
            )
        if self.load_duration not in LOAD_DURATIONS:
            raise DesignCheckError(
                f"DesignConfig.load_duration {self.load_duration!r} is not one of "
                f"{', '.join(LOAD_DURATIONS)}"
            )
        if not math.isfinite(self.target_utilisation) or not 0 < self.target_utilisation <= 1:
            raise DesignCheckError(
                f"DesignConfig.target_utilisation must be in (0, 1] — it is 1/SF — "
                f"got {self.target_utilisation!r}"
            )
        if self.units not in UNITS_POLICIES:
            raise DesignCheckError(
                f"DesignConfig.units {self.units!r} is not one of {', '.join(UNITS_POLICIES)}"
            )
        if not self.as_of.strip():
            raise DesignCheckError(
                "DesignConfig.as_of must be a caller-provided date string; it is a pin, "
                "not a clock reading"
            )

    @property
    def code_address(self) -> str:
        """``code`` with any ``@edition`` pin removed."""
        return self.code.split("@", 1)[0]

    @property
    def code_edition(self) -> str:
        """The pinned edition, or ``""`` when the config takes whatever the KB ships."""
        _, _, edition = self.code.partition("@")
        return edition

    @property
    def safety_factor(self) -> float:
        """The project margin as engineers state it: ``SF = 1 / eta_max``."""
        return 1.0 / self.target_utilisation
