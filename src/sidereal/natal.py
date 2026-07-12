"""Private natal profile records and an injectable storage interface."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
import math
import re
from threading import RLock
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from .auth import normalize_user_id
from .timebase import parse_timezone


NATAL_PROFILE_SCHEMA_VERSION = 1
NATAL_PROFILE_TYPE = "natal_profile"
_NATAL_INPUT_FIELDS = frozenset(
    (
        "birth_date",
        "birth_time",
        "time_unknown",
        "tz",
        "lat",
        "lon",
        "place_label",
    )
)
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_TIME_RE = re.compile(r"\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?")


class NatalStoreError(RuntimeError):
    """A durable natal backend could not complete a requested operation."""


@dataclass(frozen=True, slots=True)
class NatalRecord:
    """Validated private birth metadata for exactly one authenticated user."""

    user_id: str
    birth_date: date
    birth_time: time | None
    time_unknown: bool
    tz: str
    lat: float | None
    lon: float | None
    place_label: str
    updated_at: datetime

    def __post_init__(self) -> None:
        normalized_user_id = normalize_user_id(self.user_id)
        if self.user_id != normalized_user_id:
            raise ValueError("user_id must already be normalized")
        if not isinstance(self.birth_date, date) or isinstance(
            self.birth_date, datetime
        ):
            raise ValueError("birth_date must be a calendar date")
        if not isinstance(self.time_unknown, bool):
            raise ValueError("time_unknown must be a boolean")
        if self.birth_time is not None:
            if not isinstance(self.birth_time, time):
                raise ValueError("birth_time must be a civil time or None")
            if self.birth_time.tzinfo is not None:
                raise ValueError("birth_time must not include a UTC offset; use tz")
        if self.time_unknown and self.birth_time is not None:
            raise ValueError("unknown-time natal records must store birth_time as null")
        if not self.time_unknown and self.birth_time is None:
            raise ValueError("known-time natal records require birth_time")
        normalized_tz = _normalize_timezone(self.tz)
        if self.tz != normalized_tz:
            raise ValueError("tz must already be a canonical IANA timezone")
        _validate_location(self.lat, self.lon)
        if not isinstance(self.place_label, str):
            raise ValueError("place_label must be a string")
        if len(self.place_label) > 240:
            raise ValueError("place_label must be at most 240 characters")
        if not isinstance(self.updated_at, datetime) or self.updated_at.tzinfo is None:
            raise ValueError("updated_at must be a timezone-aware datetime")

    def to_dict(self) -> dict[str, Any]:
        """Return authenticated API metadata without ephemeris geometry."""

        return {
            "schema_version": NATAL_PROFILE_SCHEMA_VERSION,
            "type": NATAL_PROFILE_TYPE,
            "user_id": self.user_id,
            "birth_date": self.birth_date.isoformat(),
            "birth_time": (
                self.birth_time.isoformat() if self.birth_time is not None else None
            ),
            "time_unknown": self.time_unknown,
            "tz": self.tz,
            "lat": self.lat,
            "lon": self.lon,
            "place_label": self.place_label,
            "updated_at": self.updated_at.astimezone(UTC).isoformat(),
        }

    def storage_dict(self) -> dict[str, Any]:
        """Return the Supabase ``natal_charts`` row shape."""

        payload = self.to_dict()
        payload.pop("schema_version")
        payload.pop("type")
        return payload

    @classmethod
    def from_storage(cls, payload: Mapping[str, Any]) -> NatalRecord:
        """Validate and reconstruct one backend row."""

        if not isinstance(payload, Mapping):
            raise NatalStoreError("Natal backend returned a non-object row")
        try:
            raw_date = payload["birth_date"]
            raw_time = payload.get("birth_time")
            raw_updated = payload["updated_at"]
            birth_date = date.fromisoformat(_required_text(raw_date, "birth_date"))
            birth_time = (
                None
                if raw_time in (None, "")
                else time.fromisoformat(_required_text(raw_time, "birth_time"))
            )
            updated_at = datetime.fromisoformat(
                _required_text(raw_updated, "updated_at").replace("Z", "+00:00")
            )
            return cls(
                user_id=_required_text(payload.get("user_id"), "user_id"),
                birth_date=birth_date,
                birth_time=birth_time,
                time_unknown=_required_bool(
                    payload.get("time_unknown"), "time_unknown"
                ),
                tz=_required_text(payload.get("tz"), "tz"),
                lat=_optional_number(payload.get("lat"), "lat"),
                lon=_optional_number(payload.get("lon"), "lon"),
                place_label=_string(payload.get("place_label", ""), "place_label"),
                updated_at=updated_at,
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, NatalStoreError):  # pragma: no cover - defensive
                raise
            raise NatalStoreError(f"Natal backend returned an invalid row: {exc}") from exc


class NatalStore(Protocol):
    """Private profile persistence, swappable between memory and Supabase."""

    def get(self, user_id: str) -> NatalRecord | None:
        ...

    def upsert(self, record: NatalRecord) -> NatalRecord:
        ...

    def delete(self, user_id: str) -> bool:
        ...


class MemoryNatalStore:
    """Thread-safe process-memory backend for local development and tests."""

    def __init__(self, records: tuple[NatalRecord, ...] = ()) -> None:
        self._records: dict[str, NatalRecord] = {}
        self._lock = RLock()
        for record in records:
            self.upsert(record)

    def get(self, user_id: str) -> NatalRecord | None:
        normalized = normalize_user_id(user_id)
        with self._lock:
            return self._records.get(normalized)

    def upsert(self, record: NatalRecord) -> NatalRecord:
        if not isinstance(record, NatalRecord):
            raise TypeError("record must be a NatalRecord")
        with self._lock:
            self._records[record.user_id] = record
        return record

    def delete(self, user_id: str) -> bool:
        normalized = normalize_user_id(user_id)
        with self._lock:
            return self._records.pop(normalized, None) is not None


def natal_record_from_payload(
    user_id: str,
    payload: Mapping[str, Any],
    *,
    updated_at: datetime | None = None,
) -> NatalRecord:
    """Validate the authenticated upsert body and normalize unknown time."""

    if not isinstance(payload, Mapping):
        raise ValueError("natal payload must be an object")
    extras = sorted(set(payload) - _NATAL_INPUT_FIELDS)
    if extras:
        raise ValueError(f"unsupported natal field(s): {', '.join(extras)}")
    raw_date = _required_text(payload.get("birth_date"), "birth_date")
    if _DATE_RE.fullmatch(raw_date) is None:
        raise ValueError("birth_date must use YYYY-MM-DD")
    try:
        birth_date = date.fromisoformat(raw_date)
    except ValueError as exc:
        raise ValueError("birth_date must use YYYY-MM-DD") from exc

    raw_time = payload.get("birth_time")
    parsed_time: time | None
    if raw_time in (None, ""):
        parsed_time = None
    else:
        raw_time_text = _required_text(raw_time, "birth_time")
        if _TIME_RE.fullmatch(raw_time_text) is None:
            raise ValueError("birth_time must use HH:MM or HH:MM:SS")
        try:
            parsed_time = time.fromisoformat(raw_time_text)
        except ValueError as exc:
            raise ValueError("birth_time must use HH:MM or HH:MM:SS") from exc
        if parsed_time.tzinfo is not None:
            raise ValueError("birth_time must not include a UTC offset; use tz")
    raw_unknown = payload.get("time_unknown")
    if raw_unknown is None:
        time_unknown = parsed_time is None
    elif not isinstance(raw_unknown, bool):
        raise ValueError("time_unknown must be a boolean")
    else:
        time_unknown = raw_unknown or parsed_time is None
    birth_time = None if time_unknown else parsed_time

    timezone_name = _normalize_timezone(_required_text(payload.get("tz"), "tz"))
    lat = _optional_number(payload.get("lat"), "lat")
    lon = _optional_number(payload.get("lon"), "lon")
    _validate_location(lat, lon)
    place_label = _string(payload.get("place_label", ""), "place_label").strip()
    if len(place_label) > 240:
        raise ValueError("place_label must be at most 240 characters")

    changed_at = updated_at or datetime.now(UTC)
    if not isinstance(changed_at, datetime) or changed_at.tzinfo is None:
        raise ValueError("updated_at must be timezone-aware")
    return NatalRecord(
        user_id=normalize_user_id(user_id),
        birth_date=birth_date,
        birth_time=birth_time,
        time_unknown=time_unknown,
        tz=timezone_name,
        lat=lat,
        lon=lon,
        place_label=place_label,
        updated_at=changed_at.astimezone(UTC),
    )


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _required_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def _optional_number(value: Any, name: str) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number or null")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number or null") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number or null")
    return result


def _validate_location(lat: float | None, lon: float | None) -> None:
    if (lat is None) != (lon is None):
        raise ValueError("lat and lon must be supplied together")
    if lat is not None and not -90.0 < lat < 90.0:
        raise ValueError("lat must be strictly between -90 and 90 degrees")
    if lon is not None and not -180.0 <= lon <= 180.0:
        raise ValueError("lon must be between -180 and 180 degrees")


def _normalize_timezone(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("tz must be a non-empty IANA timezone")
    selected = value.strip()
    zone = parse_timezone(selected)
    if selected.upper() in {"UTC", "Z"}:
        return "UTC"
    if not isinstance(zone, ZoneInfo):
        raise ValueError("tz must be an IANA timezone name")
    return zone.key


__all__ = [
    "MemoryNatalStore",
    "NATAL_PROFILE_SCHEMA_VERSION",
    "NATAL_PROFILE_TYPE",
    "NatalRecord",
    "NatalStore",
    "NatalStoreError",
    "natal_record_from_payload",
]
