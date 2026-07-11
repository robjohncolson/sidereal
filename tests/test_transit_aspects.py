from __future__ import annotations

import pytest

from sidereal.aspects import compute_transit_aspects
from sidereal.types import PointPos


def _point(
    point_id: str,
    longitude: float,
    *,
    j2000: float | None = None,
    speed: float = 0.0,
    j2000_speed: float | None = None,
    kind: str = "body",
) -> PointPos:
    return PointPos(
        id=point_id,
        name=point_id,
        kind=kind,
        lon_date=longitude,
        lon_j2000=longitude if j2000 is None else j2000,
        lat=0.0,
        speed_long=speed,
        retro=speed < 0.0,
        sign="aries",
        degree_in_sign=0.0,
        house=None,
        blend=False,
        secondary_sign=None,
        speed_long_j2000=j2000_speed,
    )


def test_cross_aspects_keep_roles_and_allow_same_body() -> None:
    hits = compute_transit_aspects(
        (_point("sun", 1.0, speed=1.0),),
        (_point("sun", 0.0, speed=99.0),),
    )

    assert len(hits) == 1
    assert (hits[0].transit_body, hits[0].natal_point) == ("sun", "sun")
    assert hits[0].aspect_id == "conjunction"
    assert hits[0].exactness == pytest.approx(1.0)
    assert hits[0].applying is False


def test_cross_applying_treats_natal_position_as_fixed() -> None:
    natal = (_point("venus", 0.0, speed=99.0),)
    applying = compute_transit_aspects(
        (_point("mars", 87.0, speed=1.0),),
        natal,
    )[0]
    separating = compute_transit_aspects(
        (_point("mars", 93.0, speed=1.0),),
        natal,
    )[0]

    assert applying.aspect_id == separating.aspect_id == "square"
    assert applying.applying is True
    assert separating.applying is False


def test_cross_aspects_reuse_luminary_and_outer_orb_modifiers() -> None:
    luminary = compute_transit_aspects(
        (_point("sun", 0.0),),
        (_point("venus", 66.5),),
    )[0]
    outer_pair = compute_transit_aspects(
        (_point("uranus", 0.0),),
        (_point("pluto", 64.5),),
    )

    assert luminary.aspect_id == "sextile"
    assert luminary.orb_used == 7.0
    assert outer_pair == ()


def test_cross_aspects_exclude_transit_angles_and_derived_south_node() -> None:
    hits = compute_transit_aspects(
        (
            _point("moon", 0.0),
            _point("asc", 0.0, kind="angle"),
            _point("south_node", 0.0),
        ),
        (_point("saturn", 0.0),),
    )

    assert [(hit.transit_body, hit.natal_point) for hit in hits] == [
        ("moon", "saturn")
    ]


def test_cross_aspects_compare_a_common_j2000_frame() -> None:
    hits = compute_transit_aspects(
        (_point("mars", 20.0, j2000=7.5, speed=1.0),),
        (_point("venus", 100.0, j2000=100.0),),
    )

    assert len(hits) == 1
    assert hits[0].aspect_id == "square"
    assert hits[0].exactness == pytest.approx(2.5)


def test_cross_applying_uses_j2000_speed_near_a_station() -> None:
    hit = compute_transit_aspects(
        (_point("mars", 87.0, speed=1.0, j2000_speed=-1.0),),
        (_point("venus", 0.0),),
    )[0]

    assert hit.aspect_id == "square"
    assert hit.applying is False
