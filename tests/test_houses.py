from __future__ import annotations

import pytest

from sidereal.houses import assign_house, equal_house_cusps


def test_equal_house_cusps_wrap_from_ascendant() -> None:
    assert equal_house_cusps(350.0) == pytest.approx(
        (350, 20, 50, 80, 110, 140, 170, 200, 230, 260, 290, 320)
    )


@pytest.mark.parametrize(
    ("longitude", "expected"),
    [
        (350.0, 1),
        (19.999999, 1),
        (20.0, 2),
        (349.999999, 12),
        (-10.0, 1),
        (710.0, 1),
    ],
)
def test_house_assignment_is_half_open_and_circular(longitude: float, expected: int) -> None:
    assert assign_house(longitude, 350.0) == expected


def test_nonfinite_house_input_is_rejected() -> None:
    with pytest.raises(ValueError, match="finite"):
        assign_house(float("nan"), 0.0)


def test_exact_derived_cusps_are_not_shifted_by_float_noise() -> None:
    # Regression from a real Swiss Ephemeris Ascendant where adding 180° and
    # subtracting again produces 179.99999999999997 rather than exactly 180.
    ascendant = 204.52335108844287
    for index, cusp in enumerate(equal_house_cusps(ascendant), start=1):
        assert assign_house(cusp, ascendant) == index
    descendant = (ascendant + 180.0) % 360.0
    assert assign_house(descendant, ascendant) == 7
