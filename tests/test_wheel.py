from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time
import math
from xml.etree import ElementTree

import pytest

from sidereal.types import Chart, ChartMeta, HouseCusp, MomentInput, PointPos
from sidereal.wheel import render_svg
from sidereal.zodiac.midpoint import EXPECTED_SIGN_IDS


SVG = "{http://www.w3.org/2000/svg}"


def _point(
    point_id: str,
    name: str,
    longitude: float,
    *,
    kind: str = "body",
) -> PointPos:
    return PointPos(
        id=point_id,
        name=name,
        kind=kind,
        lon_date=longitude,
        lon_j2000=longitude,
        lat=0.0,
        speed_long=1.0,
        retro=False,
        sign="aries",
        degree_in_sign=0.0,
        house=1 if kind == "body" else None,
        blend=False,
        secondary_sign=None,
        speed_long_j2000=1.0,
    )


def _chart(*, houses: bool = True, offset: float = 0.0) -> Chart:
    ascendant = (31.2816 + offset) % 360.0
    moment = MomentInput(
        date(2000, 12, 12),
        time(12) if houses else None,
        "UTC",
        0.0 if houses else None,
        0.0 if houses else None,
        "Wheel fixture",
    )
    instant = datetime(2000, 12, 12, 12, tzinfo=UTC)
    meta = ChartMeta(
        input=moment,
        time_known=houses,
        location_known=houses,
        local_datetime=instant,
        utc_datetime=instant,
        jd_ut=2451891.0,
        jd_et=2451891.0,
        zodiac_system="midpoint_v1",
        house_system="equal_house_12" if houses else None,
        aspect_profile="modern_major",
        swe_version="fixture",
        pyswisseph_version="fixture",
        boundary_version="1",
        ephemeris_backend="fixture",
        boundary_sha256="a" * 64,
    )
    points = (
        _point("sun", "Sun", (258.73 + offset) % 360.0),
        _point("moon", "Moon", (222.60 + offset) % 360.0),
        _point("north_node", "North Node", (87.86 + offset) % 360.0),
    )
    cusps = None
    if houses:
        points += (_point("asc", "Ascendant", ascendant, kind="angle"),)
        cusps = tuple(
            HouseCusp(
                number=number,
                lon_date=(ascendant + (number - 1) * 30.0) % 360.0,
                lon_j2000=(ascendant + (number - 1) * 30.0) % 360.0,
                sign="aries",
                degree_in_sign=0.0,
                blend=False,
                secondary_sign=None,
            )
            for number in range(1, 13)
        )
    return Chart(meta=meta, points=points, cusps=cusps, aspects=(), patterns=())


def _groups(root: ElementTree.Element, class_name: str) -> list[ElementTree.Element]:
    return [
        element
        for element in root.iter(f"{SVG}g")
        if class_name in element.attrib.get("class", "").split()
    ]


def test_svg_has_all_unequal_midpoint_sign_arcs_and_body_markers() -> None:
    chart = _chart()
    svg = render_svg(chart)
    root = ElementTree.fromstring(svg)

    segments = _groups(root, "sign-segment")
    assert tuple(segment.attrib["id"] for segment in segments) == tuple(
        f"sign-{sign_id}" for sign_id in EXPECTED_SIGN_IDS
    )
    lengths = [float(segment.attrib["data-length-deg"]) for segment in segments]
    assert sum(lengths) == pytest.approx(360.0, abs=1e-5)
    assert len(set(lengths)) == 13
    assert "Ophiuchus" in "".join(root.itertext())

    natal_markers = _groups(root, "point-marker-natal")
    assert len(natal_markers) == sum(point.kind == "body" for point in chart.points)
    assert {marker.attrib["data-body"] for marker in natal_markers} == {
        "sun",
        "moon",
        "north_node",
    }


def test_ascendant_and_first_equal_house_cusp_are_at_nine_oclock() -> None:
    root = ElementTree.fromstring(render_svg(_chart()))

    assert root.attrib["data-orientation"] == "ascendant-at-nine"
    cusps = _groups(root, "house-layer")[0].findall(f"{SVG}line")
    assert len(cusps) == 12
    first = next(line for line in cusps if line.attrib["id"] == "house-cusp-1")
    assert float(first.attrib["x2"]) < float(first.attrib["x1"])
    assert float(first.attrib["y2"]) == pytest.approx(float(first.attrib["y1"]), abs=1e-3)
    assert "house-cusp-asc" in first.attrib["class"].split()


def test_unknown_time_uses_fixed_orientation_and_omits_houses() -> None:
    chart = _chart(houses=False)
    root = ElementTree.fromstring(render_svg(chart.to_dict()))

    assert root.attrib["data-orientation"] == "j2000-zero-at-nine"
    assert _groups(root, "house-layer") == []
    assert _groups(root, "point-marker-natal")
    assert "houses are omitted" in "".join(root.itertext())


