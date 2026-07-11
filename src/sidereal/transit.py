"""Pure transit-to-natal geometry over the existing chart and aspect engines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .aspects import TRANSIT_ASPECT_BODY_IDS, compute_transit_aspects
from .config import ASPECT_POINT_IDS, ChartConfig
from .houses import assign_house
from .types import Chart, TransitAspectHit


@dataclass(frozen=True, slots=True)
class TransitPlacement:
    id: str
    name: str
    sign: str
    degree_in_sign: float
    lon_date: float
    lon_j2000: float
    retro: bool
    blend: bool
    secondary_sign: str | None
    natal_house: int | None
    time_sensitive: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "sign": self.sign,
            "degree_in_sign": self.degree_in_sign,
            "lon_date": self.lon_date,
            "lon_j2000": self.lon_j2000,
            "retro": self.retro,
            "blend": self.blend,
            "secondary_sign": self.secondary_sign,
            "natal_house": self.natal_house,
            "time_sensitive": self.time_sensitive,
        }


@dataclass(frozen=True, slots=True)
class TransitGeometry:
    natal: Chart
    transit: Chart
    placements: tuple[TransitPlacement, ...]
    aspects: tuple[TransitAspectHit, ...]


def compute_transit_geometry(
    natal: Chart,
    transit: Chart,
    config: ChartConfig,
) -> TransitGeometry:
    """Compute role-preserving transit aspects and natal-house overlays."""

    config.validate()
    if not transit.meta.time_known:
        raise ValueError("Transit calculation requires a known civil time")
    if natal.meta.zodiac_system != transit.meta.zodiac_system:
        raise ValueError("Natal and transit charts must use the same zodiac system")
    if natal.meta.boundary_version != transit.meta.boundary_version:
        raise ValueError("Natal and transit charts use different boundary versions")
    if (
        natal.meta.boundary_sha256
        and transit.meta.boundary_sha256
        and natal.meta.boundary_sha256 != transit.meta.boundary_sha256
    ):
        raise ValueError("Natal and transit charts use different boundary data")
    configured_rules = tuple(
        (rule.id, rule.angle_deg, rule.orb_deg) for rule in config.aspect_rules
    )
    if transit.meta.aspect_rules != configured_rules:
        raise ValueError("Transit chart aspect rules do not match the supplied config")
    if (
        transit.meta.luminary_orb_bonus_deg != config.luminary_orb_bonus_deg
        or transit.meta.outer_pair_orb_penalty_deg
        != config.outer_pair_orb_penalty_deg
    ):
        raise ValueError("Transit chart orb modifiers do not match the supplied config")

    natal_geometry_known = bool(
        natal.meta.time_known and natal.meta.location_known and natal.cusps
    )
    natal_asc = (
        next((point for point in natal.points if point.id == "asc"), None)
        if natal_geometry_known
        else None
    )
    if natal_geometry_known and natal_asc is None:
        raise ValueError("Known-time natal chart is missing its Ascendant")

    placements = tuple(
        TransitPlacement(
            id=point.id,
            name=point.name,
            sign=point.sign,
            degree_in_sign=point.degree_in_sign,
            lon_date=point.lon_date,
            lon_j2000=point.lon_j2000,
            retro=point.retro,
            blend=point.blend,
            secondary_sign=point.secondary_sign,
            natal_house=(
                assign_house(point.lon_j2000, natal_asc.lon_j2000)
                if natal_asc is not None
                else None
            ),
            time_sensitive=point.id == "moon",
        )
        for point in transit.points
        if point.kind == "body"
    )
    natal_ids = ASPECT_POINT_IDS if natal_geometry_known else TRANSIT_ASPECT_BODY_IDS
    aspects = compute_transit_aspects(
        transit.points,
        natal.points,
        rules=config.aspect_rules,
        luminary_orb_bonus_deg=config.luminary_orb_bonus_deg,
        outer_pair_orb_penalty_deg=config.outer_pair_orb_penalty_deg,
        natal_ids=natal_ids,
    )
    return TransitGeometry(
        natal=natal,
        transit=transit,
        placements=placements,
        aspects=aspects,
    )


__all__ = ["TransitGeometry", "TransitPlacement", "compute_transit_geometry"]
