"""Join transit geometry to symbolic interpretation records and render reports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, time
from enum import Enum
import json
from pathlib import Path
from typing import Any, Protocol

from ..config import ChartConfig
from ..transit import TransitGeometry, TransitPlacement, compute_transit_geometry
from ..types import Chart, MomentInput, TransitAspectHit
from .compose import ReportGap, _sign_colored_aspect_synthesis
from .schema import ANGLES, PLANETS, InterpretationEntry, aspect_key


TRANSIT_EPISTEMIC_NOTE = (
    "Transit relationships are geometric correlations between a moving sky and "
    "a fixed natal chart. Interpretations are symbolic study notes, not "
    "predictions or scientific claims about events, personality, health, or outcomes."
)
TRANSIT_MOON_WARNING = (
    "The transit Moon moves quickly; its placement and aspects are especially "
    "time-sensitive."
)


class EntryLookup(Protocol):
    def get(self, entry_id: str) -> InterpretationEntry | None:
        ...


@dataclass(frozen=True, slots=True)
class TransitReport:
    natal: Mapping[str, Any]
    transit: Mapping[str, Any]
    placements: tuple[TransitPlacement, ...]
    relationships: tuple[Mapping[str, Any], ...]
    gaps: tuple[ReportGap, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_version": 1,
            "report_type": "transit",
            "epistemic_note": TRANSIT_EPISTEMIC_NOTE,
            "natal": dict(self.natal),
            "transit": dict(self.transit),
            "placements": [placement.to_dict() for placement in self.placements],
            "relationships": [dict(item) for item in self.relationships],
            "gaps": [gap.to_dict() for gap in self.gaps],
            "warnings": list(self.warnings),
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            indent=indent,
            sort_keys=True,
            allow_nan=False,
        )

    def to_markdown(self) -> str:
        natal_label = str(self.natal.get("label") or "Untitled natal")
        lines = [
            f"# Transit study: {natal_label}",
            "",
            f"Natal moment: {self.natal.get('local_datetime', 'unknown')} "
            f"({self.natal.get('tz', 'unknown timezone')})",
            f"Transit moment: {self.transit.get('local_datetime', 'unknown')} "
            f"({self.transit.get('tz', 'unknown timezone')})",
            f"System: {self.transit.get('zodiac_system', 'unknown')}",
            "",
            "## Epistemic note",
            "",
            TRANSIT_EPISTEMIC_NOTE,
            "",
            "## Timing notes",
            "",
        ]
        for warning in self.warnings:
            lines.append(f"- {warning}")

        lines.extend(
            (
                "",
                "## Transit placements",
                "",
                "| Transit body | Midpoint placement | Natal house |",
                "|---|---|---:|",
            )
        )
        for placement in self.placements:
            house = str(placement.natal_house) if placement.natal_house is not None else "—"
            sensitivity = " (time-sensitive)" if placement.time_sensitive else ""
            blend = (
                f" ↔ {_display(placement.secondary_sign)}"
                if placement.blend and placement.secondary_sign
                else ""
            )
            lines.append(
                f"| {_display(placement.id)}{sensitivity} | "
                f"{_display(placement.sign)} {placement.degree_in_sign:.4f}°{blend} | "
                f"{house} |"
            )

        lines.extend(("", "## Transit–natal aspects", ""))
        if self.relationships:
            for item in self.relationships:
                aspect = item["aspect"]
                reading = item["reading"]
                character = item.get("character") if isinstance(item.get("character"), Mapping) else {}
                state = _motion_state(aspect.get("applying"), aspect.get("exactness"))
                title = str(
                    character.get("title")
                    or (
                        f"Transit {_display(str(aspect['transit_body']))} "
                        f"{str(aspect['aspect_id']).replace('_', ' ')} natal "
                        f"{_display(str(aspect['natal_point']))}"
                    )
                )
                lines.extend(
                    (
                        f"### {title}",
                        "",
                        f"Geometry: separation {float(aspect['separation']):.4f}°, "
                        f"orb {float(aspect['exactness']):.4f}°, {state}.",
                        "",
                    )
                )
                synthesis = str(character.get("synthesis") or "").strip()
                if synthesis:
                    lines.extend((synthesis, ""))
                _append_reading(lines, reading)
                for side_key, side_label in (
                    ("transit_placement", "Transit body · Midpoint sign character"),
                    ("natal_placement", "Natal point · Midpoint sign character"),
                ):
                    side = character.get(side_key)
                    if not isinstance(side, Mapping):
                        continue
                    side_reading = side.get("reading")
                    if isinstance(side_reading, Mapping):
                        lines.extend((f"#### {side_label}", ""))
                        _append_reading(lines, side_reading)
        else:
            lines.append("No configured major transit–natal aspects were found.")

        lines.extend(("", "## Missing interpretation keys", ""))
        if self.gaps:
            for gap in self.gaps:
                lines.append(
                    f"- `{gap.key}` ({gap.kind}) — {'; '.join(gap.contexts)}"
                )
        else:
            lines.append("None.")
        return "\n".join(lines).rstrip() + "\n"


def compose_transit_report(
    geometry: TransitGeometry,
    store: EntryLookup | None = None,
    *,
    natal_source: str = "inline",
    natal_id: str | None = None,
) -> TransitReport:
    """Join transit geometry to the primary interpretation database once."""

    resolver = _TransitResolver(store)
    natal_points = {
        str(getattr(point, "id")): point for point in geometry.natal.points
    }
    transit_by_id = {placement.id: placement for placement in geometry.placements}
    relationships: list[Mapping[str, Any]] = []
    for hit in sorted(
        geometry.aspects,
        key=lambda item: (
            -item.force,
            item.exactness,
            item.transit_body,
            item.natal_point,
            item.aspect_id,
        ),
    ):
        key = _transit_interpretation_key(hit)
        context = (
            f"transit {hit.transit_body} {hit.aspect_id} natal {hit.natal_point}"
        )
        relationships.append(
            {
                "aspect": _json_value(hit),
                "reading": resolver.resolve(key, context),
                "character": _transit_relationship_character(
                    resolver,
                    transit_by_id=transit_by_id,
                    natal_points=natal_points,
                    hit=hit,
                    context_prefix=context,
                ),
            }
        )

    transit_warnings = tuple(
        f"Transit calculation: {warning}"
        for warning in geometry.transit.meta.warnings
    )
    warnings = tuple(dict.fromkeys((TRANSIT_MOON_WARNING, *transit_warnings)))
    return TransitReport(
        natal={
            **_chart_summary(geometry.natal),
            "source": natal_source,
            "id": natal_id,
        },
        transit=_chart_summary(geometry.transit),
        placements=geometry.placements,
        relationships=tuple(relationships),
        gaps=resolver.gaps(),
        warnings=warnings,
    )


def calculate_transit_report(
    natal: Chart,
    transit_moment: MomentInput,
    config: ChartConfig,
    store: EntryLookup | None = None,
    *,
    natal_source: str = "inline",
    natal_id: str | None = None,
) -> TransitReport:
    """Calculate one transit chart through the primary engine and compose it."""

    from ..chart import compute

    transit_chart = compute(transit_moment, config)
    geometry = compute_transit_geometry(natal, transit_chart, config)
    return compose_transit_report(
        geometry,
        store,
        natal_source=natal_source,
        natal_id=natal_id,
    )


class _TransitResolver:
    def __init__(self, store: EntryLookup | None):
        self.store = store
        self.cache: dict[str, InterpretationEntry | None] = {}
        self.gap_kinds: dict[str, str] = {}
        self.gap_contexts: dict[str, list[str]] = {}

    def resolve(self, key: str, context: str) -> dict[str, Any]:
        if key not in self.cache:
            self.cache[key] = None if self.store is None else self.store.get(key)
        entry = self.cache[key]
        if entry is None:
            self._add_gap(key, "missing", context)
            return {
                "id": key,
                "status": "missing",
                "title": key,
                "keywords": [],
                "summary": "",
                "context": context,
            }
        if entry.status == "stub":
            self._add_gap(key, "stub", context)
        reading = entry.to_dict()
        reading["context"] = context
        return reading

    def _add_gap(self, key: str, kind: str, context: str) -> None:
        current = self.gap_kinds.get(key)
        if current is not None and current != kind:
            raise RuntimeError(f"gap {key!r} changed kind from {current!r} to {kind!r}")
        self.gap_kinds[key] = kind
        contexts = self.gap_contexts.setdefault(key, [])
        if context not in contexts:
            contexts.append(context)

    def gaps(self) -> tuple[ReportGap, ...]:
        return tuple(
            ReportGap(
                key=key,
                kind=self.gap_kinds[key],
                contexts=tuple(self.gap_contexts[key]),
            )
            for key in sorted(self.gap_kinds)
        )


def _transit_interpretation_key(hit: TransitAspectHit) -> str:
    if hit.transit_body == hit.natal_point:
        return f"aspect:{hit.transit_body}:{hit.aspect_id}:{hit.natal_point}"
    try:
        return aspect_key(hit.transit_body, hit.aspect_id, hit.natal_point)
    except ValueError:
        body_a, body_b = sorted((hit.transit_body, hit.natal_point))
        return f"aspect:{body_a}:{hit.aspect_id}:{body_b}"


def _transit_relationship_character(
    resolver: _TransitResolver,
    *,
    transit_by_id: Mapping[str, TransitPlacement],
    natal_points: Mapping[str, Any],
    hit: TransitAspectHit,
    context_prefix: str,
) -> dict[str, Any]:
    transit_placement = transit_by_id.get(hit.transit_body)
    natal_point = natal_points.get(hit.natal_point)
    transit_sign = transit_placement.sign if transit_placement is not None else None
    natal_sign = getattr(natal_point, "sign", None) if natal_point is not None else None

    transit_reading = None
    if transit_sign and hit.transit_body in PLANETS:
        transit_reading = resolver.resolve(
            f"planet_in_sign:{hit.transit_body}:{transit_sign}",
            f"{context_prefix} · transit sign character",
        )
    natal_reading = None
    if natal_sign and hit.natal_point in PLANETS:
        natal_reading = resolver.resolve(
            f"planet_in_sign:{hit.natal_point}:{natal_sign}",
            f"{context_prefix} · natal sign character",
        )
    elif natal_sign and hit.natal_point in ANGLES:
        natal_reading = resolver.resolve(
            f"angle_in_sign:{hit.natal_point}:{natal_sign}",
            f"{context_prefix} · natal angle sign character",
        )

    title_bits = ["Transit", _display(hit.transit_body)]
    if transit_sign:
        title_bits.extend(["in", _display(transit_sign)])
    title_bits.append(hit.aspect_id.replace("_", " "))
    title_bits.extend(["natal", _display(hit.natal_point)])
    if natal_sign:
        title_bits.extend(["in", _display(str(natal_sign))])
    synthesis = _sign_colored_aspect_synthesis(
        body_a=hit.transit_body,
        sign_a=transit_sign,
        body_b=hit.natal_point,
        sign_b=str(natal_sign) if natal_sign else None,
        aspect_id=hit.aspect_id,
    )
    if transit_sign and natal_sign:
        synthesis = (
            f"In transit timing language: moving {_display(hit.transit_body)} in "
            f"{_display(transit_sign)} contacts natal {_display(hit.natal_point)} in "
            f"{_display(str(natal_sign))}. {synthesis}"
        )
    return {
        "title": " ".join(title_bits),
        "synthesis": synthesis,
        "transit_placement": {
            "body": hit.transit_body,
            "sign": transit_sign,
            "natal_house": (
                transit_placement.natal_house if transit_placement is not None else None
            ),
            "reading": transit_reading,
        },
        "natal_placement": {
            "body": hit.natal_point,
            "sign": natal_sign,
            "house": getattr(natal_point, "house", None) if natal_point is not None else None,
            "reading": natal_reading,
        },
    }


def _chart_summary(chart: Chart) -> dict[str, Any]:
    return {
        "label": chart.meta.input.label,
        "local_datetime": chart.meta.local_datetime.isoformat(),
        "utc_datetime": chart.meta.utc_datetime.isoformat(),
        "tz": chart.meta.input.tz,
        "time_known": chart.meta.time_known,
        "location_known": chart.meta.location_known,
        "zodiac_system": chart.meta.zodiac_system,
        "house_system": chart.meta.house_system,
        "ephemeris_backend": chart.meta.ephemeris_backend,
    }


def _append_reading(lines: list[str], reading: Mapping[str, Any]) -> None:
    status = str(reading.get("status", "missing"))
    title = str(reading.get("title") or reading.get("id"))
    if status == "missing":
        lines.extend((f"**{title}** — interpretation record missing.", ""))
        return
    label = " _(stub)_" if status == "stub" else ""
    lines.extend((f"**{title}**{label}", "", str(reading.get("summary", "")), ""))
    if reading.get("growth"):
        lines.extend((f"Development notes: {reading['growth']}", ""))


def _motion_state(applying: Any, exactness: Any) -> str:
    if abs(float(exactness or 0.0)) <= 1e-10:
        return "exact"
    if applying is True:
        return "applying"
    if applying is False:
        return "separating"
    return "motion indeterminate"


def _display(identifier: str) -> str:
    special = {"asc": "Ascendant", "mc": "Midheaven"}
    return special.get(identifier, identifier.replace("_", " ").title())


def _json_value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _json_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


__all__ = [
    "TRANSIT_EPISTEMIC_NOTE",
    "TRANSIT_MOON_WARNING",
    "TransitReport",
    "calculate_transit_report",
    "compose_transit_report",
]
