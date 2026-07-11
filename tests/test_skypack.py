from __future__ import annotations

from datetime import UTC, datetime
import json
import math
from pathlib import Path

from sidereal.cli import main
from sidereal.config import BODY_IDS
from sidereal.skypack import ASPECT_GLYPHS, BODY_GLYPHS, build_skypack


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
    assert pack["schema_version"] == 1
    assert pack["type"] == "skypack"
    assert pack["projection"] == "ecliptic_dome_v1"
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
