from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

import pytest

from sidereal.interpret.generate_seeds import rendered_seed_files
from sidereal.interpret.schema import (
    ASPECT_TYPES,
    SEED_SCHEMA_VERSION,
    SELF_ASPECT_BODIES,
    SEED6_READY_BODIES,
    SEED6_READY_COUNT,
    TOTAL_INVENTORY_COUNT,
    InterpretationEntry,
    aspect_key,
    expected_entry_ids,
    generate_seed0_entries,
    generate_seed1_entries,
    generate_seed2_entries,
    generate_seed3_entries,
    generate_seed4_entries,
    generate_seed5_entries,
    generate_seed6_entries,
    generate_seed7_entries,
)
from sidereal.interpret.store import (
    DATABASE_SCHEMA_VERSION,
    InterpretationStore,
    StoreNotInitializedError,
)


SEED_DIRECTORY = Path(__file__).resolve().parents[1] / "data" / "seeds"
STABLE_SEED_SHA256 = {
    "seed_1_core_v1.json": "e62ec89035d1ee00a0ee46325bbc67ea31b7a1346177bd70a6d3752936bcd328",
    "seed_2_personal_aspects_v1.json": "d5ac256182e823072fd3c920472c2729aced6d605b142c7a14339de3af2f1d8b",
    "seed_3_placements_v1.json": "27c9b76853a6f7f49cd5b8b68da1f8a7da1a0329b5db079cf214d8f4ea608dc8",
    "seed_4_placements_v1.json": "ccc3b058b22894476f9d5364ff33626f66a7e11d0f93402ff91bab84213823cf",
    "seed_5_relationships_v1.json": "8590eaccd72bb1116b97607e307b999e081e79f65b18fb63ccfc07338255ea7b",
    "seed_7_sign_character_v1.json": "c30c3e907c4dd6631a39ca5e5a8fed6f0146239bb74268964e5c6b6de8c5eedb",
}


_V1_SCHEMA_SQL = """
CREATE TABLE interpretation_entries (
    id TEXT PRIMARY KEY,
    entry_type TEXT NOT NULL,
    planet TEXT,
    sign TEXT,
    house INTEGER CHECK (house IS NULL OR house BETWEEN 1 AND 12),
    angle TEXT,
    body_a TEXT,
    body_b TEXT,
    aspect_type TEXT,
    pattern_type TEXT,
    title TEXT NOT NULL,
    keywords_json TEXT NOT NULL,
    summary TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    shadow TEXT NOT NULL DEFAULT '',
    growth TEXT NOT NULL DEFAULT '',
    blend_note TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL,
    license TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('stub', 'ready', 'user')),
    version INTEGER NOT NULL CHECK (version >= 1),
    updated TEXT NOT NULL,
    CHECK (body_a IS NULL OR body_b IS NULL OR body_a < body_b)
);
CREATE TABLE interpretation_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT INTO interpretation_meta(key, value) VALUES('schema_version', '1');
INSERT INTO interpretation_meta(key, value) VALUES('user_note', 'preserve me');
PRAGMA user_version = 1;
"""


def _create_v1_database(path: Path) -> InterpretationEntry:
    user_entry = InterpretationEntry(
        id="planet_in_sign:mercury:ophiuchus",
        type="planet_in_sign",
        title="My Mercury in Ophiuchus",
        keywords=("integration", "language"),
        summary="A private user-authored note that must survive the schema migration.",
        planet="mercury",
        sign="ophiuchus",
        body="Custom body text.",
        shadow="Custom shadow text.",
        growth="Custom growth text.",
        blend_note="Custom blend text.",
        source="user",
        status="user",
        version=7,
        updated="2026-07-11",
    )
    values = InterpretationStore._record_values(user_entry)
    with sqlite3.connect(path) as connection:
        connection.executescript(_V1_SCHEMA_SQL)
        connection.execute(
            "INSERT INTO interpretation_entries VALUES ("
            + ", ".join("?" for _ in values)
            + ")",
            values,
        )
    return user_entry


