from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timezone

import pytest

from sidereal.config import ChartConfig
from sidereal.synastry import compute_synastry_geometry
from sidereal.types import Chart, ChartMeta, MomentInput, PointPos


def _point(
    point_id: str,
    longitude: float,
    *,
    j2000: float | None = None,
    speed: float = 0.0,
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
        speed_long_j2000=speed,
    )


def _chart(
    label: str,
    points: tuple[PointPos, ...],
    *,
    time_known: bool = True,
    location_known: bool = True,
) -> Chart:
    local_time = time(12) if time_known else None
    moment = MomentInput(
        local_date=date(2000, 1, 1),
        local_time=local_time,
        tz="UTC",
        lat=0.0 if location_known else None,
        lon=0.0 if location_known else None,
        label=label,
    )
    instant = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)
    config = ChartConfig()
    meta = ChartMeta(
        input=moment,
        time_known=time_known,
        location_known=location_known,
        local_datetime=instant,
        utc_datetime=instant,
        jd_ut=2451545.0,
        jd_et=2451545.0,
        zodiac_system=config.zodiac,
        house_system=config.house_system if time_known and location_known else None,
        aspect_profile=config.aspect_profile,
        swe_version="test",
        pyswisseph_version="test",
        boundary_version="midpoint-test-v1",
        ephemeris_backend="synthetic",
        boundary_sha256="abc123",
    )
    return Chart(meta=meta, points=points, cusps=None, aspects=(), patterns=())


def test_synastry_preserves_roles_and_uses_common_j2000_frame() -> None:
    chart_a = _chart("A", (_point("mars", 20.0, j2000=7.5, speed=1.0),))
    chart_b = _chart("B", (_point("venus", 100.0, j2000=100.0, speed=-9.0),))

    geometry = compute_synastry_geometry(chart_a, chart_b, ChartConfig())

    assert geometry.chart_a is chart_a
    assert geometry.chart_b is chart_b
    assert len(geometry.aspects) == 1
    hit = geometry.aspects[0]
    assert (hit.a_point, hit.b_point, hit.aspect_id) == ("mars", "venus", "square")
    assert hit.separation == pytest.approx(92.5)
    assert hit.exactness == pytest.approx(2.5)
    assert hit.applying is None
    assert hit.to_dict()["applying"] is None


def test_synastry_keeps_same_body_hits_and_reuses_configured_orbs() -> None:
    chart_a = _chart(
        "A",
        (
            _point("sun", 0.0),
            _point("uranus", 0.0),
        ),
    )
    chart_b = _chart(
        "B",
        (
            _point("sun", 1.0),
            _point("venus", 66.5),
            _point("pluto", 64.5),
        ),
    )

    hits = compute_synastry_geometry(chart_a, chart_b, ChartConfig()).aspects

    sun_self = next(hit for hit in hits if (hit.a_point, hit.b_point) == ("sun", "sun"))
    sun_venus = next(
        hit for hit in hits if (hit.a_point, hit.b_point) == ("sun", "venus")
    )
    assert sun_self.aspect_id == "conjunction"
    assert sun_venus.aspect_id == "sextile"
    assert sun_venus.orb_used == 7.0
    assert not any(
        hit.a_point == "uranus" and hit.b_point == "pluto" for hit in hits
    )


def test_known_time_charts_include_angles_but_not_display_only_points() -> None:
    chart_a = _chart(
        "A",
        (
            _point("asc", 0.0, kind="angle"),
            _point("desc", 0.0, kind="angle"),
            _point("south_node", 0.0),
        ),
    )
    chart_b = _chart(
        "B",
        (
            _point("mc", 60.0, kind="angle"),
            _point("venus", 60.0),
        ),
    )

    hits = compute_synastry_geometry(chart_a, chart_b, ChartConfig()).aspects

    assert {(hit.a_point, hit.b_point) for hit in hits} == {
        ("asc", "mc"),
        ("asc", "venus"),
    }


@pytest.mark.parametrize("unknown_role", ["a", "b"])
def test_unknown_time_chart_omits_its_angles(unknown_role: str) -> None:
    # Include an inconsistent synthetic angle deliberately: metadata remains
    # authoritative, so an unknown-time chart cannot leak angle aspects.
    unknown = _chart(
        "Unknown",
        (
            _point("sun", 0.0),
            _point("asc", 0.0, kind="angle"),
        ),
        time_known=False,
        location_known=False,
    )
    known = _chart(
        "Known",
        (
            _point("venus", 0.0),
            _point("mc", 0.0, kind="angle"),
        ),
    )

    chart_a, chart_b = (unknown, known) if unknown_role == "a" else (known, unknown)
    hits = compute_synastry_geometry(chart_a, chart_b, ChartConfig()).aspects

    if unknown_role == "a":
        assert all(hit.a_point != "asc" for hit in hits)
        assert {(hit.a_point, hit.b_point) for hit in hits} == {
            ("sun", "mc"),
            ("sun", "venus"),
        }
    else:
        assert all(hit.b_point != "asc" for hit in hits)
        assert {(hit.a_point, hit.b_point) for hit in hits} == {
            ("mc", "sun"),
            ("venus", "sun"),
        }


def test_synastry_rejects_incompatible_boundary_data() -> None:
    chart_a = _chart("A", (_point("sun", 0.0),))
    chart_b = _chart("B", (_point("moon", 0.0),))
    chart_b = replace(
        chart_b,
        meta=replace(chart_b.meta, boundary_sha256="different"),
    )

    with pytest.raises(ValueError, match="different boundary data"):
        compute_synastry_geometry(chart_a, chart_b, ChartConfig())
