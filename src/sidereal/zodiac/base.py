"""Interface shared by zodiac mapping systems."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ZodiacPlacement:
    sign: str
    degree_in_sign: float
    blend: bool
    secondary_sign: str | None
    distance_to_boundary: float


@runtime_checkable
class ZodiacMap(Protocol):
    id: str
    boundary_version: str

    def map(self, longitude_deg: float, *, blend_orb_deg: float = 3.0) -> ZodiacPlacement:
        """Map a longitude in this system's declared frame."""


def normalize_longitude(longitude_deg: float) -> float:
    value = float(longitude_deg) % 360.0
    # Avoid serializing the unusual negative-zero value.
    return 0.0 if value == 0.0 else value


def forward_arc(start_deg: float, end_deg: float) -> float:
    return (end_deg - start_deg) % 360.0


__all__ = ["ZodiacMap", "ZodiacPlacement", "forward_arc", "normalize_longitude"]
