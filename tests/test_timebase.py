from __future__ import annotations

from datetime import UTC, date, time

import pytest

from sidereal.timebase import julian_days, parse_timezone, resolve_moment
from sidereal.types import MomentInput


def test_known_iana_time_resolves_to_utc() -> None:
    resolved = resolve_moment(
        MomentInput(date(2024, 7, 1), time(8, 30), "America/New_York")
    )

    assert resolved.time_known is True
    assert resolved.utc_datetime.isoformat() == "2024-07-01T12:30:00+00:00"
    assert resolved.calculation_time_assumption is None


def test_unknown_time_uses_explicit_local_noon_but_remains_unknown() -> None:
    resolved = resolve_moment(MomentInput(date(2000, 1, 1), None, "UTC"))

    assert resolved.time_known is False
    assert resolved.local_datetime.hour == 12
    assert resolved.utc_datetime.tzinfo is UTC
    assert resolved.calculation_time_assumption == "12:00 local (time not supplied)"


def test_numeric_offset_fallback() -> None:
    resolved = resolve_moment(MomentInput(date(2024, 1, 1), time(12), "+05:30"))
    assert resolved.utc_datetime.isoformat() == "2024-01-01T06:30:00+00:00"
    assert parse_timezone("UTC-04:00").utcoffset(None).total_seconds() == -4 * 3600


def test_dst_gap_and_unselected_fold_are_rejected() -> None:
    with pytest.raises(ValueError, match="Nonexistent"):
        resolve_moment(
            MomentInput(date(2024, 3, 10), time(2, 30), "America/New_York")
        )
    with pytest.raises(ValueError, match="Ambiguous"):
        resolve_moment(
            MomentInput(date(2024, 11, 3), time(1, 30), "America/New_York")
        )


def test_fold_selects_each_real_instant() -> None:
    first = resolve_moment(
        MomentInput(date(2024, 11, 3), time(1, 30), "America/New_York", fold=0)
    )
    second = resolve_moment(
        MomentInput(date(2024, 11, 3), time(1, 30), "America/New_York", fold=1)
    )

    assert first.utc_datetime.isoformat() == "2024-11-03T05:30:00+00:00"
    assert second.utc_datetime.isoformat() == "2024-11-03T06:30:00+00:00"


def test_fold_is_rejected_without_an_ambiguous_iana_local_time() -> None:
    with pytest.raises(ValueError, match="local_time"):
        resolve_moment(MomentInput(date(2024, 1, 1), None, "UTC", fold=1))
    with pytest.raises(ValueError, match="ambiguous IANA"):
        resolve_moment(MomentInput(date(2024, 1, 1), time(12), "UTC", fold=0))
    with pytest.raises(ValueError, match="unambiguous"):
        resolve_moment(
            MomentInput(date(2024, 1, 1), time(12), "America/New_York", fold=0)
        )


@pytest.mark.parametrize(
    "moment",
    [
        MomentInput(date(2000, 1, 1), time(12), "UTC", lat=1.0),
        MomentInput(date(2000, 1, 1), time(12), "UTC", lat=90.0, lon=0.0),
        MomentInput(date(2000, 1, 1), time(12), "UTC", lat=0.0, lon=181.0),
    ],
)
def test_invalid_locations_are_rejected(moment: MomentInput) -> None:
    with pytest.raises(ValueError):
        resolve_moment(moment)


def test_swiss_utc_conversion_keeps_et_ut_return_order() -> None:
    swe = pytest.importorskip("swisseph")
    resolved = resolve_moment(MomentInput(date(2000, 1, 1), time(12), "UTC"))

    jd_et, jd_ut = julian_days(resolved.utc_datetime, swe)

    assert jd_et == pytest.approx(2451545.0007428704, abs=1e-9)
    assert jd_ut == pytest.approx(2451545.00000411, abs=1e-9)
    assert jd_et > jd_ut
