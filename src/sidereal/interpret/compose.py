"""Join immutable chart geometry to symbolic interpretation records."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, time
from enum import Enum
import json
from pathlib import Path
from typing import Any, Mapping, Protocol

from .schema import ANGLES, ASPECT_TYPES, PLANETS, InterpretationEntry, aspect_key


EPISTEMIC_NOTE = (
    "Positions, houses, and angular relationships are astronomical geometry. "
    "Interpretations are symbolic cultural study notes, not scientific claims "
    "about personality, fate, health, or outcomes."
)


class EntryLookup(Protocol):
    def get(self, entry_id: str) -> InterpretationEntry | None:
        ...


@dataclass(frozen=True, slots=True)
class ReportGap:
    key: str
    kind: str  # "stub" or "missing"
    contexts: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "kind": self.kind, "contexts": list(self.contexts)}


@dataclass(frozen=True, slots=True)
class InterpretationReport:
    """A JSON/Markdown-ready report with geometry and lore kept distinct."""

    chart: Mapping[str, Any]
    planet_readings: tuple[Mapping[str, Any], ...]
    angle_readings: tuple[Mapping[str, Any], ...]
    house_readings: tuple[Mapping[str, Any], ...]
    relationships: tuple[Mapping[str, Any], ...]
    patterns: tuple[Mapping[str, Any], ...]
    gaps: tuple[ReportGap, ...]
    comparison: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "report_version": 1,
            "epistemic_note": EPISTEMIC_NOTE,
            "chart": dict(self.chart),
            "interpretation": {
                "planets": [dict(item) for item in self.planet_readings],
                "angles": [dict(item) for item in self.angle_readings],
                "houses": [dict(item) for item in self.house_readings],
                "relationships": [dict(item) for item in self.relationships],
                "patterns": [dict(item) for item in self.patterns],
            },
            "gaps": [gap.to_dict() for gap in self.gaps],
        }
        if self.comparison is not None:
            result["comparison"] = _json_value(self.comparison)
        return result

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            indent=indent,
            sort_keys=True,
            allow_nan=False,
        )

    def to_markdown(self) -> str:
        meta = self.chart.get("meta", {})
        meta = meta if isinstance(meta, Mapping) else {}
        inputs = meta.get("input", {})
        inputs = inputs if isinstance(inputs, Mapping) else {}
        label = str(inputs.get("label") or "Untitled")
        local = str(meta.get("local_datetime") or inputs.get("local_date") or "unknown")
        timezone = str(inputs.get("tz") or "unknown timezone")
        jd_ut = _format_number(meta.get("jd_ut"), 8)
        zodiac = str(meta.get("zodiac_system") or "unknown")
        houses = str(meta.get("house_system") or "not calculated")
        aspects = str(meta.get("aspect_profile") or "unknown")
        blend_orb = _format_number(meta.get("blend_orb_deg", 3.0), 2)

        lines = [
            f"# Chart: {label}",
            "",
            f"Moment: {local} ({timezone}) → JD(UT) {jd_ut}",
            f"System: {zodiac} · Houses: {houses} · Orbs: {aspects}",
        ]
        assumption = meta.get("calculation_time_assumption")
        if assumption:
            lines.append(f"Calculation assumption: {assumption}")
        warnings = meta.get("warnings", ())
        if isinstance(warnings, (list, tuple)):
            for warning in warnings:
                lines.append(f"Calculation warning: {warning}")
        lines.extend(("", "## Epistemic note", "", EPISTEMIC_NOTE, "", "## Angles", ""))
        if self.angle_readings:
            for item in self.angle_readings:
                lines.append(f"- {_format_point(item['point'])}")
        else:
            if meta.get("time_known") and meta.get("location_known"):
                lines.append("Angles were not calculated because houses and angles were disabled by configuration.")
            elif not meta.get("time_known"):
                lines.append("Angles were not calculated because the civil time is unknown.")
            else:
                lines.append("Angles were not calculated because a location was not available.")

        lines.extend(("", "## Planets", ""))
        if self.planet_readings:
            for item in self.planet_readings:
                lines.append(f"- {_format_point(item['point'])}")
        else:
            lines.append("No planetary positions are available.")

        lines.extend(("", "## Sign on each house", ""))
        if self.house_readings:
            for item in self.house_readings:
                cusp = item["cusp"]
                text = (
                    f"- House {cusp['number']}: {_display(str(cusp['sign']))} "
                    f"({_format_number(cusp['degree_in_sign'], 4)}° in sign)"
                )
                if cusp.get("blend") and cusp.get("secondary_sign"):
                    text += (
                        f" — within {blend_orb}° of the boundary with "
                        f"{_display(str(cusp['secondary_sign']))}"
                    )
                lines.append(text)
        else:
            lines.append("Houses were not calculated; no cusp signs have been inferred.")

        if self.comparison is not None:
            _append_comparison(lines, self.comparison)

        lines.extend(("", "## Placement readings", ""))
        if self.planet_readings:
            for item in self.planet_readings:
                point = item["point"]
                house_note = (
                    f" · House {point['house']}"
                    if point.get("house") is not None
                    else ""
                )
                blend_note = (
                    f" — within {blend_orb}° of the boundary with "
                    f"{_display(str(point['secondary_sign']))}"
                    if point.get("blend") and point.get("secondary_sign")
                    else ""
                )
                lines.extend(
                    (
                        f"### {_display(str(point['id']))} · {_display(str(point['sign']))}{house_note}{blend_note}",
                        "",
                    )
                )
                _append_readings(lines, item["readings"])
        else:
            lines.append("No placement readings are available.")

        if self.angle_readings:
            lines.extend(("", "## Angle readings", ""))
            for item in self.angle_readings:
                if not item["readings"]:
                    continue
                point = item["point"]
                blend_note = (
                    f" — within {blend_orb}° of the boundary with "
                    f"{_display(str(point['secondary_sign']))}"
                    if point.get("blend") and point.get("secondary_sign")
                    else ""
                )
                lines.extend(
                    (
                        f"### {_display(str(point['id']))} in {_display(str(point['sign']))}{blend_note}",
                        "",
                    )
                )
                _append_readings(lines, item["readings"])

        lines.extend(("", "## House cusp readings", ""))
        if self.house_readings:
            for item in self.house_readings:
                cusp = item["cusp"]
                blend_note = (
                    f" — within {blend_orb}° of the boundary with "
                    f"{_display(str(cusp['secondary_sign']))}"
                    if cusp.get("blend") and cusp.get("secondary_sign")
                    else ""
                )
                lines.extend(
                    (
                        f"### House {cusp['number']} · {_display(str(cusp['sign']))}{blend_note}",
                        "",
                    )
                )
                _append_readings(lines, item["readings"])
        else:
            lines.append("No house cusp readings are applicable.")

        lines.extend(("", "## Relationships", ""))
        if self.relationships:
            for item in self.relationships:
                aspect = item["aspect"]
                state = (
                    "exact"
                    if abs(float(aspect.get("exactness", 0.0))) <= 1e-10
                    else "applying"
                    if aspect.get("applying") is True
                    else "separating"
                    if aspect.get("applying") is False
                    else "motion indeterminate"
                )
                lines.extend(
                    (
                        f"### {_display(str(aspect['body_a']))} {str(aspect['aspect_id']).replace('_', ' ')} "
                        f"{_display(str(aspect['body_b']))}",
                        "",
                        f"Geometry: separation {_format_number(aspect['separation'], 4)}°, "
                        f"orb {_format_number(aspect['exactness'], 4)}°, {state}.",
                        "",
                    )
                )
                _append_readings(lines, (item["reading"],))
        else:
            lines.append("No configured major aspects were found.")

        lines.extend(("", "## Patterns", ""))
        if self.patterns:
            for item in self.patterns:
                pattern = item["pattern"]
                members = ", ".join(_display(str(member)) for member in pattern.get("members", ()))
                lines.extend((f"### {_display(str(pattern['pattern_id']))}", "", f"Members: {members}.", ""))
                _append_readings(lines, (item["reading"],))
        else:
            lines.append("No configured structural patterns were found.")

        lines.extend(("", "## Missing interpretation keys", ""))
        if self.gaps:
            for gap in self.gaps:
                contexts = "; ".join(gap.contexts)
                lines.append(f"- `{gap.key}` ({gap.kind}) — {contexts}")
        else:
            lines.append("None.")
        return "\n".join(lines).rstrip() + "\n"


class _Resolver:
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
            ReportGap(key=key, kind=self.gap_kinds[key], contexts=tuple(self.gap_contexts[key]))
            for key in sorted(self.gap_kinds)
        )


def compose_report(
    chart: Any,
    store: EntryLookup | None = None,
    *,
    comparison: Mapping[str, Any] | None = None,
) -> InterpretationReport:
    """Compose one chart without mutating or embellishing its geometry.

    A present stub is rendered and also reported as a ``stub`` gap. An absent
    record is rendered as an empty ``missing`` reading and reported separately.
    Passing ``store=None`` therefore still produces a complete report shape.
    """

    if isinstance(chart, Mapping) or not hasattr(chart, "to_dict"):
        raise TypeError(
            "chart must be a Chart-like object with geometry attributes, not a mapping"
        )
    chart_data = _json_value(chart.to_dict())
    if not isinstance(chart_data, Mapping):
        raise TypeError("chart must serialize to an object")
    resolver = _Resolver(store)

    planet_readings: list[Mapping[str, Any]] = []
    angle_readings: list[Mapping[str, Any]] = []
    for point in getattr(chart, "points", ()):
        point_data = _json_value(point)
        point_id = str(getattr(point, "id"))
        if point_id in PLANETS:
            readings = [resolver.resolve(f"planet:{point_id}", f"{point_id} principle")]
            sign = str(getattr(point, "sign"))
            readings.append(
                resolver.resolve(
                    f"planet_in_sign:{point_id}:{sign}",
                    f"{point_id} primary sign placement",
                )
            )
            secondary = getattr(point, "secondary_sign", None)
            if bool(getattr(point, "blend", False)) and secondary:
                readings.append(
                    resolver.resolve(
                        f"planet_in_sign:{point_id}:{secondary}",
                        f"{point_id} adjacent sign within boundary blend orb",
                    )
                )
            house = getattr(point, "house", None)
            if house is not None:
                readings.append(
                    resolver.resolve(
                        f"planet_in_house:{point_id}:{house}",
                        f"{point_id} house {house} placement",
                    )
                )
            planet_readings.append({"point": point_data, "readings": readings})
        elif point_id in {"asc", "mc", "desc", "ic"}:
            readings: list[dict[str, Any]] = []
            if point_id in ANGLES:
                sign = str(getattr(point, "sign"))
                readings.append(
                    resolver.resolve(
                        f"angle_in_sign:{point_id}:{sign}",
                        f"{point_id} primary sign placement",
                    )
                )
                secondary = getattr(point, "secondary_sign", None)
                if bool(getattr(point, "blend", False)) and secondary:
                    readings.append(
                        resolver.resolve(
                            f"angle_in_sign:{point_id}:{secondary}",
                            f"{point_id} adjacent sign within boundary blend orb",
                        )
                    )
            angle_readings.append({"point": point_data, "readings": readings})

    house_readings: list[Mapping[str, Any]] = []
    for cusp in getattr(chart, "cusps", None) or ():
        cusp_data = _json_value(cusp)
        number = int(getattr(cusp, "number", getattr(cusp, "house", 0)))
        sign = str(getattr(cusp, "sign"))
        reading = resolver.resolve(
            f"sign_on_house:{sign}:{number}",
            f"{sign} on house {number} cusp",
        )
        house_readings.append({"cusp": cusp_data, "readings": [reading]})

    relationships: list[Mapping[str, Any]] = []
    for aspect in sorted(getattr(chart, "aspects", ()), key=_relationship_sort_key):
        body_a = str(getattr(aspect, "body_a"))
        body_b = str(getattr(aspect, "body_b"))
        aspect_id = str(getattr(aspect, "aspect_id"))
        try:
            key = aspect_key(body_a, aspect_id, body_b)
        except ValueError:
            # Future/minor aspects remain visible as explicit missing keys.
            a, b = sorted((body_a, body_b))
            key = f"aspect:{a}:{aspect_id}:{b}"
        context = f"{body_a} {aspect_id} {body_b} relationship"
        relationships.append(
            {
                "aspect": _json_value(aspect),
                "reading": resolver.resolve(key, context),
            }
        )

    patterns: list[Mapping[str, Any]] = []
    for pattern in getattr(chart, "patterns", ()):
        pattern_id = str(getattr(pattern, "pattern_id"))
        patterns.append(
            {
                "pattern": _json_value(pattern),
                "reading": resolver.resolve(
                    f"pattern:{pattern_id}", f"{pattern_id} structural pattern"
                ),
            }
        )

    return InterpretationReport(
        chart=dict(chart_data),
        planet_readings=tuple(planet_readings),
        angle_readings=tuple(angle_readings),
        house_readings=tuple(house_readings),
        relationships=tuple(relationships),
        patterns=tuple(patterns),
        gaps=resolver.gaps(),
        comparison=comparison,
    )


def _json_value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
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


def _display(identifier: str) -> str:
    special = {
        "asc": "Ascendant",
        "mc": "Midheaven",
        "desc": "Descendant",
        "ic": "Imum Coeli",
        "t_square": "T-Square",
        "grand_trine": "Grand Trine",
    }
    return special.get(identifier, identifier.replace("_", " ").title())


def _format_number(value: Any, places: int) -> str:
    try:
        return f"{float(value):.{places}f}"
    except (TypeError, ValueError):
        return "unknown"


def _format_point(point: Mapping[str, Any]) -> str:
    text = (
        f"{_display(str(point['id']))}: {_display(str(point['sign']))} "
        f"{_format_number(point['degree_in_sign'], 4)}°"
    )
    if point.get("house") is not None:
        text += f", house {point['house']}"
    if point.get("retro"):
        text += ", retrograde"
    if point.get("blend") and point.get("secondary_sign"):
        text += f", boundary blend with {_display(str(point['secondary_sign']))}"
    return text


def _relationship_sort_key(aspect: Any) -> tuple[Any, ...]:
    body_a = str(getattr(aspect, "body_a"))
    body_b = str(getattr(aspect, "body_b"))
    pair = frozenset((body_a, body_b))
    special_pairs = (
        frozenset(("sun", "moon")),
        frozenset(("sun", "asc")),
        frozenset(("moon", "asc")),
        frozenset(("sun", "mc")),
        frozenset(("moon", "mc")),
    )
    if pair in special_pairs:
        group = 0
        subgroup = special_pairs.index(pair)
    else:
        personal = {"sun", "moon", "mercury", "venus", "mars", "asc", "mc"}
        personal_count = int(body_a in personal) + int(body_b in personal)
        if personal_count == 2:
            group, subgroup = 1, 0
        elif personal_count == 1:
            group, subgroup = 2, 0
        else:
            group, subgroup = 3, 0
    aspect_id = str(getattr(aspect, "aspect_id"))
    aspect_rank = ASPECT_TYPES.index(aspect_id) if aspect_id in ASPECT_TYPES else len(ASPECT_TYPES)
    force = float(getattr(aspect, "force", 0.0))
    exactness = float(getattr(aspect, "exactness", 0.0))
    a, b = sorted((body_a, body_b))
    return group, subgroup, -force, exactness, a, b, aspect_rank


def _append_comparison(lines: list[str], comparison: Mapping[str, Any]) -> None:
    systems = comparison.get("systems", ())
    if not isinstance(systems, (list, tuple)) or not systems:
        raise ValueError("comparison systems must be a non-empty array")
    system_ids = tuple(str(system) for system in systems)
    note = str(comparison.get("note") or "")
    lines.extend(("", "## Comparison", ""))
    if note:
        lines.extend((note, ""))
    points = comparison.get("points", ())
    if not isinstance(points, (list, tuple)):
        raise ValueError("comparison points must be an array")
    for point in points:
        if not isinstance(point, Mapping):
            raise ValueError("each comparison point must be an object")
        labels = point.get("systems", {})
        if not isinstance(labels, Mapping):
            raise ValueError("comparison point systems must be an object")
        rendered: list[str] = []
        for system in system_ids:
            placement = labels.get(system)
            if not isinstance(placement, Mapping):
                raise ValueError(f"comparison point is missing system {system!r}")
            rendered.append(
                f"{_display(system)}: {_display(str(placement.get('sign', 'unknown')))} "
                f"{_format_number(placement.get('degree_in_sign'), 4)}°"
            )
        difference = " — labels differ" if point.get("labels_differ") else ""
        lines.append(
            f"- {_display(str(point.get('id', 'unknown')))}: "
            + " · ".join(rendered)
            + difference
        )

    cusps = comparison.get("cusps", ())
    if isinstance(cusps, (list, tuple)) and cusps:
        lines.extend(("", "### House cusp labels", ""))
        for cusp in cusps:
            if not isinstance(cusp, Mapping):
                raise ValueError("each comparison cusp must be an object")
            labels = cusp.get("systems", {})
            if not isinstance(labels, Mapping):
                raise ValueError("comparison cusp systems must be an object")
            rendered = []
            for system in system_ids:
                placement = labels.get(system)
                if not isinstance(placement, Mapping):
                    raise ValueError(f"comparison cusp is missing system {system!r}")
                rendered.append(
                    f"{_display(system)}: {_display(str(placement.get('sign', 'unknown')))} "
                    f"{_format_number(placement.get('degree_in_sign'), 4)}°"
                )
            difference = " — labels differ" if cusp.get("labels_differ") else ""
            lines.append(
                f"- House {cusp.get('number', 'unknown')}: "
                + " · ".join(rendered)
                + difference
            )


def _append_readings(lines: list[str], readings: Any) -> None:
    for reading in readings:
        status = str(reading.get("status", "missing"))
        title = str(reading.get("title") or reading.get("id"))
        if status == "missing":
            lines.extend((f"**{title}** — interpretation record missing.", ""))
            continue
        label = " _(stub)_" if status == "stub" else ""
        lines.extend((f"**{title}**{label}", "", str(reading.get("summary", "")), ""))
        for field, heading in (
            ("body", "Notes"),
            ("shadow", "Lower-expression notes"),
            ("growth", "Development notes"),
            ("blend_note", "Boundary note"),
        ):
            if reading.get(field):
                lines.extend((f"{heading}: {reading[field]}", ""))


__all__ = [
    "EPISTEMIC_NOTE",
    "InterpretationReport",
    "ReportGap",
    "compose_report",
]
