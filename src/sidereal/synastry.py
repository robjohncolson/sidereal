"""Pure two-natal synastry geometry over the existing aspect engine.

Synastry compares two fixed chart moments.  Point roles therefore remain
explicit as chart A and chart B, while applying/separating is intentionally
undefined.  All angular comparisons use the common J2000 ecliptic longitudes
already stored on :class:`~sidereal.types.PointPos`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .aspects import TRANSIT_ASPECT_BODY_IDS, compute_transit_aspects
from .config import ASPECT_POINT_IDS, ChartConfig
from .types import Chart


@dataclass(frozen=True, slots=True)
class SynastryAspectHit:
    """A major aspect from a point in chart A to a point in chart B."""

    a_point: str
    b_point: str
    aspect_id: str
    separation: float
    orb_used: float
    exactness: float
    force: float
    applying: None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe, role-preserving representation."""

        return {
            "a_point": self.a_point,
            "b_point": self.b_point,
            "aspect_id": self.aspect_id,
            "separation": self.separation,
            "orb_used": self.orb_used,
            "exactness": self.exactness,
            "force": self.force,
            "applying": self.applying,
        }


@dataclass(frozen=True, slots=True)
class SynastryGeometry:
    """Two source charts and their role-preserving cross-chart aspects."""

    chart_a: Chart
    chart_b: Chart
    aspects: tuple[SynastryAspectHit, ...]


def compute_synastry_geometry(
    chart_a: Chart,
    chart_b: Chart,
    config: ChartConfig,
) -> SynastryGeometry:
    """Compute major A-to-B aspects in the charts' common J2000 frame.

    The shared cross-chart matcher supplies the configured major rules and orb
    modifiers.  It is invoked with both sides' eligible natal points, including
    Ascendant and Midheaven only when that chart has known time and location.
    Descendant, IC, and South Node retain their existing display-only status so
    they do not duplicate opposition geometry or interpretation keys.
    """

    config.validate()
    _validate_common_frame(chart_a, chart_b, config)

    cross_hits = compute_transit_aspects(
        chart_a.points,
        chart_b.points,
        rules=config.aspect_rules,
        luminary_orb_bonus_deg=config.luminary_orb_bonus_deg,
        outer_pair_orb_penalty_deg=config.outer_pair_orb_penalty_deg,
        transit_ids=_eligible_ids(chart_a),
        natal_ids=_eligible_ids(chart_b),
    )
    aspects = tuple(
        SynastryAspectHit(
            a_point=hit.transit_body,
            b_point=hit.natal_point,
            aspect_id=hit.aspect_id,
            separation=hit.separation,
            orb_used=hit.orb_used,
            exactness=hit.exactness,
            force=hit.force,
        )
        for hit in cross_hits
    )
    return SynastryGeometry(chart_a=chart_a, chart_b=chart_b, aspects=aspects)


def _eligible_ids(chart: Chart) -> frozenset[str]:
    if chart.meta.time_known and chart.meta.location_known:
        return ASPECT_POINT_IDS
    return TRANSIT_ASPECT_BODY_IDS


def _validate_common_frame(
    chart_a: Chart,
    chart_b: Chart,
    config: ChartConfig,
) -> None:
    if chart_a.meta.zodiac_system != chart_b.meta.zodiac_system:
        raise ValueError("Synastry charts must use the same zodiac system")
    if chart_a.meta.zodiac_system != config.zodiac:
        raise ValueError("Synastry charts do not match the configured zodiac system")
    if chart_a.meta.boundary_version != chart_b.meta.boundary_version:
        raise ValueError("Synastry charts use different boundary versions")
    if (
        chart_a.meta.boundary_sha256
        and chart_b.meta.boundary_sha256
        and chart_a.meta.boundary_sha256 != chart_b.meta.boundary_sha256
    ):
        raise ValueError("Synastry charts use different boundary data")
    configured_rules = tuple(
        (rule.id, rule.angle_deg, rule.orb_deg) for rule in config.aspect_rules
    )
    for role, chart in (("A", chart_a), ("B", chart_b)):
        if chart.meta.aspect_profile != config.aspect_profile:
            raise ValueError(
                f"Synastry chart {role} aspect profile does not match the supplied config"
            )
        if chart.meta.aspect_rules and chart.meta.aspect_rules != configured_rules:
            raise ValueError(
                f"Synastry chart {role} aspect rules do not match the supplied config"
            )
        if (
            chart.meta.luminary_orb_bonus_deg != config.luminary_orb_bonus_deg
            or chart.meta.outer_pair_orb_penalty_deg
            != config.outer_pair_orb_penalty_deg
        ):
            raise ValueError(
                f"Synastry chart {role} orb modifiers do not match the supplied config"
            )


__all__ = [
    "SynastryAspectHit",
    "SynastryGeometry",
    "compute_synastry_geometry",
]