def test_chart_dataclass_and_reordered_direct_json_are_deterministic() -> None:
    chart = _chart()
    payload = chart.to_dict()
    payload["points"] = list(reversed(payload["points"]))
    assert payload["cusps"] is not None
    payload["cusps"] = list(reversed(payload["cusps"]))

    assert render_svg(chart) == render_svg(payload)


def test_optional_overlay_uses_a_distinct_render_only_lane() -> None:
    natal = _chart()
    overlay = _chart(houses=False, offset=14.0)
    root = ElementTree.fromstring(render_svg(natal, overlay_chart=overlay))

    natal_markers = _groups(root, "point-marker-natal")
    overlay_markers = _groups(root, "point-marker-overlay")
    assert len(natal_markers) == len(overlay_markers) == 3
    assert root.find(f".//*[@id='point-natal-sun']") is not None
    assert root.find(f".//*[@id='point-overlay-sun']") is not None
    assert _groups(root, "wheel-legend")
    natal_tick = natal_markers[0].find(f"{SVG}line")
    overlay_tick = overlay_markers[0].find(f"{SVG}line")
    assert natal_tick is not None and overlay_tick is not None
    assert natal_tick.attrib["stroke"] != overlay_tick.attrib["stroke"]
    assert len(_groups(root, "house-layer")[0].findall(f"{SVG}line")) == 12


def test_clustered_point_labels_receive_distinct_radial_lanes() -> None:
    chart = _chart(houses=False)
    chart = replace(
        chart,
        points=(
            replace(chart.points[0], lon_j2000=10.0),
            replace(chart.points[1], lon_j2000=11.0),
            replace(chart.points[2], lon_j2000=12.0),
        ),
    )
    markers = _groups(ElementTree.fromstring(render_svg(chart)), "point-marker-natal")

    assert {marker.attrib["data-label-lane"] for marker in markers} == {"0", "1", "2"}


def test_overlay_rejects_incompatible_boundary_data() -> None:
    natal = _chart()
    overlay = _chart(houses=False)
    overlay = replace(
        overlay,
        meta=replace(overlay.meta, boundary_sha256="b" * 64),
    )

    with pytest.raises(ValueError, match="different boundary data"):
        render_svg(natal, overlay_chart=overlay)


def test_dynamic_text_is_xml_escaped_and_svg_is_csp_safe() -> None:
    chart = _chart(houses=False)
    unsafe_name = 'A&B <Sun> "quoted" onload=alert(1)'
    chart = replace(
        chart,
        points=(replace(chart.points[0], name=unsafe_name), *chart.points[1:]),
    )
    svg = render_svg(chart)
    root = ElementTree.fromstring(svg)

    assert "A&amp;B &lt;Sun&gt; &quot;quoted&quot;" in svg
    assert "<Sun>" not in svg
    title = root.find(f".//*[@id='point-natal-sun']/{SVG}title")
    assert title is not None and title.text is not None
    assert unsafe_name in title.text

    prohibited_tags = {"style", "script", "use", "image", "foreignObject"}
    for element in root.iter():
        local_name = element.tag.rsplit("}", 1)[-1]
        assert local_name not in prohibited_tags
        for attribute in element.attrib:
            local_attribute = attribute.rsplit("}", 1)[-1]
            assert local_attribute != "style"
            assert local_attribute not in {"href", "src"}
            assert not local_attribute.lower().startswith("on")


@pytest.mark.parametrize(
    "width",
    [True, "640", math.nan, math.inf, -math.inf, 319.999, 2048.001],
)
def test_width_validation_is_strict(width: object) -> None:
    with pytest.raises((TypeError, ValueError), match="width"):
        render_svg(_chart(houses=False), width=width)  # type: ignore[arg-type]


def test_fractional_width_is_finite_and_preserved() -> None:
    root = ElementTree.fromstring(render_svg(_chart(houses=False), width=640.5))
    assert root.attrib["width"] == root.attrib["height"] == "640.5"
    assert root.attrib["viewBox"] == "0 0 640.5 640.5"


def test_nonfinite_or_out_of_range_chart_geometry_fails_loudly() -> None:
    chart = _chart(houses=False)
    nonfinite = replace(
        chart,
        points=(replace(chart.points[0], lon_j2000=math.nan), *chart.points[1:]),
    )
    out_of_range = replace(
        chart,
        points=(replace(chart.points[0], lon_j2000=360.0), *chart.points[1:]),
    )

    with pytest.raises(ValueError, match="finite"):
        render_svg(nonfinite)
    with pytest.raises(ValueError, match=r"\[0, 360\)"):
        render_svg(out_of_range)


def test_point_ids_must_be_safe_and_unique_for_stable_svg_ids() -> None:
    chart = _chart(houses=False)
    unsafe = replace(
        chart,
        points=(replace(chart.points[0], id='sun" onload="alert(1)'), *chart.points[1:]),
    )
    duplicate = replace(
        chart,
        points=(replace(chart.points[0], id="moon"), *chart.points[1:]),
    )

    with pytest.raises(ValueError, match="safe stable identifier"):
        render_svg(unsafe)
    with pytest.raises(ValueError, match="duplicate id"):
        render_svg(duplicate)
