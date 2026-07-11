"""Geometry-only ``skypack_v1`` export for local planetarium consumers."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import math
from pathlib import Path
from typing import Any

from .chart import compute
from .config import BODY_IDS
from .library import DEFAULT_CHARTS_DIR, SavedChart, load_chart
from .timebase import parse_timezone, resolve_moment
from .transit import TransitGeometry, compute_transit_geometry
from .types import Chart, MomentInput, PointPos
from .zodiac.base import normalize_longitude
from .zodiac.midpoint import MidpointZodiac


SKYPACK_SCHEMA_VERSION = 1
SKYPACK_TYPE = "skypack"
SKYPACK_PROJECTION = "ecliptic_dome_v1"

BODY_GLYPHS: dict[str, str] = {
    "sun": "☉",
    "moon": "☽",
    "mercury": "☿",
    "venus": "♀",
    "mars": "♂",
    "jupiter": "♃",
    "saturn": "♄",
    "uranus": "♅",
    "neptune": "♆",
    "pluto": "♇",
    "north_node": "☊",
    "south_node": "☋",
}

ASPECT_GLYPHS: dict[str, str] = {
    "conjunction": "☌",
    "opposition": "☍",
    "trine": "△",
    "square": "□",
    "sextile": "⚹",
}

SIGN_GLYPHS: dict[str, str] = {
    "aries": "♈",
    "taurus": "♉",
    "gemini": "♊",
    "cancer": "♋",
    "leo": "♌",
    "virgo": "♍",
    "libra": "♎",
    "scorpio": "♏",
    "ophiuchus": "⛎",
    "sagittarius": "♐",
    "capricorn": "♑",
    "aquarius": "♒",
    "pisces": "♓",
}

_LUMINARY_IDS = frozenset(("sun", "moon"))
_NODE_IDS = frozenset(("north_node", "south_node"))


def parse_local_datetime(value: str) -> datetime:
    """Parse the CLI/API ``when`` value as an offset-free local datetime."""

    text = value.strip()
    if not text or ("T" not in text and " " not in text):
        raise ValueError(
            "when must be an ISO local datetime (YYYY-MM-DDTHH:MM[:SS])"
        )
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            "when must be an ISO local datetime (YYYY-MM-DDTHH:MM[:SS])"
        ) from exc
    if parsed.tzinfo is not None:
        raise ValueError("when must not include a UTC offset; use tz")
    return parsed


def build_skypack(
    natal_id: str,
    *,
    when: datetime | str | None = None,
    tz: str | None = None,
    charts_dir: Path | str = DEFAULT_CHARTS_DIR,
    boundary_path: Path | str | None = None,
    ephe_path: Path | str | None = None,
    require_swiss_ephemeris: bool = False,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Load one saved natal chart and build its local ``skypack_v1`` document.

    An offset-free ``when`` is interpreted in ``tz``. When ``tz`` is omitted,
    the saved natal chart's timezone is used. When ``when`` is omitted, the
    build instant is used as the moving-sky epoch.
    """

    record = load_chart(natal_id, Path(charts_dir).expanduser())
    return build_skypack_from_saved_chart(
        record,
        when=when,
        tz=tz,
        boundary_path=boundary_path,
        ephe_path=ephe_path,
        require_swiss_ephemeris=require_swiss_ephemeris,
        generated_at=generated_at,
    )


