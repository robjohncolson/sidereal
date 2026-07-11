from __future__ import annotations

from datetime import date, time

import pytest

from sidereal.ephemeris import EphemerisError, SwissEphemeris, resolve_ephe_path
from sidereal.timebase import julian_days, resolve_moment
from sidereal.types import MomentInput


swe = pytest.importorskip("swisseph")


def j2000_utc_jd() -> float:
    resolved = resolve_moment(MomentInput(date(2000, 1, 1), time(12), "UTC"))
    return julian_days(resolved.utc_datetime, swe)[1]


def test_published_j2000_epoch_sun_sanity_in_et() -> None:
    position, returned = swe.calc(
        2451545.0,
        swe.SUN,
        swe.FLG_SWIEPH | swe.FLG_SPEED,
    )

    assert position[0] == pytest.approx(280.368166558278, abs=1 / 3600)
    assert returned & swe.FLG_SPEED


def test_required_body_batch_and_south_node_derivation() -> None:
    batch = SwissEphemeris(swe_module=swe).calculate_positions(j2000_utc_jd())
    by_id = {item.id: item for item in batch.positions}

    assert len(batch.positions) == 12
    # Goldens differ slightly between the Moshier fallback and file-backed Swiss
    # Ephemeris (.se1). Prefer SE files when present; keep Moshier fixtures so
    # tests remain green in a clean checkout without data/ephe/*.se1.
    if batch.backend == "swisseph":
        assert by_id["sun"].lon_date == pytest.approx(280.368922860, abs=1e-5)
        assert by_id["sun"].lon_j2000 == pytest.approx(280.372792699, abs=1e-5)
        assert by_id["north_node"].lon_j2000 == pytest.approx(123.957892453, abs=1e-5)
    else:
        assert batch.backend == "moseph"
        assert by_id["sun"].lon_date == pytest.approx(280.368923865, abs=1e-5)
        assert by_id["sun"].lon_j2000 == pytest.approx(280.372793704, abs=1e-5)
        assert by_id["north_node"].lon_j2000 == pytest.approx(123.956765040, abs=1e-5)
    assert by_id["south_node"].lon_j2000 == pytest.approx(
        (by_id["north_node"].lon_j2000 + 180) % 360,
        abs=1e-12,
    )
    assert by_id["south_node"].speed_long == by_id["north_node"].speed_long


def test_vector_frame_conversion_has_golden_angles() -> None:
    houses = SwissEphemeris(swe_module=swe).calculate_houses(j2000_utc_jd(), 0, 0)

    assert houses.asc_date == pytest.approx(11.375506695, abs=1e-7)
    assert houses.mc_date == pytest.approx(279.612456148, abs=1e-7)
    assert houses.asc_j2000 == pytest.approx(11.379376534, abs=1e-7)
    assert houses.mc_j2000 == pytest.approx(279.616325987, abs=1e-7)
    assert houses.cusps_date[1] == pytest.approx(houses.cusps_date[0] + 30, abs=1e-10)
    assert houses.cusps_j2000[1] == pytest.approx(houses.cusps_j2000[0] + 30, abs=1e-10)


def test_each_equal_cusp_is_rotated_and_can_cross_a_midpoint_boundary() -> None:
    from sidereal.zodiac.midpoint import MidpointZodiac

    houses = SwissEphemeris(swe_module=swe).calculate_houses(
        2451545.0, 0.0, -161.08
    )
    zodiac = MidpointZodiac.load_default()

    assert houses.mc_date == pytest.approx(117.316230652, abs=1e-7)
    assert houses.mc_j2000 == pytest.approx(117.320100491, abs=1e-7)
    assert zodiac.map(houses.mc_j2000).sign == "cancer"


def test_house_conversion_does_not_mutate_host_sidereal_mode() -> None:
    swe.set_sid_mode(swe.SIDM_LAHIRI, 0.0, 0.0)
    flags = swe.FLG_SWIEPH | swe.FLG_SIDEREAL
    before = swe.calc_ut(2460000.5, swe.SUN, flags)[0][0]

    SwissEphemeris(swe_module=swe).calculate_houses(2460000.5, 0, 0)

    after = swe.calc_ut(2460000.5, swe.SUN, flags)[0][0]
    assert after == pytest.approx(before, abs=1e-12)


def test_strict_mode_rejects_moshier_fallback(tmp_path) -> None:
    engine = SwissEphemeris(
        ephe_path=tmp_path,
        require_swiss_ephemeris=True,
        swe_module=swe,
    )
    with pytest.raises(EphemerisError, match="required but unavailable"):
        engine.calculate_positions(j2000_utc_jd())


def test_ephemeris_path_resolution_is_deterministic(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SIDEREAL_EPHE_PATH", str(tmp_path))
    assert resolve_ephe_path() == tmp_path.resolve()

    missing = tmp_path / "missing"
    with pytest.raises(FileNotFoundError, match="not a directory"):
        resolve_ephe_path(missing)


def test_provider_reapplies_its_process_global_path_for_every_calculation(
    monkeypatch, tmp_path
) -> None:
    first_path = tmp_path / "first"
    second_path = tmp_path / "second"
    first_path.mkdir()
    second_path.mkdir()
    first = SwissEphemeris(ephe_path=first_path, swe_module=swe)
    SwissEphemeris(ephe_path=second_path, swe_module=swe)

    calls: list[str | None] = []
    original = swe.set_ephe_path

    def recording_set_ephe_path(path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(swe, "set_ephe_path", recording_set_ephe_path)
    first.calculate_positions(j2000_utc_jd())
    assert calls[0] == str(first_path.resolve())

    calls.clear()
    first.calculate_houses(j2000_utc_jd(), 0, 0)
    assert calls[0] == str(first_path.resolve())
