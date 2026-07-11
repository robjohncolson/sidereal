"""Major aspect and structural-pattern detection."""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
import math
from typing import Iterable

from .config import (
    ASPECT_POINT_IDS,
    LUMINARY_IDS,
    MAJOR_ASPECT_RULES,
    OUTER_PLANET_IDS,
    PERSONAL_POINT_IDS,
    AspectRule,
)
from .types import AspectHit, PatternHit, PointPos


_MOTION_EPSILON = 1e-12
_EXACT_EPSILON = 1e-10


def signed_arc(angle_deg: float) -> float:
    """Normalize an angle to the half-open interval [-180, 180)."""

    value = (angle_deg + 180.0) % 360.0 - 180.0
    return 0.0 if value == 0.0 else value


def shortest_arc(longitude_a_deg: float, longitude_b_deg: float) -> float:
    """Absolute circular separation in [0, 180]."""

    if not math.isfinite(longitude_a_deg) or not math.isfinite(longitude_b_deg):
        raise ValueError("Aspect longitudes must be finite")
    return abs(signed_arc(longitude_b_deg - longitude_a_deg))


def compute_aspects(
    points: Iterable[PointPos],
    *,
    rules: tuple[AspectRule, ...] = MAJOR_ASPECT_RULES,
    luminary_orb_bonus_deg: float = 1.0,
    outer_pair_orb_penalty_deg: float = 2.0,
    allowed_ids: frozenset[str] = ASPECT_POINT_IDS,
) -> tuple[AspectHit, ...]:
    """Return stable, canonical major-aspect hits for eligible points."""

    eligible: dict[str, PointPos] = {}
    for point in points:
        if point.id not in allowed_ids:
            continue
        if point.id in eligible:
            raise ValueError(f"Duplicate aspect point id: {point.id!r}")
        eligible[point.id] = point

    hits: list[AspectHit] = []
    for body_a, body_b in combinations(sorted(eligible), 2):
        point_a = eligible[body_a]
        point_b = eligible[body_b]
        separation = shortest_arc(point_a.lon_date, point_b.lon_date)
        phase = signed_arc(point_b.lon_date - point_a.lon_date)
        relative_speed = point_b.speed_long - point_a.speed_long
        candidates: list[tuple[float, int, AspectRule, float]] = []
        for rule_index, rule in enumerate(rules):
            orb = _resolved_orb(
                body_a,
                body_b,
                rule.orb_deg,
                luminary_orb_bonus_deg=luminary_orb_bonus_deg,
                outer_pair_orb_penalty_deg=outer_pair_orb_penalty_deg,
            )
            exactness = abs(separation - rule.angle_deg)
            if exactness <= orb:
                candidates.append((exactness, rule_index, rule, orb))
        if candidates:
            # Custom profiles can create overlapping windows. The closest
            # exact geometry wins; declaration order is only a stable tie-break.
            exactness, _, rule, orb = min(candidates, key=lambda item: item[:2])
            error = _oriented_error(phase, rule.angle_deg)
            applying: bool | None
            if abs(error) <= _EXACT_EPSILON or abs(relative_speed) <= _MOTION_EPSILON:
                applying = None
            else:
                # d(error)/dt is the relative longitudinal speed.  The aspect
                # applies exactly when |error| is decreasing.
                applying = error * relative_speed < 0.0
            hits.append(
                AspectHit(
                    body_a=body_a,
                    body_b=body_b,
                    aspect_id=rule.id,
                    separation=separation,
                    orb_used=orb,
                    exactness=exactness,
                    force=max(0.0, min(1.0, 1.0 - exactness / orb)),
                    applying=applying,
                )
            )
    return tuple(hits)


def detect_patterns(
    points: Iterable[PointPos],
    aspects: Iterable[AspectHit],
) -> tuple[PatternHit, ...]:
    """Detect v1 stelliums, T-squares and grand trines without duplicates."""

    eligible = {
        point.id: point
        for point in points
        if point.id in ASPECT_POINT_IDS
    }
    patterns: list[PatternHit] = []

    by_sign: dict[str, list[str]] = defaultdict(list)
    for point in eligible.values():
        by_sign[point.sign].append(point.id)
    for sign, members in sorted(by_sign.items()):
        canonical = tuple(sorted(members))
        if len(canonical) >= 3 and any(member in PERSONAL_POINT_IDS for member in canonical):
            patterns.append(PatternHit("stellium", canonical, sign=sign))

    aspect_lookup = {
        (hit.body_a, hit.body_b): hit.aspect_id
        for hit in aspects
        if hit.body_a in eligible and hit.body_b in eligible
    }
    for members in combinations(sorted(eligible), 3):
        edges = {
            pair: aspect_lookup.get(pair)
            for pair in combinations(members, 2)
        }
        if all(aspect_id == "trine" for aspect_id in edges.values()):
            patterns.append(PatternHit("grand_trine", members))

        opposition_pairs = [pair for pair, aspect_id in edges.items() if aspect_id == "opposition"]
        if len(opposition_pairs) == 1:
            opposition = opposition_pairs[0]
            apex = next(member for member in members if member not in opposition)
            legs = tuple(tuple(sorted((apex, endpoint))) for endpoint in opposition)
            if all(aspect_lookup.get(leg) == "square" for leg in legs):
                patterns.append(PatternHit("t_square", members, apex=apex))

    priority = {"stellium": 0, "t_square": 1, "grand_trine": 2}
    return tuple(
        sorted(
            patterns,
            key=lambda item: (
                priority.get(item.pattern_id, 99),
                item.sign or "",
                item.members,
                item.apex or "",
            ),
        )
    )


def _resolved_orb(
    body_a: str,
    body_b: str,
    base_orb_deg: float,
    *,
    luminary_orb_bonus_deg: float,
    outer_pair_orb_penalty_deg: float,
) -> float:
    orb = base_orb_deg
    if body_a in LUMINARY_IDS or body_b in LUMINARY_IDS:
        orb += luminary_orb_bonus_deg
    if body_a in OUTER_PLANET_IDS and body_b in OUTER_PLANET_IDS:
        orb -= outer_pair_orb_penalty_deg
    if orb <= 0.0:
        raise ValueError(f"Resolved aspect orb must be positive for {body_a}/{body_b}")
    return orb


def _oriented_error(phase_deg: float, aspect_angle_deg: float) -> float:
    if aspect_angle_deg == 0.0:
        return signed_arc(phase_deg)
    if aspect_angle_deg == 180.0:
        return signed_arc(phase_deg - 180.0)
    positive = signed_arc(phase_deg - aspect_angle_deg)
    negative = signed_arc(phase_deg + aspect_angle_deg)
    return positive if abs(positive) <= abs(negative) else negative


__all__ = ["compute_aspects", "detect_patterns", "shortest_arc", "signed_arc"]
