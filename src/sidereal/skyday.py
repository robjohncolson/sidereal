"""Public, natal-free daily sky geometry for Moon Chorus."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date as Date, datetime, time, tzinfo
from pathlib import Path
import re
from threading import RLock
from typing import Any
from zoneinfo import ZoneInfo

from .chart import compute
from .config import ChartConfig
from .ephemeris import EphemerisError
from .skypack import SKYPACK_PROJECTION, build_body_entries, build_sign_band
from .timebase import parse_timezone, resolve_moment
from .types import MomentInput
from .zodiac.midpoint import MidpointZodiac


SKYDAY_SCHEMA_VERSION = 1
SKYDAY_TYPE = "skyday"
SKYDAY_SYSTEM = "midpoint_v1"
SKYDAY_PRIVACY = "public"
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True, slots=True)
class SkyDayRequest:
    """One validated civil-day request and its calculation instant."""

    timezone: str
    cache_date: Date
    epoch_utc: datetime

    @property
    def cache_key(self) -> str:
        return f"{self.timezone}:{self.cache_date.isoformat()}"


class SkyDayCalculationError(RuntimeError):
    """A validated request whose geometry could not be calculated."""


SkyDayBuilder = Callable[..., dict[str, Any]]


class SkyDayCache:
    """Thread-safe, process-local cache keyed by timezone and civil date."""

    def __init__(self, builder: SkyDayBuilder | None = None) -> None:
        self._builder = build_skyday if builder is None else builder
        self._entries: dict[str, dict[str, Any]] = {}
        self._lock = RLock()

    def get(
        self,
        *,
        tz: str = "UTC",
        date: Date | str | None = None,
        when: datetime | str | None = None,
        boundary_path: Path | str | None = None,
        ephe_path: Path | str | None = None,
        require_swiss_ephemeris: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Return one stable payload, calculating the first cache miss only."""

        request = resolve_skyday_request(tz=tz, date=date, when=when, now=now)
        with self._lock:
            cached = self._entries.get(request.cache_key)
            if cached is not None:
                return deepcopy(cached)
            try:
                payload = self._builder(
                    tz=request.timezone,
                    date=request.cache_date,
                    when=request.epoch_utc,
                    boundary_path=boundary_path,
                    ephe_path=ephe_path,
                    require_swiss_ephemeris=require_swiss_ephemeris,
                )
            except (EphemerisError, OSError, RuntimeError, ValueError) as exc:
                raise SkyDayCalculationError(str(exc)) from exc
            self._entries[request.cache_key] = deepcopy(payload)
            return deepcopy(payload)

    def clear(self) -> None:
        """Drop this process-local cache, primarily for tests and operations."""

        with self._lock:
            self._entries.clear()


