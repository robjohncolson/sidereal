"""Authenticated natal computation and per-user daily skypack caching."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from threading import RLock
from typing import Any
from zoneinfo import ZoneInfo

from .chart import compute
from .config import ChartConfig
from .natal import NatalRecord
from .skypack import build_skypack_from_chart
from .timebase import parse_timezone
from .types import Chart, MomentInput


PersonalPackBuilder = Callable[..., dict[str, Any]]


def compute_natal_chart(
    record: NatalRecord,
    *,
    boundary_path: Path | str | None = None,
    ephe_path: Path | str | None = None,
    require_swiss_ephemeris: bool = False,
) -> tuple[Chart, ChartConfig]:
    """Compute private natal geometry directly, never through ``charts/``."""

    if not isinstance(record, NatalRecord):
        raise TypeError("record must be a NatalRecord")
    include_houses = (
        not record.time_unknown and record.lat is not None and record.lon is not None
    )
    config = ChartConfig(
        boundary_path=(
            Path(boundary_path).expanduser() if boundary_path is not None else None
        ),
        ephe_path=Path(ephe_path).expanduser() if ephe_path is not None else None,
        require_swiss_ephemeris=require_swiss_ephemeris,
        include_houses=include_houses,
        include_patterns=False,
    )
    config.validate()
    moment = MomentInput(
        local_date=record.birth_date,
        local_time=None if record.time_unknown else record.birth_time,
        tz=record.tz,
        lat=record.lat,
        lon=record.lon,
        label="Saved sky",
    )
    return compute(moment, config), config


def build_personal_skypack(
    record: NatalRecord,
    *,
    when: datetime | None = None,
    tz: str | None = None,
    boundary_path: Path | str | None = None,
    ephe_path: Path | str | None = None,
    require_swiss_ephemeris: bool = False,
) -> dict[str, Any]:
    """Build one natal-bearing private pack at the current moving epoch."""

    generated = _aware_utc(
        when or datetime.now(UTC).replace(microsecond=0),
        "when",
    )
    chart, config = compute_natal_chart(
        record,
        boundary_path=boundary_path,
        ephe_path=ephe_path,
        require_swiss_ephemeris=require_swiss_ephemeris,
    )
    return build_skypack_from_chart(
        chart,
        config,
        natal_id=record.user_id,
        natal_label="Saved sky",
        when=generated,
        tz=record.tz if tz is None else tz,
        privacy="user_private",
        generated_at=generated,
    )


class PersonalSkyCache:
    """Thread-safe private pack cache keyed by user, timezone, and civil date."""

    def __init__(self, builder: PersonalPackBuilder) -> None:
        self._builder = builder
        self._entries: dict[tuple[str, str, str], tuple[str, dict[str, Any]]] = {}
        self._lock = RLock()

    def get(
        self,
        record: NatalRecord,
        *,
        tz: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        timezone_name = _timezone_name(record.tz if tz is None else tz)
        zone = parse_timezone(timezone_name)
        current = _aware_utc(
            now or datetime.now(UTC).replace(microsecond=0),
            "now",
        )
        cache_date = current.astimezone(zone).date().isoformat()
        key = (record.user_id, timezone_name, cache_date)
        version = hashlib.sha256(
            json.dumps(
                record.storage_dict(),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None and cached[0] == version:
                return deepcopy(cached[1])
            payload = self._builder(record, when=current, tz=timezone_name)
            if not isinstance(payload, dict):
                raise TypeError("personal skypack builder must return a dict")
            self._entries[key] = (version, deepcopy(payload))
            while len(self._entries) > 512:
                self._entries.pop(next(iter(self._entries)))
            return deepcopy(payload)

    def invalidate(self, user_id: str) -> None:
        with self._lock:
            for key in tuple(self._entries):
                if key[0] == user_id:
                    self._entries.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


def _timezone_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("tz must be a non-empty IANA timezone")
    selected = value.strip()
    zone = parse_timezone(selected)
    if selected.upper() in {"UTC", "Z"}:
        return "UTC"
    if isinstance(zone, ZoneInfo):
        return zone.key
    return selected


def _aware_utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "PersonalPackBuilder",
    "PersonalSkyCache",
    "build_personal_skypack",
    "compute_natal_chart",
]
