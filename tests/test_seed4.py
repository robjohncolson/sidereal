from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from sidereal.interpret.generate_seeds import rendered_seed_files
from sidereal.interpret.schema import (
    SEED4_HOUSE_BODIES,
    SEED4_READY_COUNT,
    SEED4_SIGN_PLANETS,
    SIGNS,
    TOTAL_INVENTORY_COUNT,
    generate_seed4_entries,
)
from sidereal.interpret.store import InterpretationStore


SEED_DIRECTORY = Path(__file__).resolve().parents[1] / "data" / "seeds"
PRIOR_SEED_NAMES = (
    "seed_0_inventory_v1.json",
    "seed_1_core_v1.json",
    "seed_2_personal_aspects_v1.json",
    "seed_3_placements_v1.json",
)


def test_seed4_is_the_exact_required_ready_set() -> None:
    entries = generate_seed4_entries()
    expected_ids = {
        f"planet_in_sign:{planet}:{sign}"
        for planet in SEED4_SIGN_PLANETS
        for sign in SIGNS
    } | {
        f"planet_in_house:{planet}:{house}"
        for planet in SEED4_HOUSE_BODIES
        for house in range(1, 13)
    }

    assert len(entries) == SEED4_READY_COUNT == 99
    assert {entry.id for entry in entries} == expected_ids
    assert Counter(entry.type for entry in entries) == {
        "planet_in_sign": 39,
        "planet_in_house": 60,
    }
    assert all(entry.status == "ready" for entry in entries)
    assert all(entry.source == "original" for entry in entries)
    assert all(entry.version >= 2 for entry in entries)
    assert all(entry.growth for entry in entries)
    assert all(len(entry.summary) >= 100 for entry in entries)
    assert all("not yet authored" not in entry.summary for entry in entries)
    assert len({entry.summary for entry in entries}) == SEED4_READY_COUNT


def test_seed4_houses_nodes_and_ophiuchus_are_first_class() -> None:
    entries = generate_seed4_entries()
    house_entries = tuple(
        entry for entry in entries if entry.type == "planet_in_house"
    )
    node_entries = tuple(
        entry
        for entry in house_entries
        if entry.planet in {"north_node", "south_node"}
    )
    ophiuchus_entries = tuple(
        entry for entry in entries if entry.sign == "ophiuchus"
    )

    assert len(house_entries) == 60
    assert all(
        "Houses are life-arena metaphors, not predictions" in entry.summary
        for entry in house_entries
    )
    assert len(node_entries) == 24
    assert all("calculated point, not a planet" in entry.summary for entry in node_entries)
    assert {entry.id for entry in ophiuchus_entries} == {
        "planet_in_sign:mercury:ophiuchus",
        "planet_in_sign:venus:ophiuchus",
        "planet_in_sign:mars:ophiuchus",
    }
    assert len({entry.summary for entry in ophiuchus_entries}) == 3
    assert all("boundary-crossing insight" in entry.summary for entry in ophiuchus_entries)
    assert all("Scorpio" not in entry.summary for entry in ophiuchus_entries)


def test_seed4_file_is_registered_without_changing_prior_seed_bytes() -> None:
    rendered = rendered_seed_files()
    name = "seed_4_placements_v1.json"

    assert rendered == rendered_seed_files()
    assert name in rendered
    payload = json.loads(rendered[name])
    assert payload["schema_version"] == 1
    assert payload["seed_id"] == "seed_4_placements_v1"
    assert payload["records"] == [
        entry.to_dict() for entry in generate_seed4_entries()
    ]
    for prior_name in PRIOR_SEED_NAMES:
        assert rendered[prior_name] == (SEED_DIRECTORY / prior_name).read_text(
            encoding="utf-8"
        )


def test_seed4_store_import_upgrades_stubs_and_is_idempotent(tmp_path: Path) -> None:
    seed_directory = tmp_path / "seeds"
    seed_directory.mkdir()
    rendered = rendered_seed_files()
    selected_names = ("seed_0_inventory_v1.json", "seed_4_placements_v1.json")
    for name in selected_names:
        (seed_directory / name).write_text(rendered[name], encoding="utf-8")

    with InterpretationStore(tmp_path / "sidereal.db") as store:
        store.initialize()
        first = store.import_path(seed_directory)
        audit = store.audit()

        assert first.files == 2
        assert first.records == TOTAL_INVENTORY_COUNT + SEED4_READY_COUNT
        assert first.inserted == TOTAL_INVENTORY_COUNT
        assert first.updated == SEED4_READY_COUNT
        assert (audit.ready, audit.stub, audit.missing) == (99, 813, 0)
        assert store.get("planet_in_sign:mercury:ophiuchus").status == "ready"  # type: ignore[union-attr]
        assert store.get("planet_in_house:north_node:12").status == "ready"  # type: ignore[union-attr]

        second = store.import_path(seed_directory)
        assert second.inserted == second.updated == 0
        assert second.unchanged == TOTAL_INVENTORY_COUNT
        assert second.skipped == SEED4_READY_COUNT
