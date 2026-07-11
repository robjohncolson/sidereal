"""Configuration and stable v1 inventories for the geometry engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
import math
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AspectRule:
    id: str
    angle_deg: float
    orb_deg: float


MAJOR_ASPECT_RULES: tuple[AspectRule, ...] = (
    AspectRule("conjunction", 0.0, 8.0),
    AspectRule("opposition", 180.0, 8.0),
    AspectRule("trine", 120.0, 8.0),
    AspectRule("square", 90.0, 7.0),
    AspectRule("sextile", 60.0, 6.0),
)

BODY_IDS: tuple[str, ...] = (
    "sun",
    "moon",
    "mercury",
    "venus",
    "mars",
    "jupiter",
    "saturn",
    "uranus",
    "neptune",
    "pluto",
    "north_node",
    "south_node",
)

ANGLE_IDS: tuple[str, ...] = ("asc", "mc", "desc", "ic")

# This set mirrors the v1 interpretation-key inventory.  South Node, Desc and
# IC remain calculated/displayed points but deliberately do not create a cloud
# of interpretation gaps or duplicate opposition relationships.
ASPECT_POINT_IDS: frozenset[str] = frozenset(
    (
        "sun",
        "moon",
        "mercury",
        "venus",
        "mars",
        "jupiter",
        "saturn",
        "uranus",
        "neptune",
        "pluto",
        "north_node",
        "asc",
        "mc",
    )
)

PERSONAL_POINT_IDS: frozenset[str] = frozenset(
    ("sun", "moon", "mercury", "venus", "mars", "asc", "mc")
)
LUMINARY_IDS: frozenset[str] = frozenset(("sun", "moon"))
OUTER_PLANET_IDS: frozenset[str] = frozenset(("uranus", "neptune", "pluto"))

POINT_NAMES: dict[str, str] = {
    "sun": "Sun",
    "moon": "Moon",
    "mercury": "Mercury",
    "venus": "Venus",
    "mars": "Mars",
    "jupiter": "Jupiter",
    "saturn": "Saturn",
    "uranus": "Uranus",
    "neptune": "Neptune",
    "pluto": "Pluto",
    "north_node": "North Node",
    "south_node": "South Node",
    "asc": "Ascendant",
    "mc": "Midheaven",
    "desc": "Descendant",
    "ic": "Imum Coeli",
}


@dataclass(frozen=True, slots=True)
class ChartConfig:
    """Runtime choices for a v1 chart.

    The default permits Swiss Ephemeris' documented Moshier fallback so a
    newly installed CLI can calculate modern charts before optional ``.se1``
    files are added.  The actual backend is always recorded; strict callers can
    require those files with ``require_swiss_ephemeris=True``.
    """

    zodiac: str = "midpoint_v1"
    house_system: str = "equal_house_12"
    blend_orb_deg: float = 3.0
    aspect_profile: str = "modern_major"
    aspect_rules: tuple[AspectRule, ...] = MAJOR_ASPECT_RULES
    luminary_orb_bonus_deg: float = 1.0
    outer_pair_orb_penalty_deg: float = 2.0
    assumed_local_time: time = time(12, 0)
    boundary_path: Path | None = None
    ephe_path: Path | None = None
    require_swiss_ephemeris: bool = False
    include_houses: bool = True
    include_patterns: bool = True

    def validate(self) -> None:
        if self.zodiac != "midpoint_v1":
            raise ValueError(f"Unsupported zodiac system: {self.zodiac!r}")
        if self.house_system != "equal_house_12":
            raise ValueError(f"Unsupported house system: {self.house_system!r}")
        if not 0.0 <= self.blend_orb_deg < 180.0:
            raise ValueError("blend_orb_deg must be in [0, 180)")
        if self.assumed_local_time.tzinfo is not None:
            raise ValueError("assumed_local_time must be a naive civil time")
        if not isinstance(self.include_houses, bool):
            raise ValueError("include_houses must be a boolean")
        if not isinstance(self.include_patterns, bool):
            raise ValueError("include_patterns must be a boolean")
        if not isinstance(self.require_swiss_ephemeris, bool):
            raise ValueError("require_swiss_ephemeris must be a boolean")
        if (
            not math.isfinite(self.luminary_orb_bonus_deg)
            or self.luminary_orb_bonus_deg < 0.0
        ):
            raise ValueError("luminary_orb_bonus_deg must be finite and non-negative")
        if (
            not math.isfinite(self.outer_pair_orb_penalty_deg)
            or self.outer_pair_orb_penalty_deg < 0.0
        ):
            raise ValueError("outer_pair_orb_penalty_deg must be finite and non-negative")
        if not self.aspect_rules:
            raise ValueError("aspect_rules cannot be empty")
        for rule in self.aspect_rules:
            if not math.isfinite(rule.angle_deg) or not 0.0 <= rule.angle_deg <= 180.0:
                raise ValueError(f"Invalid aspect angle for {rule.id!r}")
            if not math.isfinite(rule.orb_deg) or rule.orb_deg <= 0.0:
                raise ValueError(f"Invalid aspect orb for {rule.id!r}")
            if rule.orb_deg <= self.outer_pair_orb_penalty_deg:
                raise ValueError(
                    f"Outer-pair penalty leaves no positive orb for {rule.id!r}"
                )


__all__ = [
    "ANGLE_IDS",
    "ASPECT_POINT_IDS",
    "AspectRule",
    "BODY_IDS",
    "ChartConfig",
    "LUMINARY_IDS",
    "MAJOR_ASPECT_RULES",
    "OUTER_PLANET_IDS",
    "PERSONAL_POINT_IDS",
    "POINT_NAMES",
]
