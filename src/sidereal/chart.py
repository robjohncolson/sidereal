"""Chart calculation orchestration; no interpretation prose belongs here."""

from __future__ import annotations

import math
from typing import Iterable

from .aspects import compute_aspects, detect_patterns
from .config import BODY_IDS, ChartConfig, POINT_NAMES
from .ephemeris import EphemerisProvider, RawHouseData, SwissEphemeris
from .houses import assign_house
from .timebase import julian_days, resolve_moment
from .types import Chart, ChartMeta, HouseCusp, MomentInput, PointPos
from .zodiac.base import ZodiacMap, normalize_longitude
from .zodiac.midpoint import MidpointZodiac


def compute(
    moment: MomentInput,
    config: ChartConfig | None = None,
    *,
    ephemeris: EphemerisProvider | None = None,
    zodiac: ZodiacMap | None = None,
) -> Chart:
    """Compute a reproducible geometry chart for ``moment``.

    Interpretation lookup/composition is intentionally a separate downstream
    step so astronomical facts and symbolic notes cannot be conflated.
    """

    active_config = config or ChartConfig()
    active_config.validate()
    resolved = resolve_moment(moment, assumed_local_time=active_config.assumed_local_time)
    jd_et, jd_ut = julian_days(resolved.utc_datetime)

    active_ephemeris = ephemeris or SwissEphemeris(
        ephe_path=active_config.ephe_path,
        require_swiss_ephemeris=active_config.require_swiss_ephemeris,
    )
    active_zodiac = zodiac or MidpointZodiac.load_default(active_config.boundary_path)
    if active_zodiac.id != active_config.zodiac:
        raise ValueError(
            f"Configured zodiac {active_config.zodiac!r} does not match mapper {active_zodiac.id!r}"
        )

    batch = active_ephemeris.calculate_positions(jd_ut)
    _validate_position_batch(batch)
    house_data: RawHouseData | None = None
    if (
        active_config.include_houses
        and resolved.time_known
        and resolved.location_known
    ):
        # Location validation in timebase guarantees both values are present.
        assert moment.lat is not None and moment.lon is not None
        house_data = active_ephemeris.calculate_houses(jd_ut, moment.lat, moment.lon)
        _validate_house_data(house_data)

    points = list(
        _body_points(
            batch.positions,
            active_zodiac,
            active_config.blend_orb_deg,
            house_data,
        )
    )
    if house_data is not None:
        points.extend(_angle_points(house_data, active_zodiac, active_config.blend_orb_deg))

    cusps = (
        _house_cusps(house_data, active_zodiac, active_config.blend_orb_deg)
        if house_data is not None
        else None
    )
    aspect_hits = compute_aspects(
        points,
        rules=active_config.aspect_rules,
        luminary_orb_bonus_deg=active_config.luminary_orb_bonus_deg,
        outer_pair_orb_penalty_deg=active_config.outer_pair_orb_penalty_deg,
    )
    patterns = detect_patterns(points, aspect_hits) if active_config.include_patterns else ()

    warnings = list(batch.warnings)
    if not resolved.time_known:
        warnings.append(
            "Civil time was not supplied: positions use the recorded local-noon assumption; "
            "angles, houses, and angle aspects are omitted."
        )
    elif not resolved.location_known:
        warnings.append("Location was not supplied: angles, houses, and angle aspects are omitted.")
    elif not active_config.include_houses:
        warnings.append("Houses, angles, and angle aspects were disabled by configuration.")

    meta = ChartMeta(
        input=moment,
        time_known=resolved.time_known,
        location_known=resolved.location_known,
        local_datetime=resolved.local_datetime,
        utc_datetime=resolved.utc_datetime,
        jd_ut=jd_ut,
        jd_et=jd_et,
        zodiac_system=active_config.zodiac,
        house_system=active_config.house_system if house_data is not None else None,
        aspect_profile=active_config.aspect_profile,
        swe_version=active_ephemeris.swe_version,
        pyswisseph_version=active_ephemeris.pyswisseph_version,
        boundary_version=active_zodiac.boundary_version,
        ephemeris_backend=batch.backend,
        calculation_time_assumption=resolved.calculation_time_assumption,
        warnings=tuple(dict.fromkeys(warnings)),
        blend_orb_deg=active_config.blend_orb_deg,
        aspect_rules=tuple(
            (rule.id, rule.angle_deg, rule.orb_deg)
            for rule in active_config.aspect_rules
        ),
        luminary_orb_bonus_deg=active_config.luminary_orb_bonus_deg,
        outer_pair_orb_penalty_deg=active_config.outer_pair_orb_penalty_deg,
        houses_enabled=active_config.include_houses,
        patterns_enabled=active_config.include_patterns,
        ephemeris_flags=tuple(
            dict.fromkeys(
                tuple(getattr(active_ephemeris, "position_flags", ()))
                + (
                    tuple(getattr(active_ephemeris, "house_frame_flags", ()))
                    if house_data is not None
                    else ()
                )
            )
        ),
        house_frame_method=(
            str(getattr(active_ephemeris, "house_frame_method", "")) or None
            if house_data is not None
            else None
        ),
        boundary_source_doi=str(getattr(active_zodiac, "source_doi", "")),
        boundary_license_id=str(getattr(active_zodiac, "license_id", "")),
        boundary_sha256=str(getattr(active_zodiac, "content_sha256", "")),
    )
    return Chart(
        meta=meta,
        points=tuple(points),
        cusps=cusps,
        aspects=aspect_hits,
        patterns=patterns,
    )


