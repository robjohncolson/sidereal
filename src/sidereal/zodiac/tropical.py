"""Classic equal-sign tropical zodiac mapping in the ecliptic-of-date frame."""

from __future__ import annotations

import math

from .base import ZodiacPlacement, normalize_longitude


TROPICAL_SIGNS: tuple[str, ...] = (
    "aries",
    "taurus",
    "gemini",
    "cancer",
    "leo",
    "virgo",
    "libra",
    "scorpio",
    "sagittarius",
    "capricorn",
    "aquarius",
    "pisces",
)


class TropicalZodiac:
    """Map tropical longitude of date into twelve half-open 30-degree signs."""

    id = "tropical"
    boundary_version = "equal_12_v1"
    frame = "ecliptic_of_date"

    def map(
        self,
        longitude_deg: float,
        *,
        blend_orb_deg: float = 3.0,
    ) -> ZodiacPlacement:
        if not math.isfinite(longitude_deg):
            raise ValueError("longitude must be finite")
        if not math.isfinite(blend_orb_deg) or blend_orb_deg < 0.0:
            raise ValueError("blend_orb_deg must be a finite non-negative number")

        longitude = normalize_longitude(longitude_deg)
        index = min(int(longitude // 30.0), len(TROPICAL_SIGNS) - 1)
        degree = longitude - index * 30.0
        distance_to_start = degree
        distance_to_end = 30.0 - degree
        if distance_to_start <= distance_to_end:
            distance = distance_to_start
            secondary = TROPICAL_SIGNS[(index - 1) % len(TROPICAL_SIGNS)]
        else:
            distance = distance_to_end
            secondary = TROPICAL_SIGNS[(index + 1) % len(TROPICAL_SIGNS)]
        blend = distance <= blend_orb_deg
        return ZodiacPlacement(
            sign=TROPICAL_SIGNS[index],
            degree_in_sign=degree,
            blend=blend,
            secondary_sign=secondary if blend else None,
            distance_to_boundary=distance,
        )


__all__ = ["TROPICAL_SIGNS", "TropicalZodiac"]
