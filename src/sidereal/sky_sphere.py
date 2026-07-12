"""Pure reference math for the simplified v2.1 rotating celestial sphere."""

from __future__ import annotations

import math
from typing import Iterable

from .zodiac.base import normalize_longitude


Vector3 = tuple[float, float, float]

NOON_ANCHOR_DEG = 90.0
WORLD_FRAME_TILT_DEG = 90.0
DEFAULT_HORIZON_EPSILON = 1e-9


def ecliptic_to_vec(lon_deg: float, lat_deg: float = 0.0) -> Vector3:
    """Map ecliptic longitude/latitude to a sphere-local unit direction.

    The local ecliptic is the XZ great circle and local +Y is ecliptic north.
    Longitudes are normalized; latitude must use its conventional [-90, 90]
    degree range.
    """

    longitude = normalize_longitude(_finite_number(lon_deg, "lon_deg"))
    latitude = _finite_number(lat_deg, "lat_deg")
    if not -90.0 <= latitude <= 90.0:
        raise ValueError("lat_deg must be in [-90, 90]")
    azimuth = math.radians(longitude)
    elevation = math.radians(latitude)
    cos_elevation = math.cos(elevation)
    return (
        cos_elevation * math.cos(azimuth),
        math.sin(elevation),
        cos_elevation * -math.sin(azimuth),
    )


def sphere_angle_deg(
    spin_phase: float,
    sun_lon_deg: float,
    *,
    noon_anchor_deg: float = NOON_ANCHOR_DEG,
) -> float:
    """Return normalized sphere-local yaw for a diurnal cycle.

    ``spin_phase == 0`` is solar noon and ``spin_phase == 0.5`` is the
    opposite half-turn. Epoch solar longitude only anchors the rigid sphere;
    theatre phase does not alter it.
    """

    phase = _finite_number(spin_phase, "spin_phase")
    if not 0.0 <= phase < 1.0:
        raise ValueError("spin_phase must be in [0, 1)")
    sun_longitude = normalize_longitude(
        _finite_number(sun_lon_deg, "sun_lon_deg")
    )
    noon_anchor = normalize_longitude(
        _finite_number(noon_anchor_deg, "noon_anchor_deg")
    )
    return normalize_longitude(
        noon_anchor - sun_longitude + phase * 360.0
    )


def apply_spin(vec: Iterable[float], angle_deg: float) -> Vector3:
    """Rigidly rotate a sphere-local direction into the simplified world frame.

    The transform is ``R_x(+90 deg) * R_y(angle_deg)``. The fixed X tilt maps
    the local polar axis onto world +Z so rotation changes world Y elevation;
    a bare Y rotation would leave every latitude-zero point on the horizon.
    """

    x, y, z = _vector3(vec)
    angle = math.radians(
        normalize_longitude(_finite_number(angle_deg, "angle_deg"))
    )
    cosine = math.cos(angle)
    sine = math.sin(angle)
    spun_x = cosine * x + sine * z
    spun_z = -sine * x + cosine * z
    # R_x(+90 degrees): (x, y, z) -> (x, -z, y).
    return (spun_x, -spun_z, y)


def elevation_deg(vec: Iterable[float]) -> float:
    """Return world-frame elevation in degrees for a non-zero direction."""

    x, y, z = _vector3(vec)
    horizontal = math.hypot(x, z)
    if horizontal == 0.0 and y == 0.0:
        raise ValueError("vec must be non-zero")
    return math.degrees(math.atan2(y, horizontal))


def above_horizon(
    vec: Iterable[float],
    y_horizon: float = 0.0,
    eps: float = DEFAULT_HORIZON_EPSILON,
) -> bool:
    """Return whether a world direction clears the horizontal Y threshold."""

    _, y, _ = _vector3(vec)
    horizon = _finite_number(y_horizon, "y_horizon")
    epsilon = _finite_number(eps, "eps")
    if epsilon < 0.0:
        raise ValueError("eps must be non-negative")
    return y > horizon + epsilon


def sun_world_dir(
    sun_lon_deg: float,
    spin_phase: float,
    *,
    noon_anchor_deg: float = NOON_ANCHOR_DEG,
) -> Vector3:
    """Return the latitude-zero Sun direction after the diurnal transform."""

    local_direction = ecliptic_to_vec(sun_lon_deg)
    angle = sphere_angle_deg(
        spin_phase,
        sun_lon_deg,
        noon_anchor_deg=noon_anchor_deg,
    )
    return apply_spin(local_direction, angle)


def _vector3(vec: Iterable[float]) -> Vector3:
    try:
        values = tuple(vec)
    except TypeError as exc:
        raise TypeError("vec must be an iterable of three numbers") from exc
    if len(values) != 3:
        raise ValueError("vec must contain exactly three values")
    return (
        _finite_number(values[0], "vec[0]"),
        _finite_number(values[1], "vec[1]"),
        _finite_number(values[2], "vec[2]"),
    )


def _finite_number(value: float, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


__all__ = [
    "DEFAULT_HORIZON_EPSILON",
    "NOON_ANCHOR_DEG",
    "Vector3",
    "WORLD_FRAME_TILT_DEG",
    "above_horizon",
    "apply_spin",
    "ecliptic_to_vec",
    "elevation_deg",
    "sphere_angle_deg",
    "sun_world_dir",
]
