from __future__ import annotations

from datetime import date, time
from dataclasses import replace

import pytest

pytest.importorskip("swisseph")

from sidereal.chart import compute
from sidereal.ephemeris import PositionBatch, RawHouseData, RawPosition
from sidereal.types import MomentInput


def test_full_j2000_chart_matches_verified_swiss_values() -> None:
    chart = compute(MomentInput(date(2000, 1, 1), time(12), "UTC", 0, 0, "Golden"))
    points = {point.id: point for point in chart.points}

    assert chart.meta.jd_ut == pytest.approx(2451545.00000411, abs=1e-9)
    assert len(chart.points) == 16
    assert chart.cusps is not None and len(chart.cusps) == 12
    assert points["sun"].lon_date == pytest.approx(280.368923865, abs=1e-5)
    assert points["sun"].lon_j2000 == pytest.approx(280.372793704, abs=1e-5)
    assert (points["sun"].sign, points["sun"].house) == ("sagittarius", 9)
    assert points["moon"].sign == "libra"
    assert points["moon"].blend is True
    assert points["moon"].secondary_sign == "virgo"
    assert points["asc"].lon_j2000 == pytest.approx(11.379376534, abs=1e-7)
    assert points["mc"].lon_j2000 == pytest.approx(279.616325987, abs=1e-7)
    assert tuple(cusp.sign for cusp in chart.cusps) == (
        "pisces",
        "aries",
        "taurus",
        "gemini",
        "cancer",
        "leo",
        "virgo",
        "virgo",
        "scorpio",
        "sagittarius",
        "capricorn",
        "aquarius",
    )
    assert any(
        hit.body_a == "mc" and hit.body_b == "sun" and hit.aspect_id == "conjunction"
        for hit in chart.aspects
    )
    assert not any(
        derived in (hit.body_a, hit.body_b)
        for hit in chart.aspects
        for derived in ("south_node", "desc", "ic")
    )


def test_unknown_time_has_planets_but_no_angles_houses_or_angle_aspects() -> None:
    chart = compute(MomentInput(date(2000, 1, 1), None, "UTC"))

    assert chart.meta.time_known is False
    assert chart.meta.calculation_time_assumption == "12:00 local (time not supplied)"
    assert len(chart.points) == 12
    assert chart.cusps is None
    assert all(point.kind == "body" and point.house is None for point in chart.points)
    assert all("asc" not in (hit.body_a, hit.body_b) for hit in chart.aspects)


def test_canonical_boundaries_place_j2000_era_sun_in_ophiuchus_in_december() -> None:
    # The canonical 254.7132° boundary puts the J2000-era window around
    # December 7–18; this test follows the numeric table rather than a loose
    # "late November" description in the handoff prompt.
    chart = compute(MomentInput(date(2000, 12, 10), None, "UTC"))
    sun = next(point for point in chart.points if point.id == "sun")

    assert sun.lon_j2000 == pytest.approx(258.731689, abs=2e-5)
    assert sun.sign == "ophiuchus"


def test_ophiuchus_sun_entry_and_exit_dates_follow_published_boundaries() -> None:
    # Fixture source: Chimenti, The Midpoint Method, canonical J2000 starts
    # 254.7132° (Ophiuchus) and 267.0711° (Sagittarius), Zenodo DOI
    # 10.5281/zenodo.20747017. Noon samples bracket each crossing to one day.
    expected = {
        date(2000, 12, 6): "scorpio",
        date(2000, 12, 7): "ophiuchus",
        date(2000, 12, 18): "ophiuchus",
        date(2000, 12, 19): "sagittarius",
    }
    for local_date, sign in expected.items():
        chart = compute(MomentInput(local_date, None, "UTC"))
        sun = next(point for point in chart.points if point.id == "sun")
        assert sun.sign == sign


def test_chart_serialization_is_json_safe_and_stable() -> None:
    chart = compute(MomentInput(date(2000, 1, 1), None, "UTC", label="Serializable"))
    payload = chart.to_dict()
    text = chart.to_json(indent=None)

    assert payload["meta"]["input"]["local_date"] == "2000-01-01"
    assert payload["meta"]["input"]["local_time"] is None
    assert '"zodiac_system": "midpoint_v1"' in text
    assert payload["meta"]["blend_orb_deg"] == 3.0
    assert payload["meta"]["aspect_rules"][0] == ["conjunction", 0.0, 8.0]
    assert payload["meta"]["ephemeris_flags"] == [
        "FLG_SWIEPH",
        "FLG_SPEED",
        "FLG_J2000",
    ]
    assert payload["meta"]["house_frame_method"] is None
    assert len(payload["meta"]["boundary_sha256"]) == 64


def test_chart_and_report_serializers_reject_nonstandard_nan_json() -> None:
    from sidereal.interpret.compose import compose_report

    chart = compute(MomentInput(date(2000, 1, 1), None, "UTC"))
    corrupt = replace(
        chart,
        points=(replace(chart.points[0], lat=float("nan")), *chart.points[1:]),
    )
    with pytest.raises(ValueError, match="Out of range float"):
        corrupt.to_json()
    with pytest.raises(ValueError, match="Out of range float"):
        compose_report(corrupt, None).to_json()


class _InvalidProvider:
    swe_version = "test"
    pyswisseph_version = "test"
    position_flags: tuple[str, ...] = ()
    house_frame_flags: tuple[str, ...] = ()
    house_frame_method = "test"

    def __init__(self, *, bad_houses: bool = False) -> None:
        self.bad_houses = bad_houses

    def calculate_positions(self, _jd_ut: float) -> PositionBatch:
        return PositionBatch(
            positions=tuple(
                RawPosition(
                    id=body_id,
                    lon_date=float(index * 30),
                    lon_j2000=float(index * 30),
                    lat=(
                        float("nan")
                        if body_id == "sun" and not self.bad_houses
                        else 0.0
                    ),
                    speed_long=1.0,
                )
                for index, body_id in enumerate((
                    "sun", "moon", "mercury", "venus", "mars", "jupiter",
                    "saturn", "uranus", "neptune", "pluto", "north_node",
                    "south_node",
                ))
            ),
            backend="fixture",
        )

    def calculate_houses(self, _jd_ut: float, _lat: float, _lon: float) -> RawHouseData:
        return RawHouseData(
            cusps_date=tuple(float(index * 30) for index in range(12)),
            cusps_j2000=tuple(float(index * 30) for index in range(12)),
            cusp_speeds_date=(float("nan"),) + (1.0,) * 11,
            asc_date=0.0,
            asc_j2000=0.0,
            asc_speed_date=1.0,
            mc_date=270.0,
            mc_j2000=270.0,
            mc_speed_date=1.0,
        )


def test_orchestrator_rejects_nonfinite_provider_geometry() -> None:
    with pytest.raises(ValueError, match="non-finite geometry"):
        compute(
            MomentInput(date(2000, 1, 1), None, "UTC"),
            ephemeris=_InvalidProvider(),
        )
    with pytest.raises(ValueError, match="non-finite house"):
        compute(
            MomentInput(date(2000, 1, 1), time(12), "UTC", 0, 0),
            ephemeris=_InvalidProvider(bad_houses=True),
        )