def build_skypack_from_saved_chart(
    record: SavedChart,
    *,
    when: datetime | str | None = None,
    tz: str | None = None,
    boundary_path: Path | str | None = None,
    ephe_path: Path | str | None = None,
    require_swiss_ephemeris: bool = False,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a pack from an already-loaded, validated saved-chart record."""

    generated_utc = _generated_instant(generated_at)
    timezone_name = _timezone_name(tz, record.tz)
    # Validate even when the epoch is already aware or defaults to now; the
    # timezone remains part of the public pack contract.
    parse_timezone(timezone_name)
    epoch_utc = _epoch_instant(when, timezone_name, default=generated_utc)

    base_config = record.chart_config()
    active_config = replace(
        base_config,
        boundary_path=(
            Path(boundary_path).expanduser()
            if boundary_path is not None
            else base_config.boundary_path
        ),
        ephe_path=(
            Path(ephe_path).expanduser()
            if ephe_path is not None
            else base_config.ephe_path
        ),
        require_swiss_ephemeris=(
            require_swiss_ephemeris or base_config.require_swiss_ephemeris
        ),
        include_houses=False,
        include_patterns=False,
    )
    active_config.validate()
    zodiac = MidpointZodiac.load_default(active_config.boundary_path)
    transit_moment = MomentInput(
        local_date=epoch_utc.date(),
        local_time=epoch_utc.timetz().replace(tzinfo=None),
        tz="UTC",
        label="Sky",
    )
    transit_chart = compute(transit_moment, active_config, zodiac=zodiac)
    geometry = compute_transit_geometry(
        record.chart_object(),
        transit_chart,
        active_config,
    )
    return _pack_from_geometry(
        record,
        geometry,
        zodiac,
        timezone_name=timezone_name,
        generated_at=generated_utc,
    )


def _pack_from_geometry(
    record: SavedChart,
    geometry: TransitGeometry,
    zodiac: MidpointZodiac,
    *,
    timezone_name: str,
    generated_at: datetime,
) -> dict[str, Any]:
    movers = _body_entries(geometry.transit, moving=True)
    natal_ghosts = _body_entries(geometry.natal, moving=False)
    mover_ids = {item["id"] for item in movers}
    ghost_ids = {item["id"] for item in natal_ghosts}

    resonances = []
    for hit in geometry.aspects:
        if hit.transit_body not in mover_ids or hit.natal_point not in ghost_ids:
            continue
        glyph = ASPECT_GLYPHS.get(hit.aspect_id)
        if glyph is None:
            continue
        applying = hit.applying
        if applying is not None and not isinstance(applying, bool):
            raise ValueError("Transit aspect applying state must be boolean or null")
        resonances.append(
            {
                "transit_body": hit.transit_body,
                "natal_point": hit.natal_point,
                "aspect_id": hit.aspect_id,
                "aspect_glyph": glyph,
                "separation": _finite_number(hit.separation, "separation"),
                "orb": _finite_number(hit.exactness, "orb"),
                "orb_limit": _finite_number(hit.orb_used, "orb_limit"),
                "applying": applying,
            }
        )

    return {
        "schema_version": SKYPACK_SCHEMA_VERSION,
        "type": SKYPACK_TYPE,
        "projection": SKYPACK_PROJECTION,
        "generated_at": _utc_isoformat(generated_at),
        "epoch_utc": _utc_isoformat(geometry.transit.meta.utc_datetime),
        "timezone": timezone_name,
        "location": None,
        "natal_id": record.id,
        "natal_label": record.label,
        "system": "midpoint_v1",
        "privacy": "local_only",
        "sign_band": _sign_band(zodiac),
        "movers": movers,
        "natal_ghosts": natal_ghosts,
        "resonances": resonances,
    }


def _sign_band(zodiac: MidpointZodiac) -> list[dict[str, Any]]:
    signs = zodiac.signs
    return [
        {
            "id": sign.id,
            "glyph": SIGN_GLYPHS[sign.id],
            "lon_start_j2000": _longitude(sign.start_deg, f"{sign.id} start"),
            "lon_end_j2000": _longitude(
                signs[(index + 1) % len(signs)].start_deg,
                f"{sign.id} end",
            ),
        }
        for index, sign in enumerate(signs)
    ]


def _body_entries(chart: Chart, *, moving: bool) -> list[dict[str, Any]]:
    by_id: dict[str, PointPos] = {}
    for point in chart.points:
        if point.kind != "body" or point.id not in BODY_GLYPHS:
            continue
        if point.id in by_id:
            raise ValueError(f"Duplicate body point in chart: {point.id!r}")
        by_id[point.id] = point
    missing = tuple(body_id for body_id in BODY_IDS if body_id not in by_id)
    if missing:
        raise ValueError(f"Chart is missing skypack bodies: {', '.join(missing)}")

    result: list[dict[str, Any]] = []
    for body_id in BODY_IDS:
        point = by_id[body_id]
        if point.sign not in SIGN_GLYPHS:
            raise ValueError(f"Unknown Midpoint sign on {body_id!r}: {point.sign!r}")
        entry: dict[str, Any] = {
            "id": body_id,
            "name": point.name,
            "glyph": BODY_GLYPHS[body_id],
            "lon_j2000": _longitude(point.lon_j2000, f"{body_id} longitude"),
            "sign": point.sign,
            "degree_in_sign": _finite_number(
                point.degree_in_sign,
                f"{body_id} degree_in_sign",
            ),
            "kind": _body_kind(body_id),
        }
        if moving:
            entry["retro"] = bool(point.retro)
        result.append(entry)
    return result


def _body_kind(body_id: str) -> str:
    if body_id in _LUMINARY_IDS:
        return "luminary"
    if body_id in _NODE_IDS:
        return "node"
    return "planet"


def _timezone_name(value: str | None, fallback: str) -> str:
    selected = fallback if value is None else value
    if not isinstance(selected, str) or not selected.strip():
        raise ValueError("tz must be a non-empty IANA zone or UTC offset")
    return selected.strip()


def _epoch_instant(
    value: datetime | str | None,
    timezone_name: str,
    *,
    default: datetime,
) -> datetime:
    if value is None:
        return default
    parsed = parse_local_datetime(value) if isinstance(value, str) else value
    if not isinstance(parsed, datetime):
        raise TypeError("when must be a datetime, ISO local datetime string, or None")
    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC)
    local_moment = MomentInput(
        local_date=parsed.date(),
        local_time=parsed.time(),
        tz=timezone_name,
        label="Sky",
        fold=parsed.fold if parsed.fold == 1 else None,
    )
    return resolve_moment(local_moment).utc_datetime


def _generated_instant(value: datetime | None) -> datetime:
    selected = datetime.now(UTC).replace(microsecond=0) if value is None else value
    if not isinstance(selected, datetime):
        raise TypeError("generated_at must be a datetime or None")
    if selected.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    return selected.astimezone(UTC)


def _utc_isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("skypack timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _finite_number(value: float, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _longitude(value: float, name: str) -> float:
    return normalize_longitude(_finite_number(value, name))


__all__ = [
    "ASPECT_GLYPHS",
    "BODY_GLYPHS",
    "SIGN_GLYPHS",
    "SKYPACK_PROJECTION",
    "SKYPACK_SCHEMA_VERSION",
    "SKYPACK_TYPE",
    "build_skypack",
    "build_skypack_from_saved_chart",
    "parse_local_datetime",
]
