from __future__ import annotations

from datetime import date, time
import json
import math
from pathlib import Path

import pytest

pytest.importorskip("swisseph")

from sidereal.chart import compute
from sidereal.cli import main
from sidereal.comparison import build_comparison, parse_comparison_systems
from sidereal.interpret.compose import compose_report
from sidereal.types import MomentInput
from sidereal.zodiac.tropical import TROPICAL_SIGNS, TropicalZodiac


def test_tropical_zodiac_uses_half_open_equal_signs_without_ophiuchus() -> None:
    zodiac = TropicalZodiac()

    assert zodiac.map(0.0).sign == "aries"
    assert zodiac.map(29.999999).sign == "aries"
    assert zodiac.map(30.0).sign == "taurus"
    assert zodiac.map(360.0).sign == "aries"
    assert zodiac.map(-30.0).sign == "pisces"
    assert len(TROPICAL_SIGNS) == 12
    assert "ophiuchus" not in TROPICAL_SIGNS
    with pytest.raises(ValueError, match="finite"):
        zodiac.map(math.nan)


def test_comparison_aliases_are_stable_and_require_tropical() -> None:
    assert parse_comparison_systems("tropical") == ("midpoint_v1", "tropical")
    assert parse_comparison_systems("midpoint,tropical,midpoint_v1") == (
        "midpoint_v1",
        "tropical",
    )
    with pytest.raises(ValueError, match="include tropical"):
        parse_comparison_systems("midpoint")
    with pytest.raises(ValueError, match="unsupported"):
        parse_comparison_systems("galactic")


def test_j2000_sun_comparison_uses_midpoint_j2000_and_tropical_of_date() -> None:
    chart = compute(MomentInput(date(2000, 1, 1), time(12), "UTC", 0, 0))
    comparison = build_comparison(chart, "tropical")
    sun = next(point for point in comparison["points"] if point["id"] == "sun")

    assert comparison["systems"] == ["midpoint_v1", "tropical"]
    assert sun["systems"]["midpoint_v1"]["sign"] == "sagittarius"
    assert sun["systems"]["tropical"]["sign"] == "capricorn"
    assert sun["systems"]["tropical"]["degree_in_sign"] == pytest.approx(
        10.368923865,
        abs=1e-5,
    )
    assert sun["labels_differ"] is True
    assert len(comparison["cusps"]) == 12
    first_cusp = comparison["cusps"][0]
    expected = TropicalZodiac().map(chart.cusps[0].lon_date)  # type: ignore[index]
    assert first_cusp["systems"]["tropical"]["sign"] == expected.sign


def test_comparison_is_report_geometry_only_and_unknown_time_has_no_cusps() -> None:
    chart = compute(MomentInput(date(2000, 1, 1), None, "UTC"))
    plain = compose_report(chart, None)
    comparison = build_comparison(chart, "midpoint,tropical")
    compared = compose_report(chart, None, comparison=comparison)

    assert comparison["cusps"] == []
    assert len(comparison["points"]) == 12
    assert compared.gaps == plain.gaps
    assert compared.planet_readings == plain.planet_readings
    payload = compared.to_dict()
    assert payload["comparison"] == comparison
    markdown = compared.to_markdown()
    assert "## Comparison" in markdown
    assert "different reference frames" in markdown
    assert "labels differ" in markdown


def test_chart_cli_emits_comparison_json_and_markdown(
    tmp_path: Path,
) -> None:
    output = tmp_path / "comparison.json"
    markdown = tmp_path / "comparison.md"

    assert main(
        [
            "chart",
            "--date",
            "2000-01-01",
            "--time",
            "12:00",
            "--tz",
            "UTC",
            "--lat",
            "0",
            "--lon",
            "0",
            "--compare",
            "tropical",
            "--out",
            str(output),
            "--md",
            str(markdown),
        ]
    ) == 0

    payload = json.loads(output.read_text(encoding="utf-8"))
    sun = next(item for item in payload["comparison"]["points"] if item["id"] == "sun")
    primary_sun = next(item for item in payload["chart"]["points"] if item["id"] == "sun")
    assert primary_sun["sign"] == "sagittarius"
    assert sun["systems"]["tropical"]["sign"] == "capricorn"
    assert "## Comparison" in markdown.read_text(encoding="utf-8")
