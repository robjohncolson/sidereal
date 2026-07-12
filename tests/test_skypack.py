from __future__ import annotations

from datetime import UTC, datetime
import json
import math
from pathlib import Path

import pytest

from sidereal.cli import main
from sidereal.config import BODY_IDS
from sidereal.skypack import (
    ASPECT_GLYPHS,
    BODY_GLYPHS,
    build_skypack,
    rank_resonances,
    shortest_arc,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHARTS_DIR = PROJECT_ROOT / "charts"
BOBBY_ID = "bobby-19831129T132400Z-e1d0a0c471"
FIXED_LOCAL_WHEN = "2026-07-11T14:09:00"
FIXED_EPOCH_UTC = "2026-07-11T18:09:00+00:00"
FIXTURE_PATH = PROJECT_ROOT / "data" / "fixtures" / "skypack_bobby_sample.json"

REQUIRED_TOP_LEVEL = {
    "schema_version",
    "type",
    "projection",
    "generated_at",
    "epoch_utc",
    "timezone",
    "location",
    "natal_id",
    "natal_label",
    "system",
    "privacy",
    "sign_band",
    "movers",
    "natal_ghosts",
    "resonances",
    "same_body_delta",
    "resonance_rank",
}


def _build_fixed_pack() -> dict[str, object]:
    return build_skypack(
        BOBBY_ID,
        when=FIXED_LOCAL_WHEN,
        tz="America/New_York",
        charts_dir=CHARTS_DIR,
        generated_at=datetime(2026, 7, 11, 18, 9, tzinfo=UTC),
    )


def _assert_valid_pack(pack: dict[str, object]) -> None:
    assert set(pack) == REQUIRED_TOP_LEVEL
    assert pack["schema_version"] == 2
    assert pack["type"] == "skypack"
    assert pack["projection"] == "ecliptic_band_v2"
    assert pack["system"] == "midpoint_v1"
    assert pack["privacy"] == "local_only"
    assert pack["location"] is None
    assert pack["epoch_utc"] == FIXED_EPOCH_UTC
    for key in ("generated_at", "epoch_utc"):
        timestamp = datetime.fromisoformat(pack[key])
        assert timestamp.tzinfo is not None
        assert timestamp.utcoffset().total_seconds() == 0.0

    sign_band = pack["sign_band"]
    assert isinstance(sign_band, list)
    assert len(sign_band) == 13
    assert {item["id"] for item in sign_band} == {
        "aries",
        "taurus",
        "gemini",
        "cancer",
        "leo",
        "virgo",
        "libra",
        "scorpio",
        "ophiuchus",
        "sagittarius",
        "capricorn",
        "aquarius",
        "pisces",
    }
    for item in sign_band:
        assert set(item) == {
            "id",
            "glyph",
            "lon_start_j2000",
            "lon_end_j2000",
        }
        assert item["glyph"]
        for key in ("lon_start_j2000", "lon_end_j2000"):
            assert math.isfinite(item[key])
            assert 0.0 <= item[key] < 360.0

    movers = pack["movers"]
    ghosts = pack["natal_ghosts"]
    assert isinstance(movers, list)
    assert isinstance(ghosts, list)
    assert tuple(item["id"] for item in movers) == BODY_IDS
    assert tuple(item["id"] for item in ghosts) == BODY_IDS
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
    for item in ghosts:
        assert set(item) == {
            "id",
            "name",
            "glyph",
            "lon_j2000",
            "sign",
            "degree_in_sign",
            "kind",
        }
    for item in (*movers, *ghosts):
        assert item["glyph"] == BODY_GLYPHS[item["id"]]
        assert math.isfinite(item["lon_j2000"])
        assert 0.0 <= item["lon_j2000"] < 360.0
        assert math.isfinite(item["degree_in_sign"])
        assert item["kind"] in {"planet", "luminary", "node"}
    assert all(isinstance(item["retro"], bool) for item in movers)
    assert all("retro" not in item and "speed_long" not in item for item in ghosts)

    mover_ids = {item["id"] for item in movers}
    ghost_ids = {item["id"] for item in ghosts}
    resonances = pack["resonances"]
    assert isinstance(resonances, list)
    for item in resonances:
        assert set(item) == {
            "transit_body",
            "natal_point",
            "aspect_id",
            "aspect_glyph",
            "separation",
            "orb",
            "orb_limit",
            "applying",
        }
        assert item["transit_body"] in mover_ids
        assert item["natal_point"] in ghost_ids
        assert item["aspect_id"] in ASPECT_GLYPHS
        assert item["aspect_glyph"] == ASPECT_GLYPHS[item["aspect_id"]]
        assert 0.0 <= item["separation"] <= 180.0
        assert 0.0 <= item["orb"] <= item["orb_limit"]
        assert item["applying"] in (True, False, None)

    movers_by_id = {item["id"]: item for item in movers}
    ghosts_by_id = {item["id"]: item for item in ghosts}
    common_ids = tuple(
        body_id
        for body_id in BODY_IDS
        if body_id in movers_by_id and body_id in ghosts_by_id
    )
    same_body_delta = pack["same_body_delta"]
    assert isinstance(same_body_delta, list)
    assert tuple(item["id"] for item in same_body_delta) == common_ids
    for item in same_body_delta:
        assert set(item) == {
            "id",
            "delta_deg",
            "mover_lon_j2000",
            "natal_lon_j2000",
        }
        mover_lon = movers_by_id[item["id"]]["lon_j2000"]
        natal_lon = ghosts_by_id[item["id"]]["lon_j2000"]
        raw_delta = abs(mover_lon - natal_lon) % 360.0
        expected_delta = min(raw_delta, 360.0 - raw_delta)
        assert item["mover_lon_j2000"] == mover_lon
        assert item["natal_lon_j2000"] == natal_lon
        assert math.isfinite(item["delta_deg"])
        assert item["delta_deg"] == pytest.approx(expected_delta, abs=1e-6)
        assert 0.0 <= item["delta_deg"] <= 180.0

    resonance_by_key = {
        (
            item["transit_body"],
            item["natal_point"],
            item["aspect_id"],
        ): item
        for item in resonances
    }
    assert len(resonance_by_key) == len(resonances)
    resonance_rank = pack["resonance_rank"]
    assert isinstance(resonance_rank, list)
    assert len(resonance_rank) == len(resonances)
    assert [item["rank"] for item in resonance_rank] == list(
        range(1, len(resonance_rank) + 1)
    )
    actual_sort_keys = []
    for item in resonance_rank:
        assert set(item) == {
            "transit_body",
            "natal_point",
            "aspect_id",
            "aspect_glyph",
            "orb",
            "orb_limit",
            "rank",
        }
        key = (
            item["transit_body"],
            item["natal_point"],
            item["aspect_id"],
        )
        source = resonance_by_key[key]
        assert item["aspect_glyph"] == source["aspect_glyph"]
        assert item["orb"] == source["orb"]
        assert item["orb_limit"] == source["orb_limit"]
        actual_sort_keys.append(
            (
                item["orb"] / item["orb_limit"],
                item["transit_body"],
                item["natal_point"],
                item["aspect_id"],
            )
        )
    assert actual_sort_keys == sorted(actual_sort_keys)


@pytest.mark.parametrize(
    ("longitude_a", "longitude_b", "expected"),
    [
        (0.0, 0.0, 0.0),
        (0.0, 180.0, 180.0),
        (10.0, 350.0, 20.0),
        (0.0, 90.0, 90.0),
    ],
)
def test_shortest_arc_cases(
    longitude_a: float,
    longitude_b: float,
    expected: float,
) -> None:
    assert shortest_arc(longitude_a, longitude_b) == pytest.approx(expected)


@pytest.mark.parametrize("invalid", [math.inf, -math.inf, math.nan])
def test_shortest_arc_rejects_non_finite_values(invalid: float) -> None:
    with pytest.raises(ValueError, match="longitudes must be finite"):
        shortest_arc(invalid, 0.0)


def test_resonance_rank_uses_normalized_orb_and_lexical_ties() -> None:
    rows = [
        {
            "transit_body": "venus",
            "natal_point": "sun",
            "aspect_id": "trine",
            "aspect_glyph": "△",
            "orb": 2.0,
            "orb_limit": 8.0,
        },
        {
            "transit_body": "mars",
            "natal_point": "sun",
            "aspect_id": "square",
            "aspect_glyph": "□",
            "orb": 1.0,
            "orb_limit": 4.0,
        },
        {
            "transit_body": "mars",
            "natal_point": "moon",
            "aspect_id": "trine",
            "aspect_glyph": "△",
            "orb": 2.0,
            "orb_limit": 8.0,
        },
        {
            "transit_body": "mars",
            "natal_point": "moon",
            "aspect_id": "sextile",
            "aspect_glyph": "⚹",
            "orb": 1.5,
            "orb_limit": 6.0,
        },
        {
            "transit_body": "jupiter",
            "natal_point": "moon",
            "aspect_id": "opposition",
            "aspect_glyph": "☍",
            "orb": 0.5,
            "orb_limit": 5.0,
        },
    ]

    ranked = rank_resonances(rows)

    assert [item["rank"] for item in ranked] == [1, 2, 3, 4, 5]
    assert [
        (item["transit_body"], item["natal_point"], item["aspect_id"])
        for item in ranked
    ] == [
        ("jupiter", "moon", "opposition"),
        ("mars", "moon", "sextile"),
        ("mars", "moon", "trine"),
        ("mars", "sun", "square"),
        ("venus", "sun", "trine"),
    ]


def test_resonance_rank_rejects_missing_or_invalid_limits() -> None:
    base = {
        "transit_body": "mars",
        "natal_point": "moon",
        "aspect_id": "trine",
        "aspect_glyph": "△",
        "orb": 1.0,
    }

    with pytest.raises(ValueError, match="missing required field 'orb_limit'"):
        rank_resonances([base])
    with pytest.raises(ValueError, match="orb_limit must be positive"):
        rank_resonances([{**base, "orb_limit": 0.0}])


def test_skypack_schema_and_body_geometry() -> None:
    pack = _build_fixed_pack()

    _assert_valid_pack(pack)
    assert pack["natal_id"] == BOBBY_ID
    assert pack["natal_label"] == "bobby"
    assert pack["timezone"] == "America/New_York"


def test_skypack_resonances_use_major_aspect_glyphs() -> None:
    pack = _build_fixed_pack()

    assert pack["resonances"]
    for item in pack["resonances"]:
        assert item["aspect_id"] in ASPECT_GLYPHS
        assert item["aspect_glyph"] == ASPECT_GLYPHS[item["aspect_id"]]


def test_skypack_json_round_trip() -> None:
    pack = _build_fixed_pack()

    loaded = json.loads(
        json.dumps(pack, ensure_ascii=False, allow_nan=False)
    )
    assert set(loaded) == REQUIRED_TOP_LEVEL
    assert loaded["epoch_utc"] == FIXED_EPOCH_UTC


def test_skypack_preserves_explicit_fractional_seconds() -> None:
    pack = build_skypack(
        BOBBY_ID,
        when="2026-07-11T18:09:00.123456",
        tz="UTC",
        charts_dir=CHARTS_DIR,
        generated_at=datetime(2026, 7, 11, 18, 9, tzinfo=UTC),
    )

    assert pack["epoch_utc"] == "2026-07-11T18:09:00.123456+00:00"


def test_skypack_cli_smoke(tmp_path: Path) -> None:
    output = tmp_path / "bobby-skypack.json"

    assert main(
        [
            "skypack",
            "--natal",
            BOBBY_ID,
            "--when",
            FIXED_LOCAL_WHEN,
            "--tz",
            "America/New_York",
            "--charts-dir",
            str(CHARTS_DIR),
            "-o",
            str(output),
        ]
    ) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    _assert_valid_pack(payload)


def test_checked_in_bobby_fixture_uses_same_schema_checks() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    _assert_valid_pack(payload)
    assert payload["natal_id"] == BOBBY_ID
