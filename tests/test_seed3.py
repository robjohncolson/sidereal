from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from sidereal.interpret.generate_seeds import rendered_seed_files
from sidereal.interpret.schema import (
    PATTERN_TYPES,
    SEED1_READY_COUNT,
    SEED2_READY_COUNT,
    SEED3_PERSONAL_PLANETS,
    SEED3_READY_COUNT,
    SIGNS,
    TOTAL_INVENTORY_COUNT,
    generate_seed3_entries,
)
from sidereal.interpret.store import InterpretationStore


def test_seed3_is_the_exact_required_ready_set() -> None:
    entries = generate_seed3_entries()
    entry_ids = {entry.id for entry in entries}
    expected_ids = {
        *(
            f"planet_in_house:{planet}:{house}"
            for planet in SEED3_PERSONAL_PLANETS
            for house in range(1, 13)
        ),
        *(
            f"sign_on_house:{sign}:{house}"
            for sign in SIGNS
            for house in range(1, 13)
        ),
        *(f"angle_in_sign:mc:{sign}" for sign in SIGNS),
        *(f"pattern:{pattern_type}" for pattern_type in PATTERN_TYPES),
    }

    assert len(entries) == SEED3_READY_COUNT == 256
    assert entry_ids == expected_ids
    assert Counter(entry.type for entry in entries) == {
        "planet_in_house": 84,
        "sign_on_house": 156,
        "angle_in_sign": 13,
        "pattern": 3,
    }
    assert all(entry.status == "ready" for entry in entries)
    assert all(entry.source == "original" for entry in entries)
    assert all(entry.version == 2 for entry in entries)
    assert all(entry.growth for entry in entries)
    assert all(len(entry.summary) >= 100 for entry in entries)
    assert all("not yet authored" not in entry.summary for entry in entries)


def test_seed3_house_text_is_explicit_and_ophiuchus_is_first_class() -> None:
    entries = generate_seed3_entries()
    planet_houses = tuple(
        entry for entry in entries if entry.type == "planet_in_house"
    )
    sign_houses = tuple(entry for entry in entries if entry.type == "sign_on_house")

    assert all("life-arena metaphors, not predictions" in entry.summary for entry in planet_houses)
    assert all("life-arena metaphors" in entry.summary for entry in sign_houses)
    assert {
        entry.id for entry in sign_houses if entry.sign == "ophiuchus"
    } == {f"sign_on_house:ophiuchus:{house}" for house in range(1, 13)}

    ophiuchus_mc = next(
        entry for entry in entries if entry.id == "angle_in_sign:mc:ophiuchus"
    )
    assert "boundary-crossing insight" in ophiuchus_mc.summary
    assert "promise about career" in ophiuchus_mc.summary
    assert all(
        "structural" in entry.summary
        for entry in entries
        if entry.type == "pattern"
    )


def test_seed3_file_is_registered_with_deterministic_payload() -> None:
    rendered = rendered_seed_files()
    name = "seed_3_placements_v1.json"

    assert name in rendered
    assert rendered == rendered_seed_files()
    payload = json.loads(rendered[name])
    assert payload["schema_version"] == 1
    assert payload["seed_id"] == "seed_3_placements_v1"
    assert payload["records"] == [
        entry.to_dict() for entry in generate_seed3_entries()
    ]


def test_seed3_store_import_upgrades_stubs_and_is_idempotent(tmp_path: Path) -> None:
    seed_directory = tmp_path / "seeds"
    seed_directory.mkdir()
    rendered = rendered_seed_files()
    for name in (
        "seed_0_inventory_v1.json",
        "seed_1_core_v1.json",
        "seed_2_personal_aspects_v1.json",
        "seed_3_placements_v1.json",
    ):
        (seed_directory / name).write_text(rendered[name], encoding="utf-8")
    ready_total = SEED1_READY_COUNT + SEED2_READY_COUNT + SEED3_READY_COUNT

    with InterpretationStore(tmp_path / "sidereal.db") as store:
        store.initialize()
        first = store.import_path(seed_directory)
        audit = store.audit()

        assert first.files == 4
        assert first.records == TOTAL_INVENTORY_COUNT + ready_total
        assert first.inserted == TOTAL_INVENTORY_COUNT
        assert first.updated == ready_total
        assert (audit.ready, audit.stub, audit.missing) == (437, 475, 0)
        assert store.get("planet_in_house:sun:1").status == "ready"  # type: ignore[union-attr]
        assert store.get("sign_on_house:ophiuchus:12").status == "ready"  # type: ignore[union-attr]
        assert store.get("angle_in_sign:mc:aries").status == "ready"  # type: ignore[union-attr]
        assert store.get("pattern:t_square").status == "ready"  # type: ignore[union-attr]

        second = store.import_path(seed_directory)
        assert second.inserted == second.updated == 0
        assert second.unchanged == TOTAL_INVENTORY_COUNT
        assert second.skipped == ready_total
