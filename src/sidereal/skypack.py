"""Geometry-only ``skypack_v2`` export for local planetarium consumers."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import math
from pathlib import Path
from typing import Any

from .aspects import shortest_arc
from .chart import compute
from .config import BODY_IDS, ChartConfig
from .library import DEFAULT_CHARTS_DIR, SavedChart, load_chart
from .timebase import parse_timezone, resolve_moment
from .transit import TransitGeometry, compute_transit_geometry
from .types import Chart, MomentInput, PointPos
from .zodiac.base import normalize_longitude
from .zodiac.midpoint import MidpointZodiac


SKYPACK_SCHEMA_VERSION = 2
SKYPACK_TYPE = "skypack"
SKYPACK_PROJECTION = "ecliptic_band_v2"

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
    """Load one saved natal chart and build its local ``skypack_v2`` document.

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

    return build_skypack_from_chart(
        record.chart_object(),
        record.chart_config(),
        natal_id=record.id,
        natal_label=record.label,
        when=when,
        tz=tz,
        boundary_path=boundary_path,
        ephe_path=ephe_path,
        require_swiss_ephemeris=require_swiss_ephemeris,
        privacy="local_only",
        generated_at=generated_at,
    )


def build_skypack_from_chart(
    natal_chart: Chart,
    natal_config: ChartConfig,
    *,
    natal_id: str,
    natal_label: str = "Saved sky",
    when: datetime | str | None = None,
    tz: str | None = None,
    boundary_path: Path | str | None = None,
    ephe_path: Path | str | None = None,
    require_swiss_ephemeris: bool = False,
    privacy: str = "user_private",
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a pack from private in-memory natal geometry.

    Authenticated callers use ``privacy='user_private'``.  The legacy
    saved-chart wrapper above deliberately retains ``local_only``.
    """

    if not isinstance(natal_chart, Chart):
        raise TypeError("natal_chart must be a Chart")
    if not isinstance(natal_config, ChartConfig):
        raise TypeError("natal_config must be a ChartConfig")
    if not isinstance(natal_id, str) or not natal_id.strip():
        raise ValueError("natal_id must be a non-empty string")
    if not isinstance(natal_label, str):
        raise ValueError("natal_label must be a string")
    if privacy not in {"local_only", "user_private"}:
        raise ValueError("privacy must be local_only or user_private")

    generated_utc = _generated_instant(generated_at)
    timezone_name = _timezone_name(tz, natal_chart.meta.input.tz)
    # Validate even when the epoch is already aware or defaults to now; the
    # timezone remains part of the public pack contract.
    parse_timezone(timezone_name)
    epoch_utc = _epoch_instant(when, timezone_name, default=generated_utc)

    base_config = natal_config
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
        natal_chart,
        transit_chart,
        active_config,
    )
    return _pack_from_geometry(
        geometry,
        zodiac,
        natal_id=natal_id.strip(),
        natal_label=natal_label,
        timezone_name=timezone_name,
        privacy=privacy,
        generated_at=generated_utc,
    )


def _pack_from_geometry(
    geometry: TransitGeometry,
    zodiac: MidpointZodiac,
    *,
    natal_id: str,
    natal_label: str,
    timezone_name: str,
    privacy: str,
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

    same_body_delta = _same_body_deltas(movers, natal_ghosts)
    resonance_rank = rank_resonances(resonances)

    return {
        "schema_version": SKYPACK_SCHEMA_VERSION,
        "type": SKYPACK_TYPE,
        "projection": SKYPACK_PROJECTION,
        "generated_at": _utc_isoformat(generated_at),
        "epoch_utc": _utc_isoformat(geometry.transit.meta.utc_datetime),
        "timezone": timezone_name,
        "location": None,
        "natal_id": natal_id,
        "natal_label": natal_label,
        "system": "midpoint_v1",
        "privacy": privacy,
        "sign_band": _sign_band(zodiac),
        "movers": movers,
        "natal_ghosts": natal_ghosts,
        "resonances": resonances,
        "same_body_delta": same_body_delta,
        "resonance_rank": resonance_rank,
    }


def _same_body_deltas(
    movers: list[dict[str, Any]],
    natal_ghosts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return shortest-arc deltas for ids present in both body collections."""

    natal_by_id = {item["id"]: item for item in natal_ghosts}
    result: list[dict[str, Any]] = []
    for mover in movers:
        body_id = mover["id"]
        natal = natal_by_id.get(body_id)
        if natal is None:
            continue
        mover_lon = _finite_number(
            mover["lon_j2000"],
            f"{body_id} mover longitude",
        )
        natal_lon = _finite_number(
            natal["lon_j2000"],
            f"{body_id} natal longitude",
        )
        result.append(
            {
                "id": body_id,
                "delta_deg": shortest_arc(mover_lon, natal_lon),
                "mover_lon_j2000": mover_lon,
                "natal_lon_j2000": natal_lon,
            }
        )
    return result


def rank_resonances(
    resonances: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return all resonances ranked by normalized orb, tightest first.

    A positive ``orb_limit`` is required for every row. Missing, non-finite,
    or non-positive limits are rejected rather than assigned a guessed sort
    position.
    """

    sortable: list[tuple[float, str, str, str, dict[str, Any]]] = []
    for index, resonance in enumerate(resonances):
        name = f"resonances[{index}]"
        try:
            transit_body = resonance["transit_body"]
            natal_point = resonance["natal_point"]
            aspect_id = resonance["aspect_id"]
            aspect_glyph = resonance["aspect_glyph"]
            raw_orb = resonance["orb"]
            raw_orb_limit = resonance["orb_limit"]
        except KeyError as exc:
            raise ValueError(
                f"{name} is missing required field {exc.args[0]!r}"
            ) from exc
        for field, value in (
            ("transit_body", transit_body),
            ("natal_point", natal_point),
            ("aspect_id", aspect_id),
            ("aspect_glyph", aspect_glyph),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name}.{field} must be a non-empty string")
        orb = _finite_number(raw_orb, f"{name}.orb")
        orb_limit = _finite_number(raw_orb_limit, f"{name}.orb_limit")
        if orb < 0.0:
            raise ValueError(f"{name}.orb must be non-negative")
        if orb_limit <= 0.0:
            raise ValueError(f"{name}.orb_limit must be positive")
        ranked = {
            "transit_body": transit_body,
            "natal_point": natal_point,
            "aspect_id": aspect_id,
            "aspect_glyph": aspect_glyph,
            "orb": orb,
            "orb_limit": orb_limit,
        }
        sortable.append(
            (
                orb / orb_limit,
                transit_body,
                natal_point,
                aspect_id,
                ranked,
            )
        )

    sortable.sort(key=lambda item: item[:4])
    return [
        {**item[4], "rank": rank}
        for rank, item in enumerate(sortable, start=1)
    ]


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


def build_sign_band(zodiac: MidpointZodiac) -> list[dict[str, Any]]:
    """Return the shared Midpoint sign-band wire representation."""

    return _sign_band(zodiac)


def build_body_entries(
    chart: Chart,
    *,
    moving: bool,
) -> list[dict[str, Any]]:
    """Return the shared ordered body wire representation for a chart."""

    return _body_entries(chart, moving=moving)


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
    "build_body_entries",
    "build_sign_band",
    "build_skypack",
    "build_skypack_from_chart",
    "build_skypack_from_saved_chart",
    "parse_local_datetime",
    "rank_resonances",
    "shortest_arc",
]