def _raw_self_aspect_values(body: str) -> tuple[object, ...]:
    return (
        f"aspect:{body}:square:{body}",
        "aspect",
        None,
        None,
        None,
        None,
        body,
        body,
        "square",
        None,
        f"{body.title()} Square {body.title()}",
        '["test"]',
        "Constraint probe.",
        "",
        "",
        "",
        "",
        "user",
        "personal-use",
        "user",
        1,
        "2026-07-11",
    )


def test_self_aspect_key_and_entry_validation_are_explicitly_allowlisted() -> None:
    key = "aspect:jupiter:sextile:jupiter"
    assert aspect_key("jupiter", "sextile", "jupiter") == key
    entry = InterpretationEntry(
        id=key,
        type="aspect",
        title="Jupiter Sextile Jupiter",
        keywords=("opportunity",),
        summary="A valid same-body cross-chart interpretation record.",
        body_a="jupiter",
        body_b="jupiter",
        aspect_type="sextile",
    )
    assert entry.id == key

    for body in ("asc", "mc", "south_node"):
        with pytest.raises(ValueError, match="same-body|aspect bodies"):
            aspect_key(body, "square", body)
        with pytest.raises(ValueError, match="same-body|aspect bodies"):
            InterpretationEntry(
                id=f"aspect:{body}:square:{body}",
                type="aspect",
                title="Unsupported self aspect",
                keywords=("invalid",),
                summary="This selector must be rejected by validation.",
                body_a=body,
                body_b=body,
                aspect_type="square",
            )


def test_seed0_contains_the_exact_55_self_keys_and_445_aspects() -> None:
    inventory = generate_seed0_entries()
    self_ids = {
        f"aspect:{body}:{aspect_type}:{body}"
        for body in SELF_ASPECT_BODIES
        for aspect_type in ASPECT_TYPES
    }

    assert len(self_ids) == 55
    assert self_ids <= {entry.id for entry in inventory}
    assert Counter(entry.type for entry in inventory)["aspect"] == 445
    assert len(inventory) == TOTAL_INVENTORY_COUNT == 967


def test_seed6_is_the_exact_ready_self_aspect_set() -> None:
    entries = generate_seed6_entries()
    expected = {
        f"aspect:{body}:{aspect_type}:{body}"
        for body in SEED6_READY_BODIES
        for aspect_type in ASPECT_TYPES
    }
    earlier_ids = {
        entry.id
        for generator in (
            generate_seed1_entries,
            generate_seed2_entries,
            generate_seed3_entries,
            generate_seed4_entries,
            generate_seed5_entries,
            generate_seed7_entries,
        )
        for entry in generator()
    }

    assert len(entries) == SEED6_READY_COUNT == 35
    assert {entry.id for entry in entries} == expected
    assert expected <= set(expected_entry_ids())
    assert expected.isdisjoint(earlier_ids)
    assert all(entry.status == "ready" and entry.source == "original" for entry in entries)
    assert all(entry.version == 2 for entry in entries)
    assert all(entry.growth and len(entry.summary) >= 100 for entry in entries)
    assert len({entry.summary for entry in entries}) == SEED6_READY_COUNT
    assert all("not a prediction" in entry.summary for entry in entries)


def test_seed6_artifact_is_v1_and_prior_content_seeds_are_byte_stable() -> None:
    rendered = rendered_seed_files()
    name = "seed_6_self_aspects_v1.json"

    assert rendered == rendered_seed_files()
    assert rendered[name] == (SEED_DIRECTORY / name).read_text(encoding="utf-8")
    payload = json.loads(rendered[name])
    assert payload["schema_version"] == SEED_SCHEMA_VERSION == 1
    assert payload["seed_id"] == "seed_6_self_aspects_v1"
    assert payload["records"] == [entry.to_dict() for entry in generate_seed6_entries()]
    for prior_name, digest in STABLE_SEED_SHA256.items():
        checked_in = (SEED_DIRECTORY / prior_name).read_text(encoding="utf-8")
        assert rendered[prior_name] == checked_in
        assert sha256(checked_in.encode("utf-8")).hexdigest() == digest


