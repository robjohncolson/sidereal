"""Join two-natal cross-chart geometry to symbolic interpretation records."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from typing import Any, Protocol

from ..config import ChartConfig
from ..synastry import SynastryAspectHit, SynastryGeometry, compute_synastry_geometry
from ..types import Chart
from .compose import ReportGap, _sign_colored_aspect_synthesis
from .schema import ANGLES, PLANETS, InterpretationEntry, aspect_key


SYNASTRY_EPISTEMIC_NOTE = (
    "Two-natal synastry compares geometric relationships between two fixed chart "
    "moments. Interpretations are symbolic relationship study notes, not "
    "compatibility scores, destiny claims, or predictions about people or outcomes."
)


class EntryLookup(Protocol):
    def get(self, entry_id: str) -> InterpretationEntry | None:
        ...


@dataclass(frozen=True, slots=True)
class SynastryReport:
    chart_a: Mapping[str, Any]
    chart_b: Mapping[str, Any]
    relationships: tuple[Mapping[str, Any], ...]
    gaps: tuple[ReportGap, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_version": 1,
            "report_type": "synastry",
            "epistemic_note": SYNASTRY_EPISTEMIC_NOTE,
            "chart_a": dict(self.chart_a),
            "chart_b": dict(self.chart_b),
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
        label_a = str(self.chart_a.get("label") or "Chart A")
        label_b = str(self.chart_b.get("label") or "Chart B")
        lines = [
            f"# Two-natal synastry: {label_a} ↔ {label_b}",
            "",
            "Two fixed natal/event moments are compared in one common J2000 frame.",
            "",
            f"Chart A: {self.chart_a.get('local_datetime', 'unknown')} "
            f"({self.chart_a.get('tz', 'unknown timezone')})",
            f"Chart B: {self.chart_b.get('local_datetime', 'unknown')} "
            f"({self.chart_b.get('tz', 'unknown timezone')})",
            "",
            "## Epistemic note",
            "",
            SYNASTRY_EPISTEMIC_NOTE,
        ]
        if self.warnings:
            lines.extend(("", "## Calculation notes", ""))
            lines.extend(f"- {warning}" for warning in self.warnings)

        lines.extend(("", "## Two-natal aspects", ""))
        if not self.relationships:
            lines.append("No configured major cross-chart aspects were found.")
        else:
            groups = (
                (
                    "Same-body contacts",
                    tuple(item for item in self.relationships if item.get("same_body")),
                ),
                (
                    "Other cross-chart contacts",
                    tuple(item for item in self.relationships if not item.get("same_body")),
                ),
            )
            for group_title, group_items in groups:
                if not group_items:
                    continue
                lines.extend((f"### {group_title}", ""))
                for item in group_items:
                    aspect = item["aspect"]
                    reading = item["reading"]
                    character = (
                        item.get("character")
                        if isinstance(item.get("character"), Mapping)
                        else {}
                    )
                    title = str(
                        character.get("title")
                        or (
                            f"A · {_display(str(aspect['a_point']))} "
                            f"{str(aspect['aspect_id']).replace('_', ' ')} "
                            f"B · {_display(str(aspect['b_point']))}"
                        )
                    )
                    lines.extend(
                        (
                            f"#### {title}",
                            "",
                            f"Geometry: separation {float(aspect['separation']):.4f}°, "
                            f"orb {float(aspect['exactness']):.4f}°. Both charts are fixed, "
                            "so applying/separating is not assigned.",
                            "",
                        )
                    )
                    synthesis = str(character.get("synthesis") or "").strip()
                    if synthesis:
                        lines.extend((synthesis, ""))
                    _append_reading(lines, reading)
                    for side_key, side_label in (
                        ("a_placement", "Chart A · Midpoint sign character"),
                        ("b_placement", "Chart B · Midpoint sign character"),
                    ):
                        side = character.get(side_key)
                        if not isinstance(side, Mapping):
                            continue
                        side_reading = side.get("reading")
                        if isinstance(side_reading, Mapping):
                            lines.extend((f"##### {side_label}", ""))
                            _append_reading(lines, side_reading)

        lines.extend(("", "## Missing interpretation keys", ""))
        if self.gaps:
            lines.extend(
                f"- `{gap.key}` ({gap.kind}) — {'; '.join(gap.contexts)}"
                for gap in self.gaps
            )
        else:
            lines.append("None.")
        return "\n".join(lines).rstrip() + "\n"


def compose_synastry_report(
    geometry: SynastryGeometry,
    store: EntryLookup | None = None,
    *,
    source_a: str = "inline",
    id_a: str | None = None,
    source_b: str = "inline",
    id_b: str | None = None,
) -> SynastryReport:
    """Join one role-preserving cross-chart geometry result to the DB once."""

    resolver = _SynastryResolver(store)
    points_a = {point.id: point for point in geometry.chart_a.points}
    points_b = {point.id: point for point in geometry.chart_b.points}
    relationships: list[Mapping[str, Any]] = []
    for hit in sorted(
        geometry.aspects,
        key=lambda item: (
            -item.force,
            item.exactness,
            item.a_point,
            item.b_point,
            item.aspect_id,
        ),
    ):
        key = _synastry_interpretation_key(hit)
        context = f"chart A {hit.a_point} {hit.aspect_id} chart B {hit.b_point}"
        reading = (
            _angle_self_reading(hit, key, context)
            if hit.a_point == hit.b_point and hit.a_point in ANGLES
            else resolver.resolve(key, context)
        )
        relationships.append(
            {
                "aspect": hit.to_dict(),
                "same_body": hit.a_point == hit.b_point,
                "reading": reading,
                "character": _relationship_character(
                    resolver,
                    points_a=points_a,
                    points_b=points_b,
                    hit=hit,
                    context_prefix=context,
                ),
            }
        )

    warnings = tuple(
        dict.fromkeys(
            (
                *(f"Chart A: {warning}" for warning in geometry.chart_a.meta.warnings),
                *(f"Chart B: {warning}" for warning in geometry.chart_b.meta.warnings),
            )
        )
    )
    return SynastryReport(
        chart_a={**_chart_summary(geometry.chart_a), "source": source_a, "id": id_a},
        chart_b={**_chart_summary(geometry.chart_b), "source": source_b, "id": id_b},
        relationships=tuple(relationships),
        gaps=resolver.gaps(),
        warnings=warnings,
    )


def calculate_synastry_report(
    chart_a: Chart,
    chart_b: Chart,
    config: ChartConfig,
    store: EntryLookup | None = None,
    *,
    source_a: str = "inline",
    id_a: str | None = None,
    source_b: str = "inline",
    id_b: str | None = None,
) -> SynastryReport:
    geometry = compute_synastry_geometry(chart_a, chart_b, config)
    return compose_synastry_report(
        geometry,
        store,
        source_a=source_a,
        id_a=id_a,
        source_b=source_b,
        id_b=id_b,
    )


class _SynastryResolver:
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


def _synastry_interpretation_key(hit: SynastryAspectHit) -> str:
    try:
        return aspect_key(hit.a_point, hit.aspect_id, hit.b_point)
    except ValueError:
        body_a, body_b = sorted((hit.a_point, hit.b_point))
        return f"aspect:{body_a}:{hit.aspect_id}:{body_b}"


def _angle_self_reading(
    hit: SynastryAspectHit,
    key: str,
    context: str,
) -> dict[str, Any]:
    title = f"{_display(hit.a_point)} {hit.aspect_id.title()} {_display(hit.b_point)}"
    return {
        "id": key,
        "status": "not_applicable",
        "title": title,
        "keywords": [],
        "summary": (
            "This cross-chart angle-to-same-angle contact is shown as geometry only. "
            "The shared interpretation inventory deliberately has no angle self-key."
        ),
        "context": context,
    }


def _relationship_character(
    resolver: _SynastryResolver,
    *,
    points_a: Mapping[str, Any],
    points_b: Mapping[str, Any],
    hit: SynastryAspectHit,
    context_prefix: str,
) -> dict[str, Any]:
    point_a = points_a.get(hit.a_point)
    point_b = points_b.get(hit.b_point)
    sign_a = getattr(point_a, "sign", None) if point_a is not None else None
    sign_b = getattr(point_b, "sign", None) if point_b is not None else None
    reading_a = _placement_reading(
        resolver,
        body=hit.a_point,
        sign=sign_a,
        context=f"{context_prefix} · chart A sign character",
    )
    reading_b = _placement_reading(
        resolver,
        body=hit.b_point,
        sign=sign_b,
        context=f"{context_prefix} · chart B sign character",
    )
    title_a = f"A · {_display(hit.a_point)}"
    if sign_a:
        title_a += f" in {_display(str(sign_a))}"
    title_b = f"B · {_display(hit.b_point)}"
    if sign_b:
        title_b += f" in {_display(str(sign_b))}"
    return {
        "title": f"{title_a} {hit.aspect_id.replace('_', ' ')} {title_b}",
        "synthesis": _sign_colored_aspect_synthesis(
            body_a=hit.a_point,
            sign_a=str(sign_a) if sign_a else None,
            body_b=hit.b_point,
            sign_b=str(sign_b) if sign_b else None,
            aspect_id=hit.aspect_id,
        ),
        "a_placement": {
            "body": hit.a_point,
            "sign": sign_a,
            "house": getattr(point_a, "house", None) if point_a is not None else None,
            "reading": reading_a,
        },
        "b_placement": {
            "body": hit.b_point,
            "sign": sign_b,
            "house": getattr(point_b, "house", None) if point_b is not None else None,
            "reading": reading_b,
        },
    }


def _placement_reading(
    resolver: _SynastryResolver,
    *,
    body: str,
    sign: Any,
    context: str,
) -> dict[str, Any] | None:
    if not sign:
        return None
    if body in PLANETS:
        return resolver.resolve(f"planet_in_sign:{body}:{sign}", context)
    if body in ANGLES:
        return resolver.resolve(f"angle_in_sign:{body}:{sign}", context)
    return None


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


def _display(identifier: str) -> str:
    special = {"asc": "Ascendant", "mc": "Midheaven"}
    return special.get(identifier, identifier.replace("_", " ").title())


__all__ = [
    "SYNASTRY_EPISTEMIC_NOTE",
    "SynastryReport",
    "calculate_synastry_report",
    "compose_synastry_report",
]