def build_skyday(
    *,
    tz: str = "UTC",
    date: Date | str | None = None,
    when: datetime | str | None = None,
    boundary_path: Path | str | None = None,
    ephe_path: Path | str | None = None,
    require_swiss_ephemeris: bool = False,
    generated_at: datetime | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build public Midpoint geometry without loading or accepting natal data.

    The default calculation instant is local noon on ``date`` in ``tz``.
    ``when`` may instead select a naive local or offset-aware ISO instant; the
    payload is still cached under the independently selected civil date.
    """

    request = resolve_skyday_request(tz=tz, date=date, when=when, now=now)
    generated_utc = _aware_utc(
        generated_at or datetime.now(UTC).replace(microsecond=0),
        "generated_at",
    )
    config = ChartConfig(
        boundary_path=(
            Path(boundary_path).expanduser() if boundary_path is not None else None
        ),
        ephe_path=Path(ephe_path).expanduser() if ephe_path is not None else None,
        require_swiss_ephemeris=require_swiss_ephemeris,
        include_houses=False,
        include_patterns=False,
    )
    config.validate()
    zodiac = MidpointZodiac.load_default(config.boundary_path)
    moment = MomentInput(
        local_date=request.epoch_utc.date(),
        local_time=request.epoch_utc.timetz().replace(tzinfo=None),
        tz="UTC",
        label="Sky Day",
    )
    chart = compute(moment, config, zodiac=zodiac)
    return {
        "schema_version": SKYDAY_SCHEMA_VERSION,
        "type": SKYDAY_TYPE,
        "projection": SKYPACK_PROJECTION,
        "system": SKYDAY_SYSTEM,
        "privacy": SKYDAY_PRIVACY,
        "cache_date": request.cache_date.isoformat(),
        "timezone": request.timezone,
        "epoch_utc": request.epoch_utc.isoformat(),
        "generated_at": generated_utc.isoformat(),
        "sign_band": build_sign_band(zodiac),
        "movers": build_body_entries(chart, moving=True),
        "natal_ghosts": [],
        "resonances": [],
        "same_body_delta": [],
        "resonance_rank": [],
    }


def resolve_skyday_request(
    *,
    tz: str = "UTC",
    date: Date | str | None = None,
    when: datetime | str | None = None,
    now: datetime | None = None,
) -> SkyDayRequest:
    """Validate request fields and resolve the public calculation instant."""

    timezone_name, zone = _timezone(tz)
    current = _aware_utc(
        now or datetime.now(UTC),
        "now",
    )
    cache_date = (
        current.astimezone(zone).date()
        if date is None
        else parse_skyday_date(date)
    )
    if when is None:
        epoch_utc = resolve_moment(
            MomentInput(
                local_date=cache_date,
                local_time=time(12, 0),
                tz=timezone_name,
                label="Sky Day",
            )
        ).utc_datetime
    else:
        epoch_utc = _parse_when(when, timezone_name)
    return SkyDayRequest(
        timezone=timezone_name,
        cache_date=cache_date,
        epoch_utc=epoch_utc,
    )


def parse_skyday_date(value: Date | str) -> Date:
    """Parse the exact public ``YYYY-MM-DD`` date contract."""

    if isinstance(value, datetime):
        raise ValueError("date must be YYYY-MM-DD, not a datetime")
    if isinstance(value, Date):
        return value
    if not isinstance(value, str) or _DATE_RE.fullmatch(value.strip()) is None:
        raise ValueError("date must use YYYY-MM-DD")
    try:
        return Date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"invalid calendar date: {value!r}") from exc


def _timezone(value: str) -> tuple[str, tzinfo]:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("tz must be a non-empty IANA timezone")
    text = value.strip()
    zone = parse_timezone(text)
    if text.upper() in {"UTC", "Z"}:
        normalized = "UTC"
    elif isinstance(zone, ZoneInfo):
        normalized = zone.key
    else:
        normalized = text
    return normalized, zone


def _parse_when(value: datetime | str, timezone_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text or ("T" not in text and " " not in text):
            raise ValueError("when must be an ISO datetime with a date and time")
        try:
            parsed = datetime.fromisoformat(
                text[:-1] + "+00:00" if text.upper().endswith("Z") else text
            )
        except ValueError as exc:
            raise ValueError("when must be a valid ISO local or UTC datetime") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise TypeError("when must be a datetime, ISO datetime string, or None")
    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC)
    return resolve_moment(
        MomentInput(
            local_date=parsed.date(),
            local_time=parsed.time(),
            tz=timezone_name,
            label="Sky Day",
            fold=parsed.fold if parsed.fold == 1 else None,
        )
    ).utc_datetime


def _aware_utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "SKYDAY_PRIVACY",
    "SKYDAY_SCHEMA_VERSION",
    "SKYDAY_SYSTEM",
    "SKYDAY_TYPE",
    "SkyDayCache",
    "SkyDayCalculationError",
    "SkyDayRequest",
    "build_skyday",
    "parse_skyday_date",
    "resolve_skyday_request",
]
