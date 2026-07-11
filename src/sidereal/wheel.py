"""Deterministic SVG rendering for computed 13-sign Midpoint charts.

This module is deliberately render-only.  It consumes J2000 longitudes that
the chart engine has already computed and never calls an ephemeris or remaps a
placement.  Zodiac longitude increases counterclockwise; when an Ascendant is
available it is rotated to the traditional 9 o'clock position.  Unknown-time
charts use 0 degrees J2000 at 9 o'clock and simply omit house cusps.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html import escape
import math
from numbers import Real
import re
from typing import Any

from .config import BODY_IDS
from .types import Chart
from .zodiac.midpoint import EXPECTED_SIGN_IDS, EXPECTED_STARTS


_SVG_NAMESPACE = "http://www.w3.org/2000/svg"
_MIN_WIDTH = 320.0
_MAX_WIDTH = 2048.0
_SAFE_ID = re.compile(r"[a-z][a-z0-9_-]*\Z")
_BODY_ORDER = {body_id: index for index, body_id in enumerate(BODY_IDS)}
_BODY_ABBREVIATIONS: dict[str, str] = {
    "sun": "Su",
    "moon": "Mo",
    "mercury": "Me",
    "venus": "Ve",
    "mars": "Ma",
    "jupiter": "Ju",
    "saturn": "Sa",
    "uranus": "Ur",
    "neptune": "Ne",
    "pluto": "Pl",
    "north_node": "NN",
    "south_node": "SN",
}
_SIGN_COLORS: tuple[str, ...] = (
    "#b85c4b",
    "#82733f",
    "#af8142",
    "#4d7789",
    "#b56b3b",
    "#69805a",
    "#8c6685",
    "#6f5269",
    "#477b70",
    "#74669a",
    "#6f7652",
    "#4d7890",
    "#6673a0",
)


@dataclass(frozen=True, slots=True)
class _RenderPoint:
    id: str
    name: str
    longitude: float


@dataclass(frozen=True, slots=True)
class _RenderCusp:
    number: int
    longitude: float


@dataclass(frozen=True, slots=True)
class _RenderChart:
    zodiac_system: str
    boundary_version: str
    boundary_sha256: str
    points: tuple[_RenderPoint, ...]
    asc_longitude: float | None
    cusps: tuple[_RenderCusp, ...]


def render_svg(
    chart: Chart | Mapping[str, Any],
    *,
    width: Real = 640,
    overlay_chart: Chart | Mapping[str, Any] | None = None,
) -> str:
    """Render a computed chart as a safe, standalone SVG string.

    ``chart`` may be a :class:`~sidereal.types.Chart` or its direct ``to_dict``
    JSON shape.  ``overlay_chart`` is optional and supplies a second set of
    already-computed body longitudes, intended for a transit sky layer.  The
    renderer does not calculate, precess, or reinterpret either chart.

    Width must be a finite real number from 320 through 2048 CSS pixels.  The
    SVG contains no scripts, embedded styles, links, images, event handlers, or
    ``foreignObject`` elements, so it can be imported under the local web
    desk's restrictive content-security policy.
    """

    size = _validated_width(width)
    natal = _read_chart(chart, "chart", include_cusps=True)
    overlay = (
        None
        if overlay_chart is None
        else _read_chart(overlay_chart, "overlay_chart", include_cusps=False)
    )
    _validate_frame_compatibility(natal, overlay)

    anchor_longitude = _anchor_longitude(natal)
    orientation = (
        "ascendant-at-nine"
        if natal.asc_longitude is not None or natal.cusps
        else "j2000-zero-at-nine"
    )
    center = size / 2.0
    outer_radius = size * 0.46
    sign_radius = size * 0.423
    sign_stroke = size * 0.058
    sign_label_size = size * 0.016
    boundary_inner = size * 0.391
    house_radius = size * 0.388
    natal_tick_inner = size * 0.304
    natal_tick_outer = size * 0.338
    natal_label_radius = size * 0.278
    overlay_tick_inner = size * 0.348
    overlay_tick_outer = size * 0.379
    overlay_label_radius = size * 0.382
    point_label_size = size * 0.018

    lines = [
        (
            f'<svg xmlns="{_SVG_NAMESPACE}" width="{_fmt(size)}" '
            f'height="{_fmt(size)}" viewBox="0 0 {_fmt(size)} {_fmt(size)}" '
            'role="img" class="midpoint-wheel" '
            f'data-orientation="{orientation}" '
            'aria-label="13-sign Midpoint chart wheel">'
        ),
        "  <title>13-sign Midpoint chart wheel</title>",
        (
            "  <desc>J2000 ecliptic longitude increases counterclockwise. "
            + (
                "The Ascendant is placed at 9 o'clock."
                if orientation == "ascendant-at-nine"
                else "Birth time is unknown, so 0 degrees is placed at 9 o'clock and houses are omitted."
            )
            + "</desc>"
        ),
        (
            f'  <circle class="wheel-field" cx="{_fmt(center)}" cy="{_fmt(center)}" '
            f'r="{_fmt(outer_radius)}" fill="#fffdf8" stroke="#34454c" '
            f'stroke-width="{_fmt(size * 0.003)}"/>'
        ),
        '  <g class="sign-layer">',
    ]

    segments = _canonical_segments()
    for index, (sign_id, start, length) in enumerate(segments):
        sign_name = sign_id.replace("_", " ").title()
        arc_start = _polar(center, sign_radius, _screen_angle(start, anchor_longitude))
        arc_end = _polar(
            center,
            sign_radius,
            _screen_angle((start + length) % 360.0, anchor_longitude),
        )
        label = _polar(
            center,
            sign_radius,
            _screen_angle((start + length / 2.0) % 360.0, anchor_longitude),
        )
        path = (
            f"M {_fmt(arc_start[0])} {_fmt(arc_start[1])} "
            f"A {_fmt(sign_radius)} {_fmt(sign_radius)} 0 0 0 "
            f"{_fmt(arc_end[0])} {_fmt(arc_end[1])}"
        )
        lines.extend(
            (
                (
                    f'    <g id="sign-{sign_id}" class="sign-segment sign-{sign_id}" '
                    f'data-start-deg="{_fmt(start, precision=6)}" '
                    f'data-length-deg="{_fmt(length, precision=6)}">'
                ),
                (
                    f'      <path class="sign-arc" d="{path}" fill="none" '
                    f'stroke="{_SIGN_COLORS[index]}" stroke-width="{_fmt(sign_stroke)}" '
                    'stroke-linecap="butt"/>'
                ),
                (
                    f'      <text class="sign-label" x="{_fmt(label[0])}" '
                    f'y="{_fmt(label[1])}" fill="#fffdf8" '
                    f'font-family="system-ui, sans-serif" font-size="{_fmt(sign_label_size)}" '
                    'font-weight="650" text-anchor="middle" dominant-baseline="central">'
                    f"{_xml(sign_name)}</text>"
                ),
                "    </g>",
            )
        )
    lines.append("  </g>")

    lines.append('  <g class="boundary-layer">')
    for sign_id, start, _length in segments:
        inner = _polar(center, boundary_inner, _screen_angle(start, anchor_longitude))
        outer = _polar(center, outer_radius, _screen_angle(start, anchor_longitude))
        lines.append(
            f'    <line class="sign-boundary" data-sign="{sign_id}" '
            f'x1="{_fmt(inner[0])}" y1="{_fmt(inner[1])}" '
            f'x2="{_fmt(outer[0])}" y2="{_fmt(outer[1])}" '
            f'stroke="#fffdf8" stroke-width="{_fmt(size * 0.0024)}"/>'
        )
    lines.append("  </g>")

    if natal.cusps:
        lines.append('  <g class="house-layer">')
        for cusp in natal.cusps:
            endpoint = _polar(
                center,
                house_radius,
                _screen_angle(cusp.longitude, anchor_longitude),
            )
            is_ascendant = cusp.number == 1
            lines.append(
                f'    <line id="house-cusp-{cusp.number}" class="house-cusp'
                f'{" house-cusp-asc" if is_ascendant else ""}" '
                f'data-house="{cusp.number}" data-longitude-j2000="{_fmt(cusp.longitude, precision=6)}" '
                f'x1="{_fmt(center)}" y1="{_fmt(center)}" '
                f'x2="{_fmt(endpoint[0])}" y2="{_fmt(endpoint[1])}" '
                f'stroke="{"#9b3f37" if is_ascendant else "#8b989d"}" '
                f'stroke-width="{_fmt(size * (0.004 if is_ascendant else 0.0018))}" '
                f'stroke-opacity="{"0.9" if is_ascendant else "0.62"}"/>'
            )
        lines.append("  </g>")

    lines.extend(
        _point_layer(
            natal.points,
            role="natal",
            center=center,
            anchor_longitude=anchor_longitude,
            tick_inner=natal_tick_inner,
            tick_outer=natal_tick_outer,
            label_radius=natal_label_radius,
            font_size=point_label_size,
        )
    )
    if overlay is not None:
        lines.extend(
            _point_layer(
                overlay.points,
                role="overlay",
                center=center,
                anchor_longitude=anchor_longitude,
                tick_inner=overlay_tick_inner,
                tick_outer=overlay_tick_outer,
                label_radius=overlay_label_radius,
                font_size=point_label_size * 0.88,
            )
        )
        lines.extend(_overlay_legend(center, size))

    lines.extend(
        (
            (
                f'  <circle class="wheel-center" cx="{_fmt(center)}" cy="{_fmt(center)}" '
                f'r="{_fmt(size * 0.006)}" fill="#34454c"/>'
            ),
            "</svg>",
        )
    )
    return "\n".join(lines)


def _point_layer(
    points: tuple[_RenderPoint, ...],
    *,
    role: str,
    center: float,
    anchor_longitude: float,
    tick_inner: float,
    tick_outer: float,
    label_radius: float,
    font_size: float,
) -> list[str]:
    color = "#176b78" if role == "natal" else "#c14f38"
    lanes = _point_label_lanes(points)
    lines = [f'  <g class="point-layer point-layer-{role}">']
    for point in points:
        angle = _screen_angle(point.longitude, anchor_longitude)
        inner = _polar(center, tick_inner, angle)
        outer = _polar(center, tick_outer, angle)
        lane = lanes[point.id]
        active_label_radius = label_radius - lane * font_size * 1.45
        label = _polar(center, active_label_radius, angle)
        abbreviation = _BODY_ABBREVIATIONS.get(point.id, point.name[:3])
        lines.extend(
            (
                (
                    f'    <g id="point-{role}-{point.id}" '
                    f'class="point-marker point-marker-{role}" data-body="{point.id}" '
                    f'data-label-lane="{lane}" '
                    f'data-longitude-j2000="{_fmt(point.longitude, precision=6)}">'
                ),
                (
                    f"      <title>{_xml(point.name)} — "
                    f"{_fmt(point.longitude, precision=2)}° J2000</title>"
                ),
                (
                    f'      <line class="point-tick" x1="{_fmt(inner[0])}" '
                    f'y1="{_fmt(inner[1])}" x2="{_fmt(outer[0])}" '
                    f'y2="{_fmt(outer[1])}" stroke="{color}" '
                    f'stroke-width="{_fmt(center * 0.008)}" stroke-linecap="round"/>'
                ),
                (
                    f'      <text class="point-label" x="{_fmt(label[0])}" '
                    f'y="{_fmt(label[1])}" fill="{color}" '
                    f'font-family="system-ui, sans-serif" font-size="{_fmt(font_size)}" '
                    'font-weight="700" text-anchor="middle" dominant-baseline="central">'
                    f"{_xml(abbreviation)}</text>"
                ),
                "    </g>",
            )
        )
    lines.append("  </g>")
    return lines


def _point_label_lanes(
    points: tuple[_RenderPoint, ...],
    *,
    collision_orb_deg: float = 8.0,
) -> dict[str, int]:
    """Assign deterministic radial lanes to nearby labels on the circle."""

    assigned: list[tuple[float, int]] = []
    result: dict[str, int] = {}
    for point in sorted(points, key=lambda item: (item.longitude, item.id)):
        used = {
            lane
            for longitude, lane in assigned
            if min(
                (point.longitude - longitude) % 360.0,
                (longitude - point.longitude) % 360.0,
            )
            < collision_orb_deg
        }
        lane = 0
        while lane in used:
            lane += 1
        assigned.append((point.longitude, lane))
        result[point.id] = lane
    return result


def _overlay_legend(center: float, size: float) -> list[str]:
    font_size = size * 0.016
    x_start = center - size * 0.085
    x_end = center - size * 0.045
    text_x = center - size * 0.033
    return [
        '  <g class="wheel-legend" aria-label="Wheel layer legend">',
        (
            f'    <line x1="{_fmt(x_start)}" y1="{_fmt(center - font_size)}" '
            f'x2="{_fmt(x_end)}" y2="{_fmt(center - font_size)}" '
            f'stroke="#176b78" stroke-width="{_fmt(size * 0.006)}" '
            'stroke-linecap="round"/>'
        ),
        (
            f'    <text x="{_fmt(text_x)}" y="{_fmt(center - font_size)}" '
            f'fill="#176b78" font-family="system-ui, sans-serif" '
            f'font-size="{_fmt(font_size)}" font-weight="700" '
            'dominant-baseline="central">Natal</text>'
        ),
        (
            f'    <line x1="{_fmt(x_start)}" y1="{_fmt(center + font_size)}" '
            f'x2="{_fmt(x_end)}" y2="{_fmt(center + font_size)}" '
            f'stroke="#c14f38" stroke-width="{_fmt(size * 0.004)}" '
            'stroke-linecap="round"/>'
        ),
        (
            f'    <text x="{_fmt(text_x)}" y="{_fmt(center + font_size)}" '
            f'fill="#c14f38" font-family="system-ui, sans-serif" '
            f'font-size="{_fmt(font_size)}" font-weight="700" '
            'dominant-baseline="central">Moving sky</text>'
        ),
        "  </g>",
    ]


def _canonical_segments() -> tuple[tuple[str, float, float], ...]:
    """Return the canonical half-open boundary arcs, totaling exactly 360°."""

    segments = []
    for index, (sign_id, start) in enumerate(
        zip(EXPECTED_SIGN_IDS, EXPECTED_STARTS, strict=True)
    ):
        next_start = EXPECTED_STARTS[(index + 1) % len(EXPECTED_STARTS)]
        length = (next_start - start) % 360.0
        segments.append((sign_id, start, length))
    return tuple(segments)


def _read_chart(
    value: Chart | Mapping[str, Any],
    context: str,
    *,
    include_cusps: bool,
) -> _RenderChart:
    if isinstance(value, Chart):
        meta: Any = value.meta
        raw_points: Any = value.points
        raw_cusps: Any = value.cusps
    elif isinstance(value, Mapping):
        meta = _required(value, "meta", context)
        raw_points = _required(value, "points", context)
        raw_cusps = value.get("cusps")
    else:
        raise TypeError(f"{context} must be a Chart or its direct JSON object")

    zodiac_system = _required_string(meta, "zodiac_system", f"{context}.meta")
    if zodiac_system != "midpoint_v1":
        raise ValueError(
            f"{context}.meta.zodiac_system must be 'midpoint_v1', got {zodiac_system!r}"
        )
    boundary_version = _optional_string(meta, "boundary_version", f"{context}.meta")
    boundary_sha256 = _optional_string(meta, "boundary_sha256", f"{context}.meta")

    if not _is_sequence(raw_points):
        raise TypeError(f"{context}.points must be an array")
    seen_ids: set[str] = set()
    bodies: list[_RenderPoint] = []
    asc_longitude: float | None = None
    for index, item in enumerate(raw_points):
        point_context = f"{context}.points[{index}]"
        point_id = _required_string(item, "id", point_context)
        if not _SAFE_ID.fullmatch(point_id):
            raise ValueError(f"{point_context}.id is not a safe stable identifier")
        if point_id in seen_ids:
            raise ValueError(f"{context}.points contains duplicate id {point_id!r}")
        seen_ids.add(point_id)
        name = _required_string(item, "name", point_context)
        kind = _required_string(item, "kind", point_context)
        longitude = _longitude(_required(item, "lon_j2000", point_context), point_context)
        if point_id == "asc":
            asc_longitude = longitude
        if kind == "body":
            bodies.append(_RenderPoint(point_id, name, longitude))

    if not bodies:
        raise ValueError(f"{context} has no body points to render")
    bodies.sort(key=lambda point: (_BODY_ORDER.get(point.id, len(_BODY_ORDER)), point.id))

    cusps: tuple[_RenderCusp, ...] = ()
    if include_cusps and raw_cusps is not None:
        if not _is_sequence(raw_cusps):
            raise TypeError(f"{context}.cusps must be an array or null")
        parsed_cusps: list[_RenderCusp] = []
        seen_numbers: set[int] = set()
        for index, item in enumerate(raw_cusps):
            cusp_context = f"{context}.cusps[{index}]"
            number = _required(item, "number", cusp_context)
            if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= 12:
                raise ValueError(f"{cusp_context}.number must be an integer from 1 to 12")
            if number in seen_numbers:
                raise ValueError(f"{context}.cusps contains duplicate house {number}")
            seen_numbers.add(number)
            longitude = _longitude(
                _required(item, "lon_j2000", cusp_context), cusp_context
            )
            parsed_cusps.append(_RenderCusp(number, longitude))
        if len(parsed_cusps) != 12 or seen_numbers != set(range(1, 13)):
            raise ValueError(f"{context}.cusps must contain houses 1 through 12 exactly once")
        cusps = tuple(sorted(parsed_cusps, key=lambda cusp: cusp.number))

    return _RenderChart(
        zodiac_system=zodiac_system,
        boundary_version=boundary_version,
        boundary_sha256=boundary_sha256,
        points=tuple(bodies),
        asc_longitude=asc_longitude,
        cusps=cusps,
    )


def _validate_frame_compatibility(
    natal: _RenderChart,
    overlay: _RenderChart | None,
) -> None:
    if overlay is None:
        return
    if (
        natal.boundary_version
        and overlay.boundary_version
        and natal.boundary_version != overlay.boundary_version
    ):
        raise ValueError("chart and overlay_chart use different boundary versions")
    if (
        natal.boundary_sha256
        and overlay.boundary_sha256
        and natal.boundary_sha256 != overlay.boundary_sha256
    ):
        raise ValueError("chart and overlay_chart use different boundary data")


def _anchor_longitude(chart: _RenderChart) -> float:
    if chart.asc_longitude is not None:
        return chart.asc_longitude
    if chart.cusps:
        return chart.cusps[0].longitude
    return 0.0


def _validated_width(value: Real) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError("width must be a finite real number")
    width = float(value)
    if not math.isfinite(width):
        raise ValueError("width must be finite")
    if not _MIN_WIDTH <= width <= _MAX_WIDTH:
        raise ValueError(
            f"width must be between {_fmt(_MIN_WIDTH)} and {_fmt(_MAX_WIDTH)} pixels"
        )
    return width


def _longitude(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{context}.lon_j2000 must be a finite real number")
    longitude = float(value)
    if not math.isfinite(longitude):
        raise ValueError(f"{context}.lon_j2000 must be finite")
    if not 0.0 <= longitude < 360.0:
        raise ValueError(f"{context}.lon_j2000 must be in [0, 360)")
    return longitude


def _required(value: Any, field: str, context: str) -> Any:
    if isinstance(value, Mapping):
        if field not in value:
            raise ValueError(f"{context}.{field} is required")
        return value[field]
    if hasattr(value, field):
        return getattr(value, field)
    raise ValueError(f"{context}.{field} is required")


def _required_string(value: Any, field: str, context: str) -> str:
    item = _required(value, field, context)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"{context}.{field} must be a non-empty string")
    return item


def _optional_string(value: Any, field: str, context: str) -> str:
    if isinstance(value, Mapping):
        item = value.get(field, "")
    else:
        item = getattr(value, field, "")
    if not isinstance(item, str):
        raise ValueError(f"{context}.{field} must be a string")
    return item


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _screen_angle(longitude: float, anchor_longitude: float) -> float:
    return 180.0 - ((longitude - anchor_longitude) % 360.0)


def _polar(center: float, radius: float, angle_deg: float) -> tuple[float, float]:
    radians = math.radians(angle_deg)
    return (
        center + radius * math.cos(radians),
        center + radius * math.sin(radians),
    )


def _fmt(value: float, *, precision: int = 3) -> str:
    if abs(value) < 0.5 * 10 ** (-precision):
        value = 0.0
    return f"{value:.{precision}f}".rstrip("0").rstrip(".")


def _xml(value: str) -> str:
    return escape(value, quote=True)


__all__ = ["render_svg"]
