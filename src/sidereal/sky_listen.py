"""Short local-only study responses for celestial Listen targets."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
import math
from pathlib import Path
from typing import Any, Protocol

from .aspects import TRANSIT_ASPECT_BODY_IDS, shortest_arc
from .chart import compute
from .config import ChartConfig
from .interpret.schema import InterpretationEntry, PLANETS, SIGNS
from .interpret.transit import TransitReport, calculate_transit_study
from .library import DEFAULT_CHARTS_DIR, load_chart
from .skypack import ASPECT_GLYPHS, parse_local_datetime
from .timebase import parse_timezone
from .transit import TransitGeometry, compute_transit_geometry
from .types import Chart, MomentInput, PointPos


SKY_LISTEN_SCHEMA_VERSION = 1
SKY_LISTEN_TYPE = "sky_listen"
SKY_LISTEN_SYSTEM = "midpoint_v1"
SKY_LISTEN_EPISTEMIC = "symbolic study notes, not predictions"
SKY_LISTEN_HIGHLIGHT_LIMIT = 5


class EntryLookup(Protocol):
    def get(self, entry_id: str) -> InterpretationEntry | None:
        ...


def build_sky_listen(
    *,
    natal_id: str | None = None,
    body: str | None = None,
    sign: str | None = None,
    kind: str | None = None,
    when: datetime | str | None = None,
    tz: str | None = None,
    charts_dir: Path | str = DEFAULT_CHARTS_DIR,
    boundary_path: Path | str | None = None,
    ephe_path: Path | str | None = None,
    require_swiss_ephemeris: bool = False,
    store: EntryLookup | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Calculate one moving sky and compose a compact Listen response."""

    target_kind, target_body, target_sign = normalize_sky_listen_target(
        body=body,
        sign=sign,
        kind=kind,
    )
    natal_identifier = _optional_non_empty(natal_id, "natal_id")
    record = (
        load_chart(natal_identifier, Path(charts_dir).expanduser())
        if natal_identifier is not None
        else None
    )
    timezone_name = _timezone_name(
        tz,
        record.tz if record is not None else "UTC",
    )
    transit_moment = _sky_moment(when, timezone_name, now=now)
    base_config = record.chart_config() if record is not None else ChartConfig()
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

    geometry: TransitGeometry | None = None
    report: TransitReport | None = None
    canonical_natal_id: str | None = None
    if record is None:
        transit_chart = compute(transit_moment, active_config)
    elif target_kind == "sign":
        natal_chart = record.chart_object()
        transit_chart = compute(transit_moment, active_config)
        geometry = compute_transit_geometry(
            natal_chart,
            transit_chart,
            active_config,
        )
        canonical_natal_id = record.id
    else:
        report, geometry = calculate_transit_study(
            record.chart_object(),
            transit_moment,
            active_config,
            store,
            natal_source="saved",
            natal_id=record.id,
        )
        transit_chart = geometry.transit
        canonical_natal_id = record.id

    return compose_sky_listen(
        transit_chart,
        kind=target_kind,
        body=target_body,
        sign=target_sign,
        timezone_name=timezone_name,
        store=store,
        natal_id=canonical_natal_id,
        geometry=geometry,
        transit_report=report,
    )


def normalize_sky_listen_target(
    *,
    body: str | None,
    sign: str | None,
    kind: str | None,
) -> tuple[str, str | None, str | None]:
    """Validate target selectors and apply the body-first default kind."""

    body_id = _optional_non_empty(body, "body")
    sign_id = _optional_non_empty(sign, "sign")
    selected_kind = _optional_non_empty(kind, "kind")
    if body_id is not None and body_id not in PLANETS:
        raise ValueError(f"unsupported sky-listen body: {body_id!r}")
    if sign_id is not None and sign_id not in SIGNS:
        raise ValueError(f"unsupported Midpoint sign: {sign_id!r}")
    if selected_kind is not None and selected_kind not in {"body", "sign"}:
        raise ValueError("kind must be 'body' or 'sign'")
    if selected_kind is None:
        if body_id is not None:
            selected_kind = "body"
        elif sign_id is not None:
            selected_kind = "sign"
        else:
            raise ValueError("provide a usable body or sign")
    if selected_kind == "body" and body_id is None:
        raise ValueError("body is required when kind='body'")
    if selected_kind == "sign" and sign_id is None:
        raise ValueError("sign is required when kind='sign'")
    return selected_kind, body_id, sign_id


