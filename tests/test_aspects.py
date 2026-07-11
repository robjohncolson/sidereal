from __future__ import annotations

import pytest

from sidereal.aspects import compute_aspects, detect_patterns, shortest_arc
from sidereal.config import AspectRule, ChartConfig
from sidereal.types import PointPos


def point(
    point_id: str,
    longitude: float,
    *,
    speed: float = 0.0,
    sign: str = "aries",
    kind: str = "body",
) -> PointPos:
    return PointPos(
        id=point_id,
        name=point_id,
        kind=kind,
        lon_date=longitude,
        lon_j2000=longitude,
        lat=0.0,
        speed_long=speed,
        retro=speed < 0,
        sign=sign,
        degree_in_sign=0.0,
        house=None,
        blend=False,
        secondary_sign=None,
    )


def test_shortest_arc_wraps() -> None:
    assert shortest_arc(359, 1) == pytest.approx(2)
    assert shortest_arc(10, 190) == pytest.approx(180)


@pytest.mark.parametrize(
    ("longitude", "aspect_id"),
    [(0, "conjunction"), (60, "sextile"), (90, "square"), (120, "trine"), (180, "opposition")],
)
def test_each_default_major_aspect(longitude: float, aspect_id: str) -> None:
    hits = compute_aspects((point("mars", 0), point("venus", longitude)))
    assert len(hits) == 1
    assert hits[0].aspect_id == aspect_id
    assert hits[0].exactness == pytest.approx(0)
    assert hits[0].applying is None


def test_luminary_and_outer_pair_orb_modifiers() -> None:
    luminary = compute_aspects((point("sun", 0), point("venus", 66.5)))[0]
    outers = compute_aspects((point("uranus", 0), point("pluto", 64.5)))

    assert luminary.aspect_id == "sextile"
    assert luminary.orb_used == 7.0
    assert outers == ()  # outer/outer sextile orb is tightened from 6 to 4


def test_applying_and_separating_use_oriented_relative_speed() -> None:
    applying = compute_aspects(
        (point("mars", 0, speed=0), point("venus", 87, speed=1))
    )[0]
    separating = compute_aspects(
        (point("mars", 0, speed=1), point("venus", 87, speed=0))
    )[0]

    assert applying.aspect_id == separating.aspect_id == "square"
    assert applying.applying is True
    assert separating.applying is False


def test_pairs_are_alphabetical_and_derived_points_are_excluded() -> None:
    hits = compute_aspects(
        (
            point("venus", 0),
            point("mars", 0),
            point("south_node", 0),
            point("desc", 0, kind="angle"),
        )
    )

    assert [(hit.body_a, hit.body_b) for hit in hits] == [("mars", "venus")]


def test_stellium_requires_personal_anchor() -> None:
    outer_only = (
        point("uranus", 0, sign="virgo"),
        point("neptune", 1, sign="virgo"),
        point("pluto", 2, sign="virgo"),
    )
    anchored = outer_only + (point("sun", 3, sign="virgo"),)

    assert detect_patterns(outer_only, ()) == ()
    pattern = detect_patterns(anchored, ())[0]
    assert pattern.pattern_id == "stellium"
    assert pattern.sign == "virgo"
    assert pattern.members == ("neptune", "pluto", "sun", "uranus")


def test_t_square_and_grand_trine_derive_from_aspect_graph() -> None:
    t_points = (point("sun", 0), point("moon", 180), point("mars", 90))
    t_aspects = compute_aspects(t_points)
    t_patterns = detect_patterns(t_points, t_aspects)
    assert any(item.pattern_id == "t_square" and item.apex == "mars" for item in t_patterns)

    trine_points = (point("sun", 0), point("moon", 120), point("mars", 240))
    trine_patterns = detect_patterns(trine_points, compute_aspects(trine_points))
    assert any(item.pattern_id == "grand_trine" for item in trine_patterns)


@pytest.mark.parametrize(
    "config",
    [
        ChartConfig(aspect_rules=(AspectRule("conjunction", 0.0, float("nan")),)),
        ChartConfig(luminary_orb_bonus_deg=float("nan")),
        ChartConfig(outer_pair_orb_penalty_deg=float("inf")),
        ChartConfig(outer_pair_orb_penalty_deg=6.0),
    ],
)
def test_nonfinite_or_nonpositive_resolved_orbs_are_rejected(config: ChartConfig) -> None:
    with pytest.raises(ValueError):
        config.validate()


def test_overlapping_custom_windows_choose_closest_exact_geometry() -> None:
    rules = (
        AspectRule("opposition", 180.0, 70.0),
        AspectRule("trine", 120.0, 8.0),
    )
    hit = compute_aspects(
        (point("sun", 0.0), point("mars", 120.0)),
        rules=rules,
        luminary_orb_bonus_deg=0.0,
    )[0]
    assert hit.aspect_id == "trine"
    assert hit.exactness == 0.0
