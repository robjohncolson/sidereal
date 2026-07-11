"""Public, immutable data models for chart calculation.

The models in this module deliberately contain geometry only.  Interpretation
records live in :mod:`sidereal.interpret` and are joined after a chart has been
computed.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, time
from enum import Enum
import json
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class MomentInput:
    """A civil moment supplied by the user.

    ``local_time=None`` is meaningful rather than an error: calculation uses
    local noon as an explicitly recorded representative time, while angles and
    houses remain absent.
    """

    local_date: date
    local_time: time | None
    tz: str
    lat: float | None = None
    lon: float | None = None
    label: str = ""
    fold: int | None = None


@dataclass(frozen=True, slots=True)
class PointPos:
    """Calculated position of a body or angle."""

    id: str
    name: str
    kind: str
    lon_date: float
    lon_j2000: float
    lat: float
    speed_long: float
    retro: bool
    sign: str
    degree_in_sign: float
    house: int | None
    blend: bool
    secondary_sign: str | None

    @property
    def retrograde(self) -> bool:
        """Readable alias retained for report callers."""

        return self.retro


@dataclass(frozen=True, slots=True)
class HouseCusp:
    """One of twelve equal-house cusps."""

    number: int
    lon_date: float
    lon_j2000: float
    sign: str
    degree_in_sign: float
    blend: bool
    secondary_sign: str | None

    @property
    def house(self) -> int:
        """Alias convenient for renderers."""

        return self.number


@dataclass(frozen=True, slots=True)
class AspectHit:
    """A major angular relationship between two canonical point ids."""

    body_a: str
    body_b: str
    aspect_id: str
    separation: float
    orb_used: float
    exactness: float
    force: float
    applying: bool | None


@dataclass(frozen=True, slots=True)
class PatternHit:
    """A structural relationship built from placements/aspects."""

    pattern_id: str
    members: tuple[str, ...]
    sign: str | None = None
    apex: str | None = None


@dataclass(frozen=True, slots=True)
class ChartMeta:
    """Provenance required to reproduce a chart."""

    input: MomentInput
    time_known: bool
    location_known: bool
    local_datetime: datetime
    utc_datetime: datetime
    jd_ut: float
    jd_et: float
    zodiac_system: str
    house_system: str | None
    aspect_profile: str
    swe_version: str
    pyswisseph_version: str
    boundary_version: str
    ephemeris_backend: str
    calculation_time_assumption: str | None = None
    warnings: tuple[str, ...] = ()
    blend_orb_deg: float = 3.0
    aspect_rules: tuple[tuple[str, float, float], ...] = ()
    luminary_orb_bonus_deg: float = 1.0
    outer_pair_orb_penalty_deg: float = 2.0
    houses_enabled: bool = True
    patterns_enabled: bool = True
    ephemeris_flags: tuple[str, ...] = ()
    house_frame_method: str | None = None
    boundary_source_doi: str = ""
    boundary_license_id: str = ""
    boundary_sha256: str = ""


@dataclass(frozen=True, slots=True)
class Chart:
    """Complete astronomical/geometry chart, before interpretation joins."""

    meta: ChartMeta
    points: tuple[PointPos, ...]
    cusps: tuple[HouseCusp, ...] | None
    aspects: tuple[AspectHit, ...]
    patterns: tuple[PatternHit, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation preserving dataclass field order."""

        value = _json_value(self)
        if not isinstance(value, dict):  # pragma: no cover - structural guard
            raise TypeError("Chart did not serialize to an object")
        return value

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialize this chart deterministically."""

        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            indent=indent,
            sort_keys=True,
            allow_nan=False,
        )


def _json_value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


__all__ = [
    "AspectHit",
    "Chart",
    "ChartMeta",
    "HouseCusp",
    "MomentInput",
    "PatternHit",
    "PointPos",
]