def test_fresh_v2_store_imports_all_v1_seed_files_without_gaps(tmp_path: Path) -> None:
    with InterpretationStore(tmp_path / "fresh.db") as store:
        store.initialize()
        connection = store._require_schema()
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2

        result = store.import_path(SEED_DIRECTORY)
        audit = store.audit()

        assert result.files == 13
        assert result.records == 2192
        assert result.inserted == 967
        assert result.updated == 963
        assert result.skipped == 262
        assert (audit.ready, audit.stub, audit.missing) == (897, 70, 0)
        assert store.get("aspect:jupiter:sextile:jupiter").status == "ready"  # type: ignore[union-attr]
        assert store.get("aspect:uranus:square:uranus").status == "stub"  # type: ignore[union-attr]


def test_v1_database_migrates_transactionally_and_preserves_user_data(
    tmp_path: Path,
) -> None:
    database = tmp_path / "v1.db"
    user_entry = _create_v1_database(database)
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE INDEX user_entry_source_idx
            ON interpretation_entries(source);
            CREATE TABLE user_entry_audit(entry_id TEXT NOT NULL);
            CREATE TRIGGER user_entry_update_audit
            AFTER UPDATE OF title ON interpretation_entries
            BEGIN
                INSERT INTO user_entry_audit(entry_id) VALUES (NEW.id);
            END;
            """
        )

    with InterpretationStore(database) as store:
        with pytest.raises(StoreNotInitializedError, match="db init.*migrate"):
            store.get(user_entry.id)
        store.initialize()
        assert store.get(user_entry.id) == user_entry

    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == (
            DATABASE_SCHEMA_VERSION
        )
        assert connection.execute(
            "SELECT value FROM interpretation_meta WHERE key = 'schema_version'"
        ).fetchone()[0] == "2"
        assert connection.execute(
            "SELECT value FROM interpretation_meta WHERE key = 'user_note'"
        ).fetchone()[0] == "preserve me"
        assert connection.execute(
            "SELECT type FROM sqlite_master WHERE name = 'user_entry_source_idx'"
        ).fetchone()[0] == "index"
        assert connection.execute(
            "SELECT type FROM sqlite_master WHERE name = 'user_entry_update_audit'"
        ).fetchone()[0] == "trigger"
        connection.execute(
            "UPDATE interpretation_entries SET title = title WHERE id = ?",
            (user_entry.id,),
        )
        assert connection.execute(
            "SELECT entry_id FROM user_entry_audit"
        ).fetchone()[0] == user_entry.id

        placeholders = ", ".join("?" for _ in _raw_self_aspect_values("jupiter"))
        connection.execute(
            f"INSERT INTO interpretation_entries VALUES ({placeholders})",
            _raw_self_aspect_values("jupiter"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                f"INSERT INTO interpretation_entries VALUES ({placeholders})",
                _raw_self_aspect_values("asc"),
            )


def test_failed_v1_rebuild_rolls_back_without_relabeling_database(
    tmp_path: Path,
) -> None:
    database = tmp_path / "invalid-v1.db"
    _create_v1_database(database)
    values = _raw_self_aspect_values("asc")
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(
            "INSERT INTO interpretation_entries VALUES ("
            + ", ".join("?" for _ in values)
            + ")",
            values,
        )

    with InterpretationStore(database) as store:
        with pytest.raises(sqlite3.IntegrityError):
            store.initialize()

    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute(
            "SELECT value FROM interpretation_meta WHERE key = 'schema_version'"
        ).fetchone()[0] == "1"
        assert connection.execute(
            "SELECT COUNT(*) FROM interpretation_entries"
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type = 'table' AND name = 'interpretation_entries_v2_migration'"
        ).fetchone()[0] == 0
