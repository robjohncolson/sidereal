"""Unequal 13-sign Midpoint v1 mapper in the ecliptic J2000 frame."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import site
import sys
import sysconfig
from typing import Any

from .base import ZodiacPlacement, forward_arc, normalize_longitude


BOUNDARY_FILENAME = "midpoint_j2000_v1.json"
EXPECTED_SIGN_IDS: tuple[str, ...] = (
    "aries",
    "taurus",
    "gemini",
    "cancer",
    "leo",
    "virgo",
    "libra",
    "scorpio",
    "ophiuchus",
    "sagittarius",
    "capricorn",
    "aquarius",
    "pisces",
)
EXPECTED_STARTS: tuple[float, ...] = (
    31.2816, 51.0083, 87.8655, 117.3194, 134.4689, 172.8884,
    222.6069, 241.4853, 254.7132, 267.0711, 300.4622, 326.1312,
    349.2959,
)
EXPECTED_LENGTHS: tuple[float, ...] = (
    19.7267, 36.8572, 29.4539, 17.1495, 38.4195, 49.7185,
    18.8784, 13.2279, 12.3578, 33.3912, 25.6690, 23.1646,
    41.9857,
)
EXPECTED_DOI = "10.5281/zenodo.20747017"
EXPECTED_LICENSE_ID = "cc-by-nc-nd-4.0"


@dataclass(frozen=True, slots=True)
class BoundarySign:
    id: str
    name: str
    order: int
    start_deg: float
    declared_length_deg: float


class MidpointZodiac:
    """Map J2000 ecliptic longitude into the canonical Midpoint table.

    Published values are rounded to four decimals.  Three adjacent declared
    lengths therefore differ from the next published start by 0.0001 degree.
    Membership uses consecutive starts as the canonical half-open partition;
    declared lengths are retained and validated within the SPEC's tolerance.
    This prevents microscopic gaps or overlaps without changing a boundary.
    """

    id = "midpoint_v1"

    def __init__(
        self,
        signs: tuple[BoundarySign, ...],
        *,
        boundary_version: str,
        source_path: Path,
        source_doi: str,
        license_id: str,
        content_sha256: str,
    ):
        _validate_signs(signs)
        self.signs = signs
        self.boundary_version = boundary_version
        self.source_path = source_path
        self.source_doi = source_doi
        self.license_id = license_id
        self.content_sha256 = content_sha256
        self._starts = tuple(sign.start_deg for sign in signs)

    @classmethod
    def from_file(cls, path: str | Path) -> "MidpointZodiac":
        source_path = Path(path).expanduser().resolve()
        try:
            content = source_path.read_bytes()
            payload = json.loads(content.decode("utf-8"))
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"Midpoint boundary file not found: {source_path}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid boundary JSON in {source_path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("Boundary JSON root must be an object")
        if payload.get("id") != cls.id:
            raise ValueError(f"Expected boundary id {cls.id!r}, got {payload.get('id')!r}")
        if payload.get("frame") != "ecliptic_j2000":
            raise ValueError("Midpoint v1 boundaries must declare frame='ecliptic_j2000'")
        if type(payload.get("version")) is not int or payload["version"] != 1:
            raise ValueError("Midpoint v1 boundaries must declare integer version=1")
        source = payload.get("source")
        if not isinstance(source, dict) or source.get("doi") != EXPECTED_DOI:
            raise ValueError(f"Midpoint v1 boundaries must cite DOI {EXPECTED_DOI}")
        if payload.get("license_id") != EXPECTED_LICENSE_ID:
            raise ValueError(
                f"Midpoint v1 boundaries must declare license_id={EXPECTED_LICENSE_ID!r}"
            )
        if not isinstance(payload.get("license"), str) or not payload["license"].strip():
            raise ValueError("Midpoint v1 boundaries must declare a non-empty license")
        raw_signs = payload.get("signs")
        if not isinstance(raw_signs, list):
            raise ValueError("Boundary JSON signs must be an array")
        signs = tuple(_parse_sign(item) for item in raw_signs)
        return cls(
            signs,
            boundary_version="1",
            source_path=source_path,
            source_doi=EXPECTED_DOI,
            license_id=EXPECTED_LICENSE_ID,
            content_sha256=hashlib.sha256(content).hexdigest(),
        )

    @classmethod
    def load_default(cls, explicit_path: str | Path | None = None) -> "MidpointZodiac":
        return cls.from_file(resolve_boundary_path(explicit_path))

    def map(self, longitude_deg: float, *, blend_orb_deg: float = 3.0) -> ZodiacPlacement:
        if not math.isfinite(longitude_deg):
            raise ValueError("longitude must be finite")
        if not math.isfinite(blend_orb_deg) or blend_orb_deg < 0.0:
            raise ValueError("blend_orb_deg must be a finite non-negative number")
        longitude = normalize_longitude(longitude_deg)
        index = bisect_right(self._starts, longitude) - 1
        if index < 0:
            index = len(self.signs) - 1
        sign = self.signs[index]
        next_index = (index + 1) % len(self.signs)
        previous_index = (index - 1) % len(self.signs)
        segment_length = forward_arc(sign.start_deg, self.signs[next_index].start_deg)
        degree = forward_arc(sign.start_deg, longitude)
        # bisect membership and normalized sorted starts guarantee this.  Keep a
        # guard because silently mapping corrupt boundary data would be worse.
        if not 0.0 <= degree < segment_length:
            raise RuntimeError(f"Longitude {longitude} did not fall in a Midpoint segment")

        distance_to_start = degree
        distance_to_end = segment_length - degree
        if distance_to_start <= distance_to_end:
            distance = distance_to_start
            secondary = self.signs[previous_index].id
        else:
            distance = distance_to_end
            secondary = self.signs[next_index].id
        blend = distance <= blend_orb_deg
        return ZodiacPlacement(
            sign=sign.id,
            degree_in_sign=degree,
            blend=blend,
            secondary_sign=secondary if blend else None,
            distance_to_boundary=distance,
        )


def resolve_boundary_path(explicit_path: str | Path | None = None) -> Path:
    """Locate the one canonical root-data boundary file in editable/wheel installs."""

    if explicit_path is not None:
        return _required_boundary_file(Path(explicit_path), "explicit boundary path")
    environment_path = os.environ.get("SIDEREAL_BOUNDARY_PATH")
    if environment_path:
        return _required_boundary_file(
            Path(environment_path), "SIDEREAL_BOUNDARY_PATH"
        )
    project_root = Path(__file__).resolve().parents[3]
    data_prefix = Path(sysconfig.get_path("data"))
    project_candidate = project_root / "data" / "boundaries" / BOUNDARY_FILENAME
    active_candidate = data_prefix / "share" / "sidereal" / "boundaries" / BOUNDARY_FILENAME
    user_candidate = (
        Path(site.USER_BASE) / "share" / "sidereal" / "boundaries" / BOUNDARY_FILENAME
    )
    if sys.prefix != sys.base_prefix:
        installed_candidates = (active_candidate,)
    elif site.ENABLE_USER_SITE:
        installed_candidates = (user_candidate, active_candidate)
    else:
        installed_candidates = (active_candidate,)
    candidates = (project_candidate, *installed_candidates)

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    rendered = "\n  - ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"Could not locate {BOUNDARY_FILENAME}; searched:\n  - {rendered}")


def _as_boundary_file(path: Path) -> Path:
    expanded = path.expanduser()
    return expanded / BOUNDARY_FILENAME if expanded.is_dir() else expanded


def _required_boundary_file(path: Path, label: str) -> Path:
    candidate = _as_boundary_file(path)
    if not candidate.is_file():
        raise FileNotFoundError(f"{label} is not a boundary JSON file: {candidate}")
    return candidate.resolve()


def _parse_sign(item: Any) -> BoundarySign:
    if not isinstance(item, dict):
        raise ValueError("Each boundary sign must be an object")
    try:
        return BoundarySign(
            id=str(item["id"]),
            name=str(item["name"]),
            order=int(item["order"]),
            start_deg=float(item["start_deg"]),
            declared_length_deg=float(item["length_deg"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Malformed boundary sign: {item!r}") from exc


def _validate_signs(signs: tuple[BoundarySign, ...]) -> None:
    if len(signs) != len(EXPECTED_SIGN_IDS):
        raise ValueError(f"Midpoint v1 requires {len(EXPECTED_SIGN_IDS)} signs")
    if tuple(sign.id for sign in signs) != EXPECTED_SIGN_IDS:
        raise ValueError("Midpoint sign ids/order do not match the canonical v1 inventory")
    if tuple(sign.order for sign in signs) != tuple(range(1, 14)):
        raise ValueError("Boundary sign order values must be 1 through 13")
    starts = tuple(sign.start_deg for sign in signs)
    if any(not math.isfinite(value) or not 0.0 <= value < 360.0 for value in starts):
        raise ValueError("Boundary starts must be finite values in [0, 360)")
    if any(right <= left for left, right in zip(starts, starts[1:])):
        raise ValueError("Boundary starts must be strictly increasing")
    if any(not math.isfinite(sign.declared_length_deg) or sign.declared_length_deg <= 0.0 for sign in signs):
        raise ValueError("Boundary lengths must be finite positive values")
    if any(
        not math.isclose(sign.start_deg, expected, rel_tol=0.0, abs_tol=1e-9)
        for sign, expected in zip(signs, EXPECTED_STARTS, strict=True)
    ):
        raise ValueError("Midpoint v1 start longitudes do not match the canonical table")
    if any(
        not math.isclose(sign.declared_length_deg, expected, rel_tol=0.0, abs_tol=1e-9)
        for sign, expected in zip(signs, EXPECTED_LENGTHS, strict=True)
    ):
        raise ValueError("Midpoint v1 lengths do not match the canonical table")
    if not math.isclose(sum(sign.declared_length_deg for sign in signs), 360.0, abs_tol=0.001):
        raise ValueError("Declared Midpoint sign lengths must sum to 360 degrees (±0.001)")
    for index, sign in enumerate(signs):
        next_start = signs[(index + 1) % len(signs)].start_deg
        effective_length = forward_arc(sign.start_deg, next_start)
        if not math.isclose(effective_length, sign.declared_length_deg, abs_tol=0.001):
            raise ValueError(
                f"Boundary length mismatch for {sign.id}: declared {sign.declared_length_deg}, "
                f"starts imply {effective_length}"
            )


__all__ = [
    "BOUNDARY_FILENAME",
    "BoundarySign",
    "EXPECTED_DOI",
    "EXPECTED_LENGTHS",
    "EXPECTED_LICENSE_ID",
    "EXPECTED_SIGN_IDS",
    "EXPECTED_STARTS",
    "MidpointZodiac",
    "resolve_boundary_path",
]