def _body_points(
    raw_positions: Iterable[object],
    zodiac: ZodiacMap,
    blend_orb_deg: float,
    house_data: RawHouseData | None,
) -> Iterable[PointPos]:
    for raw in raw_positions:
        # EphemerisProvider is intentionally small; these fields form its
        # structural RawPosition contract and make lightweight test doubles easy.
        body_id = str(getattr(raw, "id"))
        lon_date = float(getattr(raw, "lon_date"))
        lon_j2000 = float(getattr(raw, "lon_j2000"))
        speed_long = float(getattr(raw, "speed_long"))
        raw_speed_long_j2000 = getattr(raw, "speed_long_j2000", None)
        speed_long_j2000 = (
            speed_long
            if raw_speed_long_j2000 is None
            else float(raw_speed_long_j2000)
        )
        latitude = float(getattr(raw, "lat"))
        if not all(
            math.isfinite(value)
            for value in (
                lon_date,
                lon_j2000,
                latitude,
                speed_long,
                speed_long_j2000,
            )
        ):
            raise ValueError(f"Ephemeris returned non-finite geometry for {body_id!r}")
        placement = zodiac.map(lon_j2000, blend_orb_deg=blend_orb_deg)
        yield PointPos(
            id=body_id,
            name=POINT_NAMES.get(body_id, body_id.replace("_", " ").title()),
            kind="body",
            lon_date=normalize_longitude(lon_date),
            lon_j2000=normalize_longitude(lon_j2000),
            lat=latitude,
            speed_long=speed_long,
            retro=speed_long < 0.0,
            sign=placement.sign,
            degree_in_sign=placement.degree_in_sign,
            house=assign_house(lon_date, house_data.asc_date) if house_data is not None else None,
            blend=placement.blend,
            secondary_sign=placement.secondary_sign,
            speed_long_j2000=speed_long_j2000,
        )


def _validate_position_batch(batch: object) -> None:
    positions = tuple(getattr(batch, "positions", ()))
    ids = tuple(str(getattr(position, "id", "")) for position in positions)
    if ids != BODY_IDS:
        raise ValueError(
            "Ephemeris provider must return the complete v1 body inventory "
            f"in stable order; expected {BODY_IDS!r}, got {ids!r}"
        )
    backend = getattr(batch, "backend", None)
    if not isinstance(backend, str) or not backend.strip():
        raise ValueError("Ephemeris provider must identify a non-empty backend")


def _angle_points(
    houses: RawHouseData,
    zodiac: ZodiacMap,
    blend_orb_deg: float,
) -> list[PointPos]:
    values = (
        ("asc", houses.asc_date, houses.asc_j2000, houses.asc_speed_date),
        ("mc", houses.mc_date, houses.mc_j2000, houses.mc_speed_date),
        (
            "desc",
            normalize_longitude(houses.asc_date + 180.0),
            normalize_longitude(houses.asc_j2000 + 180.0),
            houses.asc_speed_date,
        ),
        (
            "ic",
            normalize_longitude(houses.mc_date + 180.0),
            normalize_longitude(houses.mc_j2000 + 180.0),
            houses.mc_speed_date,
        ),
    )
    result: list[PointPos] = []
    for point_id, lon_date, lon_j2000, speed in values:
        placement = zodiac.map(lon_j2000, blend_orb_deg=blend_orb_deg)
        result.append(
            PointPos(
                id=point_id,
                name=POINT_NAMES[point_id],
                kind="angle",
                lon_date=lon_date,
                lon_j2000=lon_j2000,
                lat=0.0,
                speed_long=speed,
                retro=speed < 0.0,
                sign=placement.sign,
                degree_in_sign=placement.degree_in_sign,
                house=assign_house(lon_date, houses.asc_date),
                blend=placement.blend,
                secondary_sign=placement.secondary_sign,
            )
        )
    return result


def _house_cusps(
    houses: RawHouseData,
    zodiac: ZodiacMap,
    blend_orb_deg: float,
) -> tuple[HouseCusp, ...]:
    result: list[HouseCusp] = []
    for number, (lon_date, lon_j2000) in enumerate(
        zip(houses.cusps_date, houses.cusps_j2000, strict=True),
        start=1,
    ):
        placement = zodiac.map(lon_j2000, blend_orb_deg=blend_orb_deg)
        result.append(
            HouseCusp(
                number=number,
                lon_date=lon_date,
                lon_j2000=lon_j2000,
                sign=placement.sign,
                degree_in_sign=placement.degree_in_sign,
                blend=placement.blend,
                secondary_sign=placement.secondary_sign,
            )
        )
    return tuple(result)


def _validate_house_data(houses: RawHouseData) -> None:
    if not (
        len(houses.cusps_date)
        == len(houses.cusps_j2000)
        == len(houses.cusp_speeds_date)
        == 12
    ):
        raise ValueError("Ephemeris provider must return exactly twelve house cusps")
    values = (
        *houses.cusps_date,
        *houses.cusps_j2000,
        *houses.cusp_speeds_date,
        houses.asc_date,
        houses.asc_j2000,
        houses.asc_speed_date,
        houses.mc_date,
        houses.mc_j2000,
        houses.mc_speed_date,
    )
    if not all(math.isfinite(float(value)) for value in values):
        raise ValueError("Ephemeris returned non-finite house or angle geometry")


compute_chart = compute

__all__ = ["compute", "compute_chart"]
