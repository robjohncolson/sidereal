from __future__ import annotations

from datetime import UTC, date, datetime
import json
import math
from pathlib import Path

import pytest

from sidereal.cli import main
from sidereal.config import BODY_IDS
from sidereal.ephemeris import EphemerisError
from sidereal.skyday import (
    SkyDayCache,
    SkyDayCalculationError,
    build_skyday,
    resolve_skyday_request,
)
from sidereal.skypack import BODY_GLYPHS


FIXED_DATE = "2026-07-12"
FIXED_GENERATED = datetime(2026, 7, 12, 16, 1, tzinfo=UTC)
REQUIRED_TOP_LEVEL = {
    "schema_version",
    "type",
    "projection",
    "system",
    "privacy",
    "cache_date",
    "timezone",
    "epoch_utc",
    "generated_at",
    "sign_band",
    "movers",
    "natal_ghosts",
    "resonances",
    "same_body_delta",
    "resonance_rank",
}


def _assert_valid_skyday(payload: dict[str, object]) -> None:
    assert set(payload) == REQUIRED_TOP_LEVEL
    assert payload["schema_version"] == 1
    assert payload["type"] == "skyday"
    assert payload["projection"] == "ecliptic_band_v2"
    assert payload["system"] == "midpoint_v1"
    assert payload["privacy"] == "public"
    assert "natal_id" not in payload
    for field in (
        "natal_ghosts",
        "resonances",
        "same_body_delta",
        "resonance_rank",
    ):
        assert payload[field] == []

    for field in ("epoch_utc", "generated_at"):
        parsed = datetime.fromisoformat(payload[field])
        assert parsed.tzinfo is not None
        assert parsed.utcoffset().total_seconds() == 0.0

    sign_band = payload["sign_band"]
    assert isinstance(sign_band, list)
    assert len(sign_band) == 13
    for item in sign_band:
        assert set(item) == {
            "id",
            "glyph",
            "lon_start_j2000",
            "lon_end_j2000",
        }
        assert item["glyph"]
        assert 0.0 <= item["lon_start_j2000"] < 360.0
        assert 0.0 <= item["lon_end_j2000"] < 360.0

    movers = payload["movers"]
    assert isinstance(movers, list)
    assert tuple(item["id"] for item in movers) == BODY_IDS
    for item in movers:
        assert set(item) == {
            "id",
            "name",
            "glyph",
            "lon_j2000",
            "sign",
            "degree_in_sign",
            "kind",
            "retro",
        }
        assert item["glyph"] == BODY_GLYPHS[item["id"]]
        assert math.isfinite(item["lon_j2000"])
        assert 0.0 <= item["lon_j2000"] < 360.0
        assert math.isfinite(item["degree_in_sign"])
        assert item["kind"] in {"luminary", "planet", "node"}
        assert isinstance(item["retro"], bool)
    json.dumps(payload, ensure_ascii=False, allow_nan=False)


def test_skyday_schema_geometry_and_local_noon() -> None:
    payload = build_skyday(
        tz="America/New_York",
        date=FIXED_DATE,
        generated_at=FIXED_GENERATED,
    )

    _assert_valid_skyday(payload)
    assert payload["cache_date"] == FIXED_DATE
    assert payload["timezone"] == "America/New_York"
    assert payload["epoch_utc"] == "2026-07-12T16:00:00+00:00"
    assert payload["generated_at"] == "2026-07-12T16:01:00+00:00"


def test_skyday_request_uses_today_in_requested_timezone() -> None:
    request = resolve_skyday_request(
        tz="America/Los_Angeles",
        now=datetime(2026, 7, 12, 2, 0, tzinfo=UTC),
    )

    assert request.cache_date == date(2026, 7, 11)
    assert request.epoch_utc == datetime(2026, 7, 11, 19, 0, tzinfo=UTC)


