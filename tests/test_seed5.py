from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from sidereal.interpret.generate_seeds import rendered_seed_files, write_seed_files
from sidereal.interpret.schema import (
    ASPECT_TYPES,
    SEED1_READY_COUNT,
    SEED2_READY_COUNT,
    SEED3_READY_COUNT,
    SEED4_READY_COUNT,
    SEED5_ANGLES,
    SEED5_OUTER_NODE_BODIES,
    SEED5_PERSONAL_BODIES,
    SEED5_READY_COUNT,
    TOTAL_INVENTORY_COUNT,
    aspect_key,
    expected_entry_ids,
    generate_seed2_entries,
    generate_seed4_entries,
    generate_seed5_entries,
)
from sidereal.interpret.store import InterpretationStore


SEED_DIRECTORY = Path(__file__).resolve().parents[1] / "data" / "seeds"
PRIOR_SEED_SHA256 = {
    "seed_1_core_v1.json": "e62ec89035d1ee00a0ee46325bbc67ea31b7a1346177bd70a6d3752936bcd328",
    "seed_2_personal_aspects_v1.json": "d5ac256182e823072fd3c920472c2729aced6d605b142c7a14339de3af2f1d8b",
    "seed_3_placements_v1.json": "27c9b76853a6f7f49cd5b8b68da1f8a7da1a0329b5db079cf214d8f4ea608dc8",
    "seed_4_placements_v1.json": "ccc3b058b22894476f9d5364ff33626f66a7e11d0f93402ff91bab84213823cf",
}


def test_seed5_is_the_exact_required_ready_set() -> None:
    entries = generate_seed5_entries()
    expected_outer_ids = {
        aspect_key(personal, aspect_type, counterpart)
        for personal in SEED5_PERSONAL_BODIES
        for counterpart in SEED5_OUTER_NODE_BODIES
        for aspect_type in ASPECT_TYPES
    }
    expected_angle_ids = {
        aspect_key(personal, aspect_type, angle)
        for personal in SEED5_PERSONAL_BODIES
        for angle in SEED5_ANGLES
        for aspect_type in ASPECT_TYPES
    }

    assert len(entries) == SEED5_READY_COUNT == 210
    assert {entry.id for entry in entries} == expected_outer_ids | expected_angle_ids
    assert len(expected_outer_ids) == 140
    assert len(expected_angle_ids) == 70
    assert Counter(entry.type for entry in entries) == {"aspect": 210}
    assert all(entry.status == "ready" for entry in entries)
    assert all(entry.source == "original" for entry in entries)
    assert all(entry.version >= 2 for entry in entries)
    assert all(entry.growth for entry in entries)
    assert all(len(entry.summary) >= 100 for entry in entries)
    assert all(entry.summary.count(".") <= 3 for entry in entries)
    assert all("not yet authored" not in entry.summary for entry in entries)
    assert len({entry.summary for entry in entries}) == SEED5_READY_COUNT


def test_seed5_is_canonical_in_inventory_and_disjoint_from_earlier_content() -> None:
    seed5_ids = {entry.id for entry in generate_seed5_entries()}
    seed2_ids = {entry.id for entry in generate_seed2_entries()}
    seed4_ids = {entry.id for entry in generate_seed4_entries()}

    assert seed5_ids <= set(expected_entry_ids())
    assert seed5_ids.isdisjoint(seed2_ids)
    assert seed5_ids.isdisjoint(seed4_ids)
    assert all(
        entry.body_a is not None
        and entry.body_b is not None
        and entry.body_a < entry.body_b
        and entry.id == aspect_key(entry.body_a, entry.aspect_type or "", entry.body_b)
        for entry in generate_seed5_entries()
    )


