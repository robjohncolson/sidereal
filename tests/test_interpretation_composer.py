from __future__ import annotations

from datetime import UTC, date, datetime, time
import json
from pathlib import Path

import pytest

from sidereal.interpret.compose import EPISTEMIC_NOTE, compose_report
from sidereal.interpret.store import InterpretationStore
from sidereal.types import (
    AspectHit,
    Chart,
    ChartMeta,
    HouseCusp,
    MomentInput,
    PatternHit,
    PointPos,
)


SEED_DIRECTORY = Path(__file__).resolve().parents[1] / "data" / "seeds"


def _meta(*, time_known: bool) -> ChartMeta:
    supplied_time = time(12, 0) if time_known else None
    return ChartMeta(
        input=MomentInput(
            local_date=date(2000, 1, 1),
            local_time=supplied_time,
            tz="UTC",
            lat=0.0 if time_known else None,
            lon=0.0 if time_known else None,
            label="Interpretation test",
        ),
        time_known=time_known,
        location_known=time_known,
        local_datetime=datetime(2000, 1, 1, 12, tzinfo=UTC),
        utc_datetime=datetime(2000, 1, 1, 12, tzinfo=UTC),
        jd_ut=2451545.0,
        jd_et=2451545.0007,
        zodiac_system="midpoint_v1",
        house_system="equal_house_12" if time_known else None,
        aspect_profile="modern_major",
        swe_version="test",
        pyswisseph_version="test",
        boundary_version="1",
        ephemeris_backend="fixture",
        calculation_time_assumption=(
            None if time_known else "12:00 local (time not supplied)"
        ),
        warnings=("Angles and houses omitted because civil time is unknown.",)
        if not time_known
        else (),
    )


def _point(
    point_id: str,
    *,
    sign: str,
    house: int | None,
    blend: bool = False,
    secondary: str | None = None,
    kind: str = "body",
) -> PointPos:
    return PointPos(
        id=point_id,
        name=point_id.replace("_", " ").title(),
        kind=kind,
        lon_date=260.0,
        lon_j2000=260.0,
        lat=0.0,
        speed_long=1.0,
        retro=False,
        sign=sign,
        degree_in_sign=5.2868,
        house=house,
        blend=blend,
        secondary_sign=secondary,
    )


def _seeded_store(tmp_path: Path) -> InterpretationStore:
    store = InterpretationStore(tmp_path / "interpretations.db")
    store.initialize()
    store.import_path(SEED_DIRECTORY)
    return store


def test_composer_renders_stubs_and_lists_them_as_gaps(tmp_path: Path) -> None:
    chart = Chart(
        meta=_meta(time_known=True),
        points=(
            _point("sun", sign="ophiuchus", house=1, blend=True, secondary="sagittarius"),
            _point("moon", sign="virgo", house=10),
            _point("asc", sign="ophiuchus", house=1, kind="angle"),
            _point("desc", sign="taurus", house=7, kind="angle"),
        ),
        cusps=(
            HouseCusp(
                number=1,
                lon_date=260.0,
                lon_j2000=260.0,
                sign="ophiuchus",
                degree_in_sign=5.2868,
                blend=False,
                secondary_sign=None,
            ),
        ),
        # Deliberately reverse priority order to exercise report sorting.
        aspects=(
            AspectHit("jupiter", "saturn", "square", 89.0, 7.0, 1.0, 0.8, False),
            AspectHit("mars", "venus", "sextile", 60.5, 6.0, 0.5, 0.9, True),
            AspectHit("mc", "sun", "trine", 121.0, 9.0, 1.0, 0.8, True),
            AspectHit("moon", "sun", "conjunction", 2.0, 9.0, 2.0, 0.7, True),
            AspectHit("moon", "pluto", "opposition", 179.0, 9.0, 1.0, 0.8, False),
        ),
        patterns=(PatternHit("t_square", ("moon", "sun", "pluto"), apex="sun"),),
    )
    store = _seeded_store(tmp_path)
    try:
        report = compose_report(chart, store)
    finally:
        store.close()

    data = report.to_dict()
    sun_readings = data["interpretation"]["planets"][0]["readings"]
    assert [reading["id"] for reading in sun_readings[:3]] == [
        "planet:sun",
        "planet_in_sign:sun:ophiuchus",
        "planet_in_sign:sun:sagittarius",
    ]
    assert all(reading["status"] == "ready" for reading in sun_readings[:3])
    assert sun_readings[3]["status"] == "ready"
    assert {gap.kind for gap in report.gaps} == {"stub"}
    gap_keys = {gap.key for gap in report.gaps}
    assert "planet_in_house:sun:1" not in gap_keys
    assert "pattern:t_square" not in gap_keys
    assert "aspect:mc:trine:sun" in gap_keys
    assert "aspect:moon:opposition:pluto" in gap_keys
    ordered_pairs = [
        (item["aspect"]["body_a"], item["aspect"]["body_b"])
        for item in data["interpretation"]["relationships"]
    ]
    assert ordered_pairs == [
        ("moon", "sun"),
        ("mc", "sun"),
        ("mars", "venus"),
        ("moon", "pluto"),
        ("jupiter", "saturn"),
    ]
    markdown = report.to_markdown()
    assert "## Epistemic note" in markdown
    assert EPISTEMIC_NOTE in markdown
    assert "## Missing interpretation keys" in markdown
    assert "within 3.00° of the boundary with Sagittarius" in markdown
    assert "orb 2.0000°, applying" in markdown
    assert "_(stub)_" in markdown
    assert json.loads(report.to_json())["report_version"] == 1


def test_unknown_time_composer_never_invents_houses_or_angles() -> None:
    chart = Chart(
        meta=_meta(time_known=False),
        points=(_point("sun", sign="capricorn", house=None),),
        cusps=None,
        aspects=(),
        patterns=(),
    )
    report = compose_report(chart, None)

    assert report.angle_readings == ()
    assert report.house_readings == ()
    assert not any("planet_in_house" in gap.key for gap in report.gaps)
    assert not any("angle_in_sign" in gap.key for gap in report.gaps)
    assert {gap.kind for gap in report.gaps} == {"missing"}
    markdown = report.to_markdown()
    assert "Calculation assumption: 12:00 local (time not supplied)" in markdown
    assert "Calculation warning: Angles and houses omitted" in markdown
    assert "no cusp signs have been inferred" in markdown


def test_composer_rejects_mapping_that_would_drop_geometry_readings() -> None:
    chart = Chart(
        meta=_meta(time_known=False),
        points=(_point("sun", sign="capricorn", house=None),),
        cusps=None,
        aspects=(),
        patterns=(),
    )
    with pytest.raises(TypeError, match="not a mapping"):
        compose_report(chart.to_dict(), None)
