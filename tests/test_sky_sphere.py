from __future__ import annotations

import math
from typing import Callable

import pytest

from sidereal.sky_sphere import (
    NOON_ANCHOR_DEG,
    above_horizon,
    apply_spin,
    ecliptic_to_vec,
    elevation_deg,
    sphere_angle_deg,
    sun_world_dir,
)


SUN_LONGITUDE_DEG = 109.0


def _angular_separation_deg(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    cosine = sum(
        a * b for a, b in zip(left, right, strict=True)
    ) / (left_norm * right_norm)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


@pytest.mark.parametrize(
    ("longitude", "latitude"),
    [(0.0, 0.0), (90.0, 0.0), (109.0, 5.0), (350.0, -30.0)],
)
def test_ecliptic_to_vec_is_unit_length(
    longitude: float,
    latitude: float,
) -> None:
    vector = ecliptic_to_vec(longitude, latitude)

    assert math.sqrt(sum(value * value for value in vector)) == pytest.approx(
        1.0,
        abs=1e-12,
    )


def test_ecliptic_longitudes_zero_and_ninety_are_distinct() -> None:
    assert ecliptic_to_vec(0.0) == pytest.approx((1.0, 0.0, 0.0), abs=1e-12)
    assert ecliptic_to_vec(90.0) == pytest.approx((0.0, 0.0, -1.0), abs=1e-12)


def test_noon_anchor_and_half_turn_have_fixed_angles() -> None:
    assert NOON_ANCHOR_DEG == 90.0
    assert sphere_angle_deg(0.0, SUN_LONGITUDE_DEG) == pytest.approx(341.0)
    assert sphere_angle_deg(0.5, SUN_LONGITUDE_DEG) == pytest.approx(161.0)


def test_sun_elevation_is_maximal_at_noon_and_minimal_at_half_turn() -> None:
    phases = tuple(index / 8.0 for index in range(8))
    elevations = {
        phase: elevation_deg(sun_world_dir(SUN_LONGITUDE_DEG, phase))
        for phase in phases
    }

    assert elevations[0.0] == pytest.approx(90.0, abs=1e-12)
    assert elevations[0.0] == pytest.approx(max(elevations.values()))
    assert elevations[0.5] == pytest.approx(-90.0, abs=1e-12)
    assert elevations[0.5] == pytest.approx(min(elevations.values()))


def test_sun_crosses_the_horizon_between_noon_and_half_turn() -> None:
    noon = sun_world_dir(SUN_LONGITUDE_DEG, 0.0)
    midnight = sun_world_dir(SUN_LONGITUDE_DEG, 0.5)

    assert above_horizon(noon) is True
    assert above_horizon(midnight) is False


def test_colocated_points_remain_colocated_after_spin() -> None:
    first = ecliptic_to_vec(42.0, 3.0)
    second = ecliptic_to_vec(42.0, 3.0)
    angle = sphere_angle_deg(0.375, SUN_LONGITUDE_DEG)

    assert apply_spin(first, angle) == pytest.approx(
        apply_spin(second, angle),
        abs=1e-12,
    )


def test_spin_preserves_fixed_angular_separation() -> None:
    first = ecliptic_to_vec(12.0, 4.0)
    second = ecliptic_to_vec(97.0, -2.0)
    before = _angular_separation_deg(first, second)
    angle = sphere_angle_deg(0.625, SUN_LONGITUDE_DEG)

    after = _angular_separation_deg(
        apply_spin(first, angle),
        apply_spin(second, angle),
    )

    assert after == pytest.approx(before, abs=1e-12)


@pytest.mark.parametrize("invalid", [math.inf, -math.inf, math.nan])
def test_public_helpers_reject_non_finite_inputs(invalid: float) -> None:
    calls: tuple[Callable[[], object], ...] = (
        lambda: ecliptic_to_vec(invalid),
        lambda: ecliptic_to_vec(0.0, invalid),
        lambda: sphere_angle_deg(invalid, 0.0),
        lambda: sphere_angle_deg(0.0, invalid),
        lambda: sphere_angle_deg(0.0, 0.0, noon_anchor_deg=invalid),
        lambda: apply_spin((1.0, invalid, 0.0), 0.0),
        lambda: apply_spin((1.0, 0.0, 0.0), invalid),
        lambda: elevation_deg((1.0, 0.0, invalid)),
        lambda: above_horizon((1.0, 0.0, invalid)),
        lambda: above_horizon((1.0, 0.0, 0.0), y_horizon=invalid),
        lambda: above_horizon((1.0, 0.0, 0.0), eps=invalid),
    )

    for call in calls:
        with pytest.raises(ValueError, match="must be finite"):
            call()


@pytest.mark.parametrize("phase", [-0.1, 1.0, 2.0])
def test_sphere_angle_rejects_phase_outside_cycle(phase: float) -> None:
    with pytest.raises(ValueError, match=r"spin_phase must be in \[0, 1\)"):
        sphere_angle_deg(phase, SUN_LONGITUDE_DEG)


def test_latitude_vector_and_horizon_validation_errors_are_clear() -> None:
    with pytest.raises(ValueError, match=r"lat_deg must be in \[-90, 90\]"):
        ecliptic_to_vec(0.0, 90.1)
    with pytest.raises(ValueError, match="vec must contain exactly three values"):
        apply_spin((1.0, 0.0), 0.0)
    with pytest.raises(ValueError, match="vec must be non-zero"):
        elevation_deg((0.0, 0.0, 0.0))
    with pytest.raises(ValueError, match="eps must be non-negative"):
        above_horizon((0.0, 1.0, 0.0), eps=-1e-9)
