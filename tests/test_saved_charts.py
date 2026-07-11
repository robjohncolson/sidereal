"""Local saved-chart JSON library tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time
import json
import os
from pathlib import Path
import re
import stat

import pytest

from sidereal.config import AspectRule, ChartConfig
from sidereal.library import (
    AmbiguousChartError,
    ChartNotFoundError,
    chart_from_dict,
    list_charts,
    load_chart,
    save_chart,
    update_last_report_path,
)
from sidereal.types import (
    AspectHit,
    Chart,
    ChartMeta,
    HouseCusp,
    MomentInput,
    PatternHit,
    PointPos,
)


def _fixture_chart(label: str, *, hour: int = 12) -> Chart:
    moment = MomentInput(
        local_date=date(2000, 1, 1),
        local_time=time(hour),
        tz="UTC",
        lat=0.0,
        lon=0.0,
        label=label,
    )
    instant = datetime(2000, 1, 1, hour, tzinfo=UTC)
    meta = ChartMeta(
        input=moment,
        time_known=True,
        location_known=True,
        local_datetime=instant,
        utc_datetime=instant,
        jd_ut=2451545.0 + (hour - 12) / 24,
        jd_et=2451545.0007 + (hour - 12) / 24,
        zodiac_system="midpoint_v1",
        house_system="equal_house_12",
        aspect_profile="test",
        swe_version="test",
        pyswisseph_version="test",
        boundary_version="test",
        ephemeris_backend="fixture",
        warnings=("fixture warning",),
        aspect_rules=(("conjunction", 0.0, 8.0),),
        ephemeris_flags=("FIXTURE",),
        house_frame_method="fixture rotation",
        boundary_source_doi="10.example/test",
        boundary_license_id="test-license",
        boundary_sha256="0" * 64,
    )
    point = PointPos(
        id="sun",
        name="Sun",
        kind="body",
        lon_date=280.0,
        lon_j2000=280.1,
        lat=0.0,
        speed_long=1.0,
        retro=False,
        sign="sagittarius",
        degree_in_sign=13.0,
        house=10,
        blend=False,
        secondary_sign=None,
    )
    cusp = HouseCusp(
        number=1,
        lon_date=10.0,
        lon_j2000=10.1,
        sign="pisces",
        degree_in_sign=4.0,
        blend=True,
        secondary_sign="aries",
    )
    aspect = AspectHit(
        body_a="sun",
        body_b="mc",
        aspect_id="conjunction",
        separation=1.0,
        orb_used=8.0,
        exactness=0.875,
        force=0.875,
        applying=True,
    )
    pattern = PatternHit(
        pattern_id="stellium",
        members=("sun", "moon", "mercury"),
        sign="sagittarius",
    )
    return Chart(meta, (point,), (cusp,), (aspect,), (pattern,))


def _fixture_config(tmp_path: Path) -> ChartConfig:
    return ChartConfig(
        aspect_profile="test",
        aspect_rules=(AspectRule("conjunction", 0.0, 8.0),),
        boundary_path=tmp_path / "boundaries.json",
        ephe_path=tmp_path / "ephe",
    )


def test_save_list_load_and_frozen_geometry_round_trip(tmp_path: Path) -> None:
    charts_dir = tmp_path / "charts"
    chart = _fixture_chart("My Café / Chart")
    config = _fixture_config(tmp_path)

    saved = save_chart(
        chart,
        config,
        charts_dir=charts_dir,
        systems=("midpoint_v1", "tropical"),
        last_report_path=tmp_path / "reports" / "my-chart.md",
    )

    assert re.fullmatch(
        r"my-cafe-chart-20000101T120000Z-[0-9a-f]{10}",
        saved.id,
    )
    assert saved.source_path.name == f"{saved.id}.json"
    assert saved.systems == ("midpoint_v1", "tropical")
    assert saved.moment() == chart.meta.input
    assert saved.chart_config() == config
    assert saved.chart_object() == chart
    assert saved.chart_object().to_dict() == chart.to_dict()

    payload = json.loads(saved.source_path.read_text(encoding="utf-8"))
    assert payload["input"]["label"] == "My Café / Chart"
    assert payload["config"]["ephe_path"] == str(tmp_path / "ephe")
    assert payload["chart"] == chart.to_dict()
    assert payload["last_report_path"] == str(tmp_path / "reports" / "my-chart.md")
    assert list_charts(charts_dir) == (saved,)
    assert load_chart(saved.id, charts_dir) == saved
    assert load_chart(saved.source_path.name, charts_dir) == saved
    assert load_chart("my café / chart", charts_dir) == saved

    if os.name == "posix":
        assert stat.S_IMODE(charts_dir.stat().st_mode) == 0o700
        assert stat.S_IMODE(saved.source_path.stat().st_mode) == 0o600


def test_label_resolution_requires_an_id_when_labels_repeat(tmp_path: Path) -> None:
    charts_dir = tmp_path / "charts"
    config = _fixture_config(tmp_path)
    first = save_chart(_fixture_chart("Twin", hour=12), config, charts_dir=charts_dir)
    second = save_chart(_fixture_chart("Twin", hour=13), config, charts_dir=charts_dir)

    assert tuple(item.id for item in list_charts(charts_dir)) == (first.id, second.id)
    with pytest.raises(AmbiguousChartError, match="use one of these ids"):
        load_chart("Twin", charts_dir)
    assert load_chart(second.id, charts_dir) == second


def test_same_label_and_instant_with_different_config_does_not_overwrite(
    tmp_path: Path,
) -> None:
    charts_dir = tmp_path / "charts"
    chart = _fixture_chart("Configured")
    first_config = _fixture_config(tmp_path)
    second_config = replace(first_config, ephe_path=tmp_path / "other-ephe")

    first = save_chart(chart, first_config, charts_dir=charts_dir)
    second = save_chart(chart, second_config, charts_dir=charts_dir)

    assert first.id != second.id
    assert {item.id for item in list_charts(charts_dir)} == {first.id, second.id}
    assert first.source_path.is_file()
    assert second.source_path.is_file()


def test_update_report_pointer_and_missing_library_behavior(tmp_path: Path) -> None:
    charts_dir = tmp_path / "charts"
    assert list_charts(charts_dir) == ()
    with pytest.raises(ChartNotFoundError, match="No saved chart"):
        load_chart("Nobody", charts_dir)

    saved = save_chart(
        _fixture_chart("Report"),
        _fixture_config(tmp_path),
        charts_dir=charts_dir,
    )
    assert saved.last_report_path is None
    updated = update_last_report_path(
        saved.id,
        tmp_path / "report.md",
        charts_dir=charts_dir,
    )
    assert updated.last_report_path == str(tmp_path / "report.md")
    assert updated.chart_object() == saved.chart_object()
    assert load_chart("Report", charts_dir) == updated


def test_older_saved_points_without_j2000_speed_remain_loadable() -> None:
    payload = _fixture_chart("Legacy").to_dict()
    for point in payload["points"]:
        point.pop("speed_long_j2000")

    restored = chart_from_dict(payload)

    assert restored.points[0].speed_long_j2000 is None
