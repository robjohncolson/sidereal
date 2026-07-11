from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sqlite3

import pytest

from sidereal.interpret.generate_seeds import check_seed_files, rendered_seed_files
from sidereal.interpret.schema import (
    CORE_INVENTORY_COUNT,
    SEED1_READY_COUNT,
    SEED2_PERSONAL_PLANETS,
    SEED2_READY_COUNT,
    SEED3_READY_COUNT,
    SEED4_READY_COUNT,
    SEED5_READY_COUNT,
    SEED6_READY_COUNT,
    SEED7_READY_COUNT,
    TOTAL_INVENTORY_COUNT,
    ASPECT_TYPES,
    aspect_key,
    generate_seed0_entries,
    generate_seed1_entries,
    generate_seed2_entries,
    InterpretationEntry,
)
from sidereal.interpret.store import (
    InterpretationStore,
    SeedImportError,
    StoreNotInitializedError,
)


SEED_DIRECTORY = Path(__file__).resolve().parents[1] / "data" / "seeds"


def test_interpretation_inventory_has_exact_v1_counts() -> None:
    entries = generate_seed0_entries()
    counts = Counter(entry.type for entry in entries)

    assert counts == {
        "sign": 13,
        "house": 12,
        "planet": 12,
        "planet_in_sign": 156,
        "planet_in_house": 144,
        "sign_on_house": 156,
        "aspect": 445,
        "angle_in_sign": 26,
        "pattern": 3,
    }
    assert sum(count for kind, count in counts.items() if kind != "pattern") == CORE_INVENTORY_COUNT
    assert len(entries) == TOTAL_INVENTORY_COUNT
    assert len({entry.id for entry in entries}) == TOTAL_INVENTORY_COUNT
    assert {entry.id for entry in entries if entry.type == "pattern"} == {
        "pattern:stellium",
        "pattern:t_square",
        "pattern:grand_trine",
    }


def test_seed1_is_exact_non_stub_set_with_substantive_text() -> None:
    entries = generate_seed1_entries()
    expected = {
        *(f"sign:{sign}" for sign in (
            "aries", "taurus", "gemini", "cancer", "leo", "virgo", "libra",
            "scorpio", "ophiuchus", "sagittarius", "capricorn", "aquarius", "pisces",
        )),
        *(f"house:{house}" for house in range(1, 13)),
        *(f"planet:{planet}" for planet in (
            "sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn",
            "uranus", "neptune", "pluto", "north_node", "south_node",
        )),
        *(f"planet_in_sign:{planet}:{sign}" for planet in ("sun", "moon") for sign in (
            "aries", "taurus", "gemini", "cancer", "leo", "virgo", "libra",
            "scorpio", "ophiuchus", "sagittarius", "capricorn", "aquarius", "pisces",
        )),
        *(f"angle_in_sign:asc:{sign}" for sign in (
            "aries", "taurus", "gemini", "cancer", "leo", "virgo", "libra",
            "scorpio", "ophiuchus", "sagittarius", "capricorn", "aquarius", "pisces",
        )),
    }

    assert len(entries) == SEED1_READY_COUNT == 76
    assert {entry.id for entry in entries} == expected
    assert all(entry.status == "ready" for entry in entries)
    assert all(entry.source == "original" for entry in entries)
    assert all("not yet authored" not in entry.summary for entry in entries)
    assert all(len(entry.summary) >= 80 for entry in entries)
    assert "An Pisces Ascendant" not in next(
        entry.summary for entry in entries if entry.id == "angle_in_sign:asc:pisces"
    )
    ophiuchus = next(entry for entry in entries if entry.id == "sign:ophiuchus")
    assert "first-class sign" in ophiuchus.summary
    assert "not making medical" in ophiuchus.summary


def test_seed2_personal_aspects_are_exact_ready_set() -> None:
    from itertools import combinations

    entries = generate_seed2_entries()
    expected = {
        f"aspect:{a}:{aspect}:{b}"
        for a, b in combinations(sorted(SEED2_PERSONAL_PLANETS), 2)
        for aspect in ASPECT_TYPES
    }
    assert len(entries) == SEED2_READY_COUNT == 105
    assert {entry.id for entry in entries} == expected
    assert all(entry.status == "ready" for entry in entries)
    assert all(entry.source == "original" for entry in entries)
    assert all(entry.type == "aspect" for entry in entries)
    assert all("not yet authored" not in entry.summary for entry in entries)
    assert all(len(entry.summary) >= 120 for entry in entries)
    assert all(entry.growth for entry in entries)
    moon_sun = next(entry for entry in entries if entry.id == "aspect:moon:square:sun")
    assert "emotional needs" in moon_sun.summary
    assert "core purpose" in moon_sun.summary
    assert "prediction" in moon_sun.summary