def compose_sky_listen(
    transit_chart: Chart,
    *,
    kind: str,
    body: str | None,
    sign: str | None,
    timezone_name: str,
    store: EntryLookup | None = None,
    natal_id: str | None = None,
    geometry: TransitGeometry | None = None,
    transit_report: TransitReport | None = None,
) -> dict[str, Any]:
    """Map computed geometry and existing interpretation records to the API."""

    target_kind, target_body, requested_sign = normalize_sky_listen_target(
        body=body,
        sign=sign,
        kind=kind,
    )
    if transit_chart.meta.zodiac_system != SKY_LISTEN_SYSTEM:
        raise ValueError(
            f"sky-listen requires {SKY_LISTEN_SYSTEM}, got "
            f"{transit_chart.meta.zodiac_system!r}"
        )
    point: PointPos | None = None
    if target_kind == "body":
        assert target_body is not None
        point = _body_point(transit_chart, target_body)
        target_sign = point.sign
    else:
        assert requested_sign is not None
        target_sign = requested_sign

    target = {
        "kind": target_kind,
        "body": target_body if target_kind == "body" else None,
        "sign": target_sign,
        "lon_j2000": point.lon_j2000 if point is not None else None,
        "degree_in_sign": point.degree_in_sign if point is not None else None,
        "layer": "sky_now",
    }
    placement = _placement_block(
        kind=target_kind,
        body=target_body,
        sign=target_sign,
        store=store,
    )
    if natal_id is None:
        personal: dict[str, Any] = {"available": False}
    else:
        if geometry is None or (
            target_kind == "body" and transit_report is None
        ):
            raise ValueError(
                "personal body composition requires transit geometry and report"
            )
        personal = _personal_block(
            kind=target_kind,
            body=target_body,
            sign=target_sign,
            natal_id=natal_id,
            geometry=geometry,
            transit_report=transit_report,
        )

    return {
        "schema_version": SKY_LISTEN_SCHEMA_VERSION,
        "type": SKY_LISTEN_TYPE,
        "system": SKY_LISTEN_SYSTEM,
        "epistemic": SKY_LISTEN_EPISTEMIC,
        "epoch_utc": transit_chart.meta.utc_datetime.isoformat(),
        "timezone": timezone_name,
        "target": target,
        "placement": placement,
        "personal": personal,
    }


def _placement_block(
    *,
    kind: str,
    body: str | None,
    sign: str,
    store: EntryLookup | None,
) -> dict[str, Any]:
    title = _display(sign)
    entry_id = f"sign:{sign}"
    if kind == "body":
        assert body is not None
        title = f"{_display(body)} in {_display(sign)}"
        entry_id = f"planet_in_sign:{body}:{sign}"
    entry = store.get(entry_id) if store is not None else None
    if entry is None:
        return {
            "title": title,
            "text": (
                f"No authored interpretation seed is available for {title}; "
                "this response provides geometry only."
            ),
            "status": "missing",
        }

    text = entry.summary.strip()
    if entry.status == "stub":
        text = (
            f"This interpretation seed is a draft stub. {text}"
            if text
            else "This interpretation seed is a draft stub; use geometry only."
        )
    elif not text:
        text = "This interpretation seed has no authored summary; use geometry only."
    result = {
        "title": entry.title,
        "text": text,
        "status": entry.status,
    }
    development = entry.growth.strip()
    if development:
        result["development"] = development
    return result


