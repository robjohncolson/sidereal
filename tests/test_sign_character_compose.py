"""Aspect composition must attach Midpoint sign character, not only planet lore."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from pathlib import Path

from sidereal.interpret.compose import compose_report
from sidereal.interpret.generate_seeds import write_seed_files
from sidereal.interpret.schema import generate_seed7_entries, SEED7_READY_COUNT
from sidereal.interpret.store import InterpretationStore
from sidereal.types import (
    AspectHit,
    Chart,
    ChartMeta,
    MomentInput,
    PointPos,
)


def test_seed7_completes_remaining_sign_character() -> None:
    entries = generate_seed7_entries()
    assert len(entries) == SEED7_READY_COUNT
    assert all(entry.type == "planet_in_sign" for entry in entries)
    assert all(entry.status == "ready" for entry in entries)
    assert any(entry.id == "planet_in_sign:jupiter:ophiuchus" for entry in entries)


def test_relationship_includes_sign_colored_character(tmp_path: Path) -> None:
    seed_dir = tmp_path / "seeds"
    write_seed_files(seed_dir)
    db = tmp_path / "db.sqlite"
    with InterpretationStore(db) as store:
        store.initialize()
        store.import_path(seed_dir)

        chart = Chart(
            meta=ChartMeta(
                input=MomentInput(
                    local_date=date(2000, 1, 1),
                    local_time=time(12, 0),
                    tz="UTC",
                    lat=0.0,
                    lon=0.0,
                    label="Character test",
                ),
                time_known=True,
                location_known=True,
                local_datetime=datetime(2000, 1, 1, 12, tzinfo=UTC),
                utc_datetime=datetime(2000, 1, 1, 12, tzinfo=UTC),
                jd_ut=2451545.0,
                jd_et=2451545.0007,
                zodiac_system="midpoint_v1",
                house_system="equal_house_12",
                aspect_profile="modern_major",
                swe_version="test",
                pyswisseph_version="test",
                boundary_version="1",
                ephemeris_backend="fixture",
            ),
            points=(
                PointPos(
                    id="sun",
                    name="Sun",
                    kind="body",
                    lon_date=40.0,
                    lon_j2000=40.0,
                    lat=0.0,
                    speed_long=1.0,
                    retro=False,
                    sign="aries",
                    degree_in_sign=8.7,
                    house=1,
                    blend=False,
                    secondary_sign=None,
                ),
                PointPos(
                    id="moon",
                    name="Moon",
                    kind="body",
                    lon_date=130.0,
                    lon_j2000=130.0,
                    lat=0.0,
                    speed_long=13.0,
                    retro=False,
                    sign="leo",
                    degree_in_sign=10.0,
                    house=5,
                    blend=False,
                    secondary_sign=None,
                ),
            ),
            cusps=None,
            aspects=(
                AspectHit(
                    body_a="moon",
                    body_b="sun",
                    aspect_id="square",
                    separation=90.0,
                    orb_used=8.0,
                    exactness=0.1,
                    force=0.98,
                    applying=True,
                ),
            ),
            patterns=(),
        )
        report = compose_report(chart, store).to_dict()
        rel = report["interpretation"]["relationships"][0]
        character = rel["character"]
        assert "Moon in Leo square Sun in Aries" == character["title"]
        assert "Leo" in character["synthesis"] and "Aries" in character["synthesis"]
        assert character["body_a_placement"]["sign"] == "leo"
        assert character["body_b_placement"]["sign"] == "aries"
        assert character["body_a_placement"]["reading"]["status"] == "ready"
        assert character["body_b_placement"]["reading"]["status"] == "ready"
        assert "initiative" in character["body_b_placement"]["reading"]["summary"].lower() or (
            "aries" in character["body_b_placement"]["reading"]["summary"].lower()
        )
        markdown = compose_report(chart, store).to_markdown()
        assert "Moon in Leo square Sun in Aries" in markdown
        assert "Midpoint sign character" in markdown