def test_seed_files_are_checked_in_deterministically() -> None:
    assert rendered_seed_files() == rendered_seed_files()
    assert check_seed_files(SEED_DIRECTORY) == ()


def test_store_import_is_atomic_idempotent_and_auditable(tmp_path: Path) -> None:
    db_path = tmp_path / "interpretations.db"
    ready_total = (
        SEED1_READY_COUNT
        + SEED2_READY_COUNT
        + SEED3_READY_COUNT
        + SEED4_READY_COUNT
        + SEED5_READY_COUNT
        + SEED6_READY_COUNT
        + SEED7_READY_COUNT
    )
    with InterpretationStore(db_path) as store:
        store.initialize()
        first = store.import_path(SEED_DIRECTORY)
        audit = store.audit()
        sun_ophiuchus = store.get("planet_in_sign:sun:ophiuchus")
        moon_sun_square = store.get("aspect:moon:square:sun")
        jupiter_aries = store.get("planet_in_sign:jupiter:aries")

        assert first.files == 8
        assert first.records == TOTAL_INVENTORY_COUNT + ready_total
        assert first.inserted == TOTAL_INVENTORY_COUNT
        assert first.updated == ready_total
        assert audit.expected == TOTAL_INVENTORY_COUNT
        assert (audit.ready, audit.stub, audit.missing) == (ready_total, TOTAL_INVENTORY_COUNT - ready_total, 0)
        assert sun_ophiuchus is not None and sun_ophiuchus.status == "ready"
        assert moon_sun_square is not None and moon_sun_square.status == "ready"
        assert jupiter_aries is not None and jupiter_aries.status == "ready"

        second = store.import_path(SEED_DIRECTORY)
        assert second.inserted == second.updated == 0
        assert second.unchanged == TOTAL_INVENTORY_COUNT
        assert second.skipped == ready_total


def test_aspect_key_is_unordered_and_alphabetical() -> None:
    assert aspect_key("sun", "square", "moon") == "aspect:moon:square:sun"
    assert aspect_key("moon", "square", "sun") == "aspect:moon:square:sun"
    assert aspect_key("jupiter", "sextile", "jupiter") == (
        "aspect:jupiter:sextile:jupiter"
    )


def test_init_refuses_to_relabel_an_unsupported_future_schema(tmp_path: Path) -> None:
    database = tmp_path / "future.db"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version = 3")

    with InterpretationStore(database) as store:
        with pytest.raises(StoreNotInitializedError, match="refusing to overwrite"):
            store.initialize()

    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3


def test_init_refuses_version_metadata_disagreement(tmp_path: Path) -> None:
    database = tmp_path / "mismatch.db"
    with InterpretationStore(database) as store:
        store.initialize()
        connection = store._require_schema()
        connection.execute(
            "UPDATE interpretation_meta SET value = '999' WHERE key = 'schema_version'"
        )
        connection.commit()

    with InterpretationStore(database) as store:
        with pytest.raises(StoreNotInitializedError, match="metadata disagrees"):
            store.initialize()


def test_reads_reject_a_version_marker_on_an_incomplete_schema(tmp_path: Path) -> None:
    database = tmp_path / "corrupt.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE interpretation_entries(id TEXT PRIMARY KEY)")
        connection.execute("PRAGMA user_version = 2")

    with InterpretationStore(database) as store:
        with pytest.raises(StoreNotInitializedError, match="required tables are missing"):
            store.get("sign:aries")


@pytest.mark.parametrize("invalid_house", [1.0, True, "1"])
def test_house_selectors_require_real_integers(invalid_house: object) -> None:
    with pytest.raises(ValueError, match="invalid house"):
        InterpretationEntry(
            id=f"house:{invalid_house}",
            type="house",
            title="Bad house",
            keywords=("invalid",),
            summary="This malformed record must not enter SQLite.",
            house=invalid_house,  # type: ignore[arg-type]
        )


def test_optional_text_fields_are_type_stable_for_sqlite_roundtrips() -> None:
    with pytest.raises(ValueError, match="body must be a string"):
        InterpretationEntry(
            id="sign:aries",
            type="sign",
            title="Aries",
            keywords=("initiative",),
            summary="A valid-looking record with malformed optional text.",
            sign="aries",
            body=5,  # type: ignore[arg-type]
        )


def test_seed_schema_version_rejects_json_boolean(tmp_path: Path) -> None:
    seed = tmp_path / "bad-version.json"
    seed.write_text(
        json.dumps({"schema_version": True, "records": []}), encoding="utf-8"
    )
    with InterpretationStore(tmp_path / "store.db") as store:
        store.initialize()
        with pytest.raises(SeedImportError, match="schema_version"):
            store.import_path(seed)