def test_skyday_different_date_changes_geometry() -> None:
    first = build_skyday(
        tz="UTC",
        date="2026-07-12",
        generated_at=FIXED_GENERATED,
    )
    second = build_skyday(
        tz="UTC",
        date="2026-07-13",
        generated_at=FIXED_GENERATED,
    )

    assert first["cache_date"] == "2026-07-12"
    assert second["cache_date"] == "2026-07-13"
    assert first["epoch_utc"] != second["epoch_utc"]
    assert [item["lon_j2000"] for item in first["movers"]] != [
        item["lon_j2000"] for item in second["movers"]
    ]


def test_skyday_when_accepts_local_and_aware_iso_instants() -> None:
    local = resolve_skyday_request(
        tz="America/New_York",
        date=FIXED_DATE,
        when="2026-07-12T12:30:45.123456",
    )
    aware = resolve_skyday_request(
        tz="America/New_York",
        date=FIXED_DATE,
        when="2026-07-12T16:30:45.123456Z",
    )

    assert local.epoch_utc == aware.epoch_utc
    assert aware.epoch_utc.isoformat() == "2026-07-12T16:30:45.123456+00:00"

    independently_keyed = resolve_skyday_request(
        tz="UTC",
        date=FIXED_DATE,
        when="2026-07-13T00:00:00Z",
    )
    assert independently_keyed.cache_date == date(2026, 7, 12)
    assert independently_keyed.epoch_utc == datetime(2026, 7, 13, tzinfo=UTC)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"tz": "Mars/Olympus_Mons"}, "Unknown timezone"),
        ({"date": "20260712"}, "YYYY-MM-DD"),
        ({"date": "2026-02-30"}, "invalid calendar date"),
        ({"date": FIXED_DATE, "when": "not-a-datetime"}, "ISO datetime"),
    ],
)
def test_skyday_rejects_invalid_request_values(
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        resolve_skyday_request(**kwargs)


def test_skyday_cache_computes_once_per_normalized_timezone_and_date() -> None:
    calls: list[dict[str, object]] = []

    def fake_builder(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {
            "cache_date": kwargs["date"].isoformat(),
            "timezone": kwargs["tz"],
            "epoch_utc": kwargs["when"].isoformat(),
            "generated_at": f"build-{len(calls)}",
            "movers": [len(calls)],
        }

    cache = SkyDayCache(builder=fake_builder)
    first = cache.get(
        tz="Z",
        date=FIXED_DATE,
        when="2026-07-12T12:00:00Z",
    )
    second = cache.get(
        tz="UTC",
        date=FIXED_DATE,
        when="2026-07-12T20:00:00Z",
    )
    first["movers"].append("caller mutation")
    third = cache.get(tz="UTC", date=FIXED_DATE)

    assert len(calls) == 1
    assert first["generated_at"] == second["generated_at"] == "build-1"
    assert second["epoch_utc"] == "2026-07-12T12:00:00+00:00"
    assert third["movers"] == [1]

    next_day = cache.get(tz="UTC", date="2026-07-13")
    assert len(calls) == 2
    assert next_day["cache_date"] == "2026-07-13"
    assert next_day["generated_at"] == "build-2"

    other_timezone = cache.get(tz="America/New_York", date=FIXED_DATE)
    assert len(calls) == 3
    assert other_timezone["timezone"] == "America/New_York"
    assert other_timezone["epoch_utc"] == "2026-07-12T16:00:00+00:00"


def test_skyday_cache_wraps_calculation_failures() -> None:
    def fail_builder(**_kwargs: object) -> dict[str, object]:
        raise EphemerisError("ephemeris unavailable")

    cache = SkyDayCache(builder=fail_builder)
    with pytest.raises(SkyDayCalculationError, match="ephemeris unavailable"):
        cache.get(date=FIXED_DATE)


def test_sky_day_cli_writes_valid_json(tmp_path: Path) -> None:
    output = tmp_path / "nested" / "skyday.json"

    assert main(
        [
            "sky-day",
            "--tz",
            "UTC",
            "--date",
            FIXED_DATE,
            "-o",
            str(output),
        ]
    ) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    _assert_valid_skyday(payload)
    assert payload["cache_date"] == FIXED_DATE
    assert payload["epoch_utc"] == "2026-07-12T12:00:00+00:00"