def _personal_block(
    *,
    kind: str,
    body: str | None,
    sign: str,
    natal_id: str,
    geometry: TransitGeometry,
    transit_report: TransitReport | None,
) -> dict[str, Any]:
    if kind == "sign":
        return _sign_personal_block(
            sign=sign,
            natal_id=natal_id,
            geometry=geometry,
        )
    assert body is not None
    if transit_report is None:
        raise ValueError("personal body composition requires a transit report")
    transit_point = _body_point(geometry.transit, body)
    natal_point = _body_point(geometry.natal, body)
    relationships = _body_relationships(transit_report, body)
    highlighted_relationships: list[Mapping[str, Any]] = []
    highlights: list[dict[str, Any]] = []
    for relationship in relationships:
        aspect = relationship.get("aspect")
        if not isinstance(aspect, Mapping):
            continue
        aspect_id = str(aspect.get("aspect_id") or "")
        glyph = ASPECT_GLYPHS.get(aspect_id)
        if glyph is None:
            continue
        natal_point_id = str(aspect.get("natal_point") or "")
        highlight: dict[str, Any] = {
            "aspect_id": aspect_id,
            "aspect_glyph": glyph,
            "natal_point": natal_point_id,
            "orb": _finite_float(aspect.get("exactness"), "transit aspect orb"),
            "applying": aspect.get("applying"),
        }
        # Full symbolic note per seal (not just glyph + orb) for the Listen HUD.
        character = relationship.get("character")
        reading = relationship.get("reading")
        title_line = ""
        summary = ""
        status = "missing"
        if isinstance(character, Mapping):
            title_line = str(character.get("title") or "").strip()
            synth = str(character.get("synthesis") or "").strip()
            if synth:
                summary = synth
        if isinstance(reading, Mapping):
            if not title_line:
                title_line = str(reading.get("title") or "").strip()
            # Prefer authored aspect summary when ready; else keep synthesis.
            if reading.get("status") in {"ready", "user"} and str(
                reading.get("summary") or ""
            ).strip():
                summary = str(reading.get("summary") or "").strip()
                status = str(reading.get("status") or "ready")
            elif str(reading.get("summary") or "").strip() and not summary:
                summary = str(reading.get("summary") or "").strip()
                status = str(reading.get("status") or "stub")
            elif status == "missing" and reading.get("status"):
                status = str(reading.get("status"))
        if not title_line:
            title_line = (
                f"Transit {_display(body)} {aspect_id} natal "
                f"{_display(natal_point_id)}"
            )
        if not summary:
            summary = (
                f"Geometry only: moving {_display(body)} forms a {aspect_id} to natal "
                f"{_display(natal_point_id)}; no authored relationship essay is available yet."
            )
            status = "missing"
        highlight["title"] = title_line
        highlight["text"] = summary
        highlight["status"] = status
        if isinstance(reading, Mapping):
            growth = str(reading.get("growth") or "").strip()
            if growth:
                highlight["development"] = growth
        highlights.append(highlight)
        highlighted_relationships.append(relationship)
        if len(highlights) == SKY_LISTEN_HIGHLIGHT_LIMIT:
            break

    title = f"Transit {_display(body)} to your chart"
    if not highlighted_relationships:
        if body in TRANSIT_ASPECT_BODY_IDS:
            text = (
                f"No configured major transit-to-natal aspects involving moving "
                f"{_display(body)} were found at this epoch; the same-body delta is "
                "available as geometric context."
            )
        else:
            text = (
                f"Transit-to-natal aspect highlights are not configured for moving "
                f"{_display(body)}; the same-body delta remains available as geometric "
                "context."
            )
    else:
        # Overview blurb; full per-aspect essays live on each highlight.
        authored_n = sum(
            1
            for relationship in highlighted_relationships
            if _relationship_has_authored_reading(relationship)
        )
        text = (
            f"Moving {_display(body)} forms {len(highlights)} major contact"
            f"{'s' if len(highlights) != 1 else ''} with your natal chart below"
            f"{f' ({authored_n} with authored notes)' if authored_n else ''}. "
            "Each seal is a symbolic study lens, not a prediction."
        )
        first = highlights[0]
        if first.get("title"):
            title = str(first["title"])

    result: dict[str, Any] = {
        "available": True,
        "natal_id": natal_id,
        "delta_deg": shortest_arc(
            transit_point.lon_j2000,
            natal_point.lon_j2000,
        ),
        "title": title,
        "text": text,
        "highlights": highlights,
    }
    placement = next(
        (item for item in geometry.placements if item.id == body),
        None,
    )
    if placement is not None and placement.natal_house is not None:
        result["natal_house"] = placement.natal_house
    return result


