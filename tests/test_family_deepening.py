from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re

from sidereal.interpret.schema import (
    SEED_SCHEMA_VERSION,
    InterpretationEntry,
    expected_entry_ids,
)
from sidereal.interpret.store import InterpretationStore
from sidereal.zodiac.midpoint import EXPECTED_SIGN_IDS


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEED_DIRECTORY = PROJECT_ROOT / "data" / "seeds"
FAMILY_SEEDS = (
    SEED_DIRECTORY / "seed_11_family_placements_v1.json",
    SEED_DIRECTORY / "seed_12_family_tight_aspects_v1.json",
)


def _payload(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_family_v7_waves_are_complete_reusable_and_nonfatalistic() -> None:
    expected_inventory = set(expected_entry_ids())
    placement_payload = _payload(FAMILY_SEEDS[0])
    aspect_payload = _payload(FAMILY_SEEDS[1])
    placement_records = placement_payload["records"]
    aspect_records = aspect_payload["records"]

    assert placement_payload["schema_version"] == SEED_SCHEMA_VERSION == 1
    assert aspect_payload["schema_version"] == SEED_SCHEMA_VERSION
    assert placement_payload["seed_id"] == "seed_11_family_placements_v1"
    assert aspect_payload["seed_id"] == "seed_12_family_tight_aspects_v1"
    assert len(placement_records) == 101
    assert len(aspect_records) == 57
    assert Counter(record["type"] for record in placement_records) == {
        "angle_in_sign": 5,
        "planet_in_sign": 35,
        "planet_in_house": 34,
        "sign_on_house": 27,
    }
    assert Counter(record["type"] for record in aspect_records) == {"aspect": 57}

    records = [*placement_records, *aspect_records]
    entries = [InterpretationEntry.from_dict(record) for record in records]
    ids = [entry.id for entry in entries]
    assert len(ids) == len(set(ids)) == 158
    assert set(ids) <= expected_inventory
    assert all(entry.status == "ready" for entry in entries)
    assert all(entry.source == "original" for entry in entries)
    assert all(entry.version >= 7 for entry in entries)
    assert all(len(entry.summary) >= 120 for entry in entries)
    assert all(entry.growth.strip() for entry in entries)
    assert "planet_in_sign:jupiter:ophiuchus" in ids
    assert "sign_on_house:ophiuchus:3" in ids
    assert "aspect:jupiter:trine:mercury" in ids

    assert not any(
        entry.type == "aspect"
        and entry.body_a == entry.body_b
        and entry.body_a in {"asc", "mc"}
        for entry in entries
    )
    private_name = re.compile(r"\b(?:bobby|mom|dad)\b", re.IGNORECASE)
    assert not any(
        private_name.search(" ".join((entry.title, entry.summary, entry.growth)))
        for entry in entries
    )

    sign_word = re.compile(
        r"\b(?:" + "|".join(re.escape(sign) for sign in EXPECTED_SIGN_IDS) + r")\b",
        re.IGNORECASE,
    )
    assert not any(
        sign_word.search(" ".join((entry.title, entry.summary, entry.growth)))
        for entry in entries
        if entry.type == "aspect"
    )


def test_full_seed_import_applies_family_versions_without_inventory_gaps(
    tmp_path: Path,
) -> None:
    with InterpretationStore(tmp_path / "family.db") as store:
        store.initialize()
        result = store.import_path(SEED_DIRECTORY)
        audit = store.audit()
        placement = store.get("planet_in_sign:jupiter:ophiuchus")
        shared_aspect = store.get("aspect:jupiter:trine:mercury")

    assert result.files == 13
    assert result.records == 2192
    assert result.inserted == 967
    assert result.updated == 963
    assert result.unchanged == 0
    assert result.skipped == 262
    assert (audit.expected, audit.ready, audit.stub, audit.missing) == (
        967,
        897,
        70,
        0,
    )
    assert placement is not None and placement.version >= 7
    assert shared_aspect is not None and shared_aspect.version >= 7
