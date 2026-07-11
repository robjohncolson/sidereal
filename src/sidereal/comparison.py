"""Side-by-side zodiac labels derived from one primary geometry chart."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .zodiac.tropical import TropicalZodiac


MIDPOINT_SYSTEM_ID = "midpoint_v1"
TROPICAL_SYSTEM_ID = "tropical"
COMPARISON_NOTE = (
    "Midpoint and tropical zodiac labels use different reference frames; "
    "this comparison does not decide that either frame is the one true system."
)

_SYSTEM_ALIASES = {
    "midpoint": MIDPOINT_SYSTEM_ID,
    MIDPOINT_SYSTEM_ID: MIDPOINT_SYSTEM_ID,
    TROPICAL_SYSTEM_ID: TROPICAL_SYSTEM_ID,
}


def parse_comparison_systems(value: str | Iterable[str]) -> tuple[str, ...]:
    """Normalize the supported comparison spellings into stable system ids."""

    raw_items = value.split(",") if isinstance(value, str) else list(value)
    if not raw_items:
        raise ValueError("comparison systems cannot be empty")
    systems: list[str] = []
    for raw_item in raw_items:
        item = str(raw_item).strip().lower()
        if not item:
            raise ValueError("comparison systems cannot contain an empty value")
        try:
            system = _SYSTEM_ALIASES[item]
        except KeyError as exc:
            choices = ", ".join(sorted(_SYSTEM_ALIASES))
            raise ValueError(
                f"unsupported comparison system {item!r}; choose from {choices}"
            ) from exc
        if system not in systems:
            systems.append(system)
    if TROPICAL_SYSTEM_ID not in systems:
        raise ValueError("comparison must include tropical")
    if MIDPOINT_SYSTEM_ID in systems:
        systems.remove(MIDPOINT_SYSTEM_ID)
    systems.insert(0, MIDPOINT_SYSTEM_ID)
    return tuple(systems)


def build_comparison(chart: object, systems: str | Iterable[str]) -> dict[str, Any]:
    """Build label-only comparison data without recomputing chart geometry."""

    normalized = parse_comparison_systems(systems)
    tropical = TropicalZodiac()
    blend_orb = float(getattr(getattr(chart, "meta"), "blend_orb_deg", 3.0))

    points = [
        _comparison_point(point, normalized, tropical, blend_orb)
        for point in getattr(chart, "points")
    ]
    cusps = [
        _comparison_cusp(cusp, normalized, tropical, blend_orb)
        for cusp in (getattr(chart, "cusps", None) or ())
    ]
    return {
        "systems": list(normalized),
        "points": points,
        "cusps": cusps,
        "note": COMPARISON_NOTE,
    }


def _comparison_point(
    point: object,
    systems: tuple[str, ...],
    tropical: TropicalZodiac,
    blend_orb: float,
) -> dict[str, Any]:
    labels = _system_labels(point, systems, tropical, blend_orb)
    return {
        "id": str(getattr(point, "id")),
        "systems": labels,
        "labels_differ": _labels_differ(labels),
    }


def _comparison_cusp(
    cusp: object,
    systems: tuple[str, ...],
    tropical: TropicalZodiac,
    blend_orb: float,
) -> dict[str, Any]:
    labels = _system_labels(cusp, systems, tropical, blend_orb)
    return {
        "number": int(getattr(cusp, "number")),
        "systems": labels,
        "labels_differ": _labels_differ(labels),
    }


def _system_labels(
    item: object,
    systems: tuple[str, ...],
    tropical: TropicalZodiac,
    blend_orb: float,
) -> dict[str, dict[str, Any]]:
    labels: dict[str, dict[str, Any]] = {}
    for system in systems:
        if system == MIDPOINT_SYSTEM_ID:
            labels[system] = {
                "sign": str(getattr(item, "sign")),
                "degree_in_sign": float(getattr(item, "degree_in_sign")),
            }
        elif system == TROPICAL_SYSTEM_ID:
            placement = tropical.map(
                float(getattr(item, "lon_date")),
                blend_orb_deg=blend_orb,
            )
            labels[system] = {
                "sign": placement.sign,
                "degree_in_sign": placement.degree_in_sign,
            }
        else:  # pragma: no cover - parser is the supported-system boundary
            raise ValueError(f"unsupported comparison system: {system!r}")
    return labels


def _labels_differ(labels: Mapping[str, Mapping[str, Any]]) -> bool:
    return len({str(value["sign"]) for value in labels.values()}) > 1


__all__ = [
    "COMPARISON_NOTE",
    "MIDPOINT_SYSTEM_ID",
    "TROPICAL_SYSTEM_ID",
    "build_comparison",
    "parse_comparison_systems",
]
