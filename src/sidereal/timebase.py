"""Civil-time resolution and Swiss Ephemeris Julian-day conversion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta, timezone, tzinfo
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .types import MomentInput


_OFFSET_RE = re.compile(r"^(?:UTC)?(?P<sign>[+-])(?P<hour>\d{2}):?(?P<minute>\d{2})$", re.I)


@dataclass(frozen=True, slots=True)
class ResolvedMoment:
    """A civil input resolved to one unambiguous UTC instant."""

    local_datetime: datetime
    utc_datetime: datetime
    time_known: bool
    location_known: bool
    calculation_time_assumption: str | None


def resolve_moment(
    moment: MomentInput,
    *,
    assumed_local_time: time = time(12, 0),
) -> ResolvedMoment:
    """Resolve a local civil moment, rejecting DST gaps and ambiguity.

    When the user did not supply a time, local noon is used only as the
    representative instant for body positions.  ``time_known`` remains false,
    which prevents the chart layer from calculating angles or houses.
    """

    _validate_location(moment.lat, moment.lon)
    if not moment.tz or not moment.tz.strip():
        raise ValueError("tz must be a non-empty IANA zone or UTC offset")
    if moment.local_time is not None and moment.local_time.tzinfo is not None:
        raise ValueError("local_time must not contain tzinfo; use the tz field")
    if assumed_local_time.tzinfo is not None:
        raise ValueError("assumed_local_time must be naive")
    if moment.fold not in (None, 0, 1):
        raise ValueError("fold must be 0, 1, or None")
    if moment.fold is not None and moment.local_time is None:
        raise ValueError("fold is only valid when a local_time is supplied")

    time_known = moment.local_time is not None
    selected_time = moment.local_time if time_known else assumed_local_time
    naive = datetime.combine(moment.local_date, selected_time)
    zone = parse_timezone(moment.tz)
    aware = _localize_strict(naive, zone, moment.fold)
    assumption = None
    if not time_known:
        assumption = f"{selected_time.isoformat(timespec='minutes')} local (time not supplied)"
    return ResolvedMoment(
        local_datetime=aware,
        utc_datetime=aware.astimezone(UTC),
        time_known=time_known,
        location_known=moment.lat is not None and moment.lon is not None,
        calculation_time_assumption=assumption,
    )


def parse_timezone(value: str) -> tzinfo:
    """Parse an IANA identifier, ``UTC``/``Z``, or numeric UTC offset."""

    text = value.strip()
    if text.upper() in {"UTC", "Z"}:
        return UTC
    match = _OFFSET_RE.fullmatch(text)
    if match:
        hours = int(match.group("hour"))
        minutes = int(match.group("minute"))
        if minutes >= 60 or hours > 14 or (hours == 14 and minutes != 0):
            raise ValueError(f"UTC offset out of supported range: {value!r}")
        delta = timedelta(hours=hours, minutes=minutes)
        if match.group("sign") == "-":
            delta = -delta
        return timezone(delta, name=text)
    try:
        return ZoneInfo(text)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone: {value!r}") from exc


def julian_days(utc_datetime: datetime, swe_module: Any | None = None) -> tuple[float, float]:
    """Return ``(jd_et, jd_ut)`` for an aware UTC instant.

    ``swisseph.utc_to_jd`` returns ET first and UT1 second; retaining that order
    here avoids a subtle but consequential binding pitfall.
    """

    if utc_datetime.tzinfo is None:
        raise ValueError("utc_datetime must be timezone-aware")
    instant = utc_datetime.astimezone(UTC)
    if swe_module is None:
        try:
            import swisseph as swe_module  # type: ignore[no-redef]
        except ImportError as exc:  # pragma: no cover - packaging failure path
            raise RuntimeError(
                "pyswisseph is required for Julian-day conversion; install project dependencies"
            ) from exc
    seconds = instant.second + instant.microsecond / 1_000_000.0
    jd_et, jd_ut = swe_module.utc_to_jd(
        instant.year,
        instant.month,
        instant.day,
        instant.hour,
        instant.minute,
        seconds,
        swe_module.GREG_CAL,
    )
    return float(jd_et), float(jd_ut)


def _validate_location(lat: float | None, lon: float | None) -> None:
    if (lat is None) != (lon is None):
        raise ValueError("lat and lon must be supplied together")
    if lat is None:
        return
    if not -90.0 < lat < 90.0:
        raise ValueError("lat must be strictly between -90 and 90 degrees")
    if lon is None or not -180.0 <= lon <= 180.0:
        raise ValueError("lon must be between -180 and 180 degrees")


def _localize_strict(naive: datetime, zone: tzinfo, fold: int | None) -> datetime:
    if not isinstance(zone, ZoneInfo):
        if fold is not None:
            raise ValueError("fold is only valid for an ambiguous IANA timezone time")
        return naive.replace(tzinfo=zone)

    candidates: dict[tuple[timedelta | None, datetime], datetime] = {}
    for candidate_fold in (0, 1):
        aware = naive.replace(tzinfo=zone, fold=candidate_fold)
        roundtrip = aware.astimezone(UTC).astimezone(zone)
        if roundtrip.replace(tzinfo=None) == naive and roundtrip.fold == candidate_fold:
            candidates[(aware.utcoffset(), aware.astimezone(UTC))] = aware

    values = tuple(candidates.values())
    if not values:
        raise ValueError(f"Nonexistent local time in {zone.key}: {naive.isoformat()}")
    if fold is not None:
        if len(values) == 1:
            raise ValueError(
                f"fold is not valid for the unambiguous local time {naive.isoformat()} in {zone.key}"
            )
        for aware in values:
            if aware.fold == fold:
                return aware
        raise ValueError(f"fold={fold} is not valid for {naive.isoformat()} in {zone.key}")
    if len(values) > 1:
        raise ValueError(
            f"Ambiguous local time in {zone.key}: {naive.isoformat()}; set MomentInput.fold to 0 or 1"
        )
    return values[0]


__all__ = ["ResolvedMoment", "julian_days", "parse_timezone", "resolve_moment"]