def _sign_personal_block(
    *,
    sign: str,
    natal_id: str,
    geometry: TransitGeometry,
) -> dict[str, Any]:
    natal_points = [
        point.id
        for point in geometry.natal.points
        if point.kind == "body" and point.id in PLANETS and point.sign == sign
    ]
    sky_bodies = [
        point.id
        for point in geometry.transit.points
        if point.kind == "body" and point.id in PLANETS and point.sign == sign
    ]
    sign_name = _display(sign)
    natal_text = ", ".join(_display(item) for item in natal_points) or "none"
    sky_text = ", ".join(_display(item) for item in sky_bodies) or "none"
    return {
        "available": True,
        "natal_id": natal_id,
        "title": f"{sign_name} across this saved chart",
        "text": (
            f"Natal chart bodies in {sign_name}: {natal_text}. "
            f"Moving sky bodies there at this epoch: {sky_text}."
        ),
        "highlights": [],
        "natal_points": natal_points,
        "sky_bodies": sky_bodies,
    }


def _body_relationships(
    report: TransitReport,
    body: str,
) -> list[Mapping[str, Any]]:
    relationships = [
        item
        for item in report.relationships
        if isinstance(item.get("aspect"), Mapping)
        and item["aspect"].get("transit_body") == body
    ]
    return sorted(relationships, key=_relationship_tightness_key)


def _relationship_tightness_key(
    relationship: Mapping[str, Any],
) -> tuple[float, str, str]:
    aspect = relationship["aspect"]
    assert isinstance(aspect, Mapping)
    orb = _finite_float(aspect.get("exactness"), "transit aspect orb")
    orb_limit = _finite_float(aspect.get("orb_used"), "transit aspect orb limit")
    if orb_limit <= 0.0:
        raise ValueError("transit aspect orb limit must be positive")
    return (
        orb / orb_limit,
        str(aspect.get("natal_point") or ""),
        str(aspect.get("aspect_id") or ""),
    )


def _relationship_has_authored_reading(
    relationship: Mapping[str, Any],
) -> bool:
    reading = relationship.get("reading")
    return (
        isinstance(reading, Mapping)
        and reading.get("status") in {"ready", "user"}
        and bool(str(reading.get("summary") or "").strip())
    )


def _body_point(chart: Chart, body: str) -> PointPos:
    matches = tuple(
        point
        for point in chart.points
        if point.kind == "body" and point.id == body
    )
    if len(matches) != 1:
        raise ValueError(
            f"chart must contain exactly one sky-listen body {body!r}"
        )
    return matches[0]


def _sky_moment(
    when: datetime | str | None,
    timezone_name: str,
    *,
    now: datetime | None,
) -> MomentInput:
    parse_timezone(timezone_name)
    if when is None:
        instant = _current_utc(now)
        return MomentInput(
            local_date=instant.date(),
            local_time=instant.timetz().replace(tzinfo=None),
            tz="UTC",
            label="Sky Listen",
        )
    parsed = parse_local_datetime(when) if isinstance(when, str) else when
    if not isinstance(parsed, datetime):
        raise TypeError("when must be a datetime, ISO local datetime string, or None")
    if parsed.tzinfo is not None:
        instant = parsed.astimezone(UTC)
        return MomentInput(
            local_date=instant.date(),
            local_time=instant.timetz().replace(tzinfo=None),
            tz="UTC",
            label="Sky Listen",
        )
    return MomentInput(
        local_date=parsed.date(),
        local_time=parsed.time(),
        tz=timezone_name,
        label="Sky Listen",
        fold=parsed.fold if parsed.fold == 1 else None,
    )


def _current_utc(value: datetime | None) -> datetime:
    selected = datetime.now(UTC).replace(microsecond=0) if value is None else value
    if not isinstance(selected, datetime):
        raise TypeError("now must be a datetime or None")
    if selected.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return selected.astimezone(UTC)


def _timezone_name(value: str | None, fallback: str) -> str:
    selected = fallback if value is None else value
    if not isinstance(selected, str) or not selected.strip():
        raise ValueError("tz must be a non-empty IANA zone or UTC offset")
    return selected.strip()


def _optional_non_empty(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string when provided")
    return value.strip()


def _finite_float(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _display(identifier: str) -> str:
    return identifier.replace("_", " ").title()


__all__ = [
    "SKY_LISTEN_EPISTEMIC",
    "SKY_LISTEN_HIGHLIGHT_LIMIT",
    "SKY_LISTEN_SCHEMA_VERSION",
    "SKY_LISTEN_SYSTEM",
    "SKY_LISTEN_TYPE",
    "build_sky_listen",
    "compose_sky_listen",
    "normalize_sky_listen_target",
]