def test_seed5_nodes_and_angles_keep_required_qualifications() -> None:
    entries = generate_seed5_entries()
    node_entries = tuple(
        entry
        for entry in entries
        if "north_node" in {entry.body_a, entry.body_b}
    )
    angle_entries = tuple(
        entry
        for entry in entries
        if {entry.body_a, entry.body_b} & set(SEED5_ANGLES)
    )

    assert len(node_entries) == 35
    assert all(
        "calculated point, not a planet or a destiny signal" in entry.summary
        for entry in node_entries
    )
    assert len(angle_entries) == 70
    assert all(
        "only when known birth-time geometry supplies" in entry.summary
        for entry in angle_entries
    )
    assert all("prediction of events or outcomes" in entry.summary for entry in entries)


def test_seed5_file_is_deterministic_and_prior_seed_bytes_are_unchanged() -> None:
    rendered = rendered_seed_files()
    name = "seed_5_relationships_v1.json"

    assert rendered == rendered_seed_files()
    assert name in rendered
    payload = json.loads(rendered[name])
    assert payload["schema_version"] == 1
    assert payload["seed_id"] == "seed_5_relationships_v1"
    assert payload["records"] == [
        entry.to_dict() for entry in generate_seed5_entries()
    ]
    assert rendered[name] == (SEED_DIRECTORY / name).read_text(encoding="utf-8")

    for prior_name, expected_digest in PRIOR_SEED_SHA256.items():
        checked_in = (SEED_DIRECTORY / prior_name).read_text(encoding="utf-8")
        assert rendered[prior_name] == checked_in
        assert sha256(checked_in.encode("utf-8")).hexdigest() == expected_digest


def test_seed5_store_import_upgrades_only_its_stubs_and_is_idempotent(
    tmp_path: Path,
) -> None:
    seed_directory = tmp_path / "seeds"
    seed_directory.mkdir()
    rendered = rendered_seed_files()
    selected_names = (
        "seed_0_inventory_v1.json",
        "seed_5_relationships_v1.json",
    )
    for name in selected_names:
        (seed_directory / name).write_text(rendered[name], encoding="utf-8")

    with InterpretationStore(tmp_path / "seed5.db") as store:
        store.initialize()
        first = store.import_path(seed_directory)
        audit = store.audit()

        assert first.files == 2
        assert first.records == TOTAL_INVENTORY_COUNT + SEED5_READY_COUNT
        assert first.inserted == TOTAL_INVENTORY_COUNT
        assert first.updated == SEED5_READY_COUNT
        assert (audit.ready, audit.stub, audit.missing) == (210, 757, 0)
        assert store.get("aspect:mercury:square:uranus").status == "ready"  # type: ignore[union-attr]
        assert store.get("aspect:asc:trine:sun").status == "ready"  # type: ignore[union-attr]

        second = store.import_path(seed_directory)
        assert second.inserted == second.updated == 0
        assert second.unchanged == TOTAL_INVENTORY_COUNT
        assert second.skipped == SEED5_READY_COUNT


def test_all_required_content_seeds_reach_the_phase4_inventory_target(
    tmp_path: Path,
) -> None:
    seed_directory = tmp_path / "all-seeds"
    write_seed_files(seed_directory)
    from sidereal.interpret.schema import SEED7_READY_COUNT
    from sidereal.interpret.schema import SEED6_READY_COUNT

    ready_total = (
        SEED1_READY_COUNT
        + SEED2_READY_COUNT
        + SEED3_READY_COUNT
        + SEED4_READY_COUNT
        + SEED5_READY_COUNT
        + SEED6_READY_COUNT
        + SEED7_READY_COUNT
    )

    with InterpretationStore(tmp_path / "all-seeds.db") as store:
        store.initialize()
        first = store.import_path(seed_directory)
        audit = store.audit()

        assert ready_total == 872
        assert first.files == 8
        assert first.records == TOTAL_INVENTORY_COUNT + ready_total
        assert first.inserted == TOTAL_INVENTORY_COUNT
        assert first.updated == ready_total
        assert (audit.ready, audit.stub, audit.missing) == (872, 95, 0)
