"""Pure equal-house geometry helpers."""

from __future__ import annotations

import math

from .zodiac.base import normalize_longitude


HOUSE_COUNT = 12
HOUSE_SPAN_DEG = 30.0


def equal_house_cusps(ascendant_longitude_deg: float) -> tuple[float, ...]:
    """Return twelve 30-degree tropical cusps beginning at Ascendant."""

    if not math.isfinite(ascendant_longitude_deg):
        raise ValueError("Ascendant longitude must be finite")
    ascendant = normalize_longitude(ascendant_longitude_deg)
    return tuple(normalize_longitude(ascendant + index * HOUSE_SPAN_DEG) for index in range(HOUSE_COUNT))


def assign_house(longitude_deg: float, ascendant_longitude_deg: float) -> int:
    """Assign a tropical-of-date longitude to a half-open equal house."""

    if not math.isfinite(longitude_deg) or not math.isfinite(ascendant_longitude_deg):
        raise ValueError("House assignment longitudes must be finite")
    offset = (normalize_longitude(longitude_deg) - normalize_longitude(ascendant_longitude_deg)) % 360.0
    # Swiss Ephemeris can represent a mathematically exact derived cusp a few
    # ulps below its 30-degree multiple (for example, Desc - Asc can become
    # 179.99999999999997).  Snap only sub-nanodegree noise to the exact cusp so
    # half-open membership does not put that point in the preceding house.
    nearest_cusp = round(offset / HOUSE_SPAN_DEG) * HOUSE_SPAN_DEG
    if math.isclose(offset, nearest_cusp, rel_tol=0.0, abs_tol=1e-9):
        offset = nearest_cusp % 360.0
    return int(offset // HOUSE_SPAN_DEG) + 1


__all__ = ["HOUSE_COUNT", "HOUSE_SPAN_DEG", "assign_house", "equal_house_cusps"]
