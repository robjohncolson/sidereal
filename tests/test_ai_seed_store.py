from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sidereal.interpret import EntryConflictError
from sidereal.interpret.schema import InterpretationEntry
from sidereal.interpret.store import InterpretationStore, SeedImportError


def _entry(
    *,
    title: str = "Saturn in Pisces",
    summary: str = (
        "Saturn in Pisces symbolically brings structure into contact with "
        "imagination, permeability, and the work of sustaining useful boundaries."
    ),
    status: str = "ready",
    source: str = "ai-deepseek",
    version: int = 2,
) -> InterpretationEntry:
    return InterpretationEntry(
        id="planet_in_sign:saturn:pisces",
        type="planet_in_sign",
        title=title,
        keywords=("structure", "imagination", "boundaries"),
        summary=summary,
        planet="saturn",
        sign="pisces",
        growth="Give a subtle impression a durable and accountable form.",
        source=source,
        license="personal-use",
        status=status,
        version=version,
        updated="2026-07-12",
    )


def test_ai_deepseek_is_a_valid_interpretation_source() -> None:
    assert _entry().source == "ai-deepseek"


def test_upsert_entry_inserts_only_when_expected_state_is_absent(
    tmp_path: Path,
) -> None:
    candidate = _entry()
    with InterpretationStore(tmp_path / "sidereal.db") as store:
        store.initialize()

        assert store.upsert_entry(candidate, expected=None) == candidate
        assert store.get(candidate.id) == candidate

        with pytest.raises(EntryConflictError, match="changed after it was read"):
            store.upsert_entry(replace(candidate, version=3), expected=None)
        assert store.get(candidate.id) == candidate


def test_upsert_entry_rejects_expected_record_when_row_is_missing(
    tmp_path: Path,
) -> None:
    expected = _entry(status="stub", source="generated_draft", version=1)
    candidate = _entry()
    with InterpretationStore(tmp_path / "sidereal.db") as store:
        store.initialize()

        with pytest.raises(EntryConflictError, match="changed after it was read"):
            store.upsert_entry(candidate, expected=expected)
        assert store.get(candidate.id) is None


def test_upsert_entry_uses_existing_version_rules(tmp_path: Path) -> None:
    original = _entry(
        title="Saturn in Pisces draft",
        summary="A working symbolic draft for Saturn in Pisces that remains unfinished.",
        status="stub",
        source="generated_draft",
        version=2,
    )
    lower = replace(_entry(), version=1)
    higher = replace(_entry(), version=3)
    same_version_conflict = replace(_entry(), version=2)

    with InterpretationStore(tmp_path / "sidereal.db") as store:
        store.initialize()
        store.upsert_entry(original, expected=None)

        assert store.upsert_entry(lower, expected=original) == original
        assert store.get(original.id) == original
        assert store.upsert_entry(original, expected=original) == original

        with pytest.raises(SeedImportError, match="same-version conflict"):
            store.upsert_entry(same_version_conflict, expected=original)
        assert store.get(original.id) == original

        assert store.upsert_entry(higher, expected=original) == higher
        assert store.get(original.id) == higher


def test_upsert_entry_compare_and_swap_rejects_a_stale_reader(
    tmp_path: Path,
) -> None:
    database = tmp_path / "sidereal.db"
    original = _entry(
        title="Saturn in Pisces draft",
        summary="A working symbolic draft for Saturn in Pisces that remains unfinished.",
        status="stub",
        source="generated_draft",
        version=1,
    )
    winner = _entry(version=2)
    stale_candidate = replace(
        _entry(version=3),
        title="A stale generated replacement",
    )

    with InterpretationStore(database) as first, InterpretationStore(database) as second:
        first.initialize()
        first.upsert_entry(original, expected=None)
        stale_expected = first.get(original.id)
        assert stale_expected == original

        second.initialize()
        assert second.upsert_entry(winner, expected=second.get(original.id)) == winner

        with pytest.raises(EntryConflictError, match="changed after it was read"):
            first.upsert_entry(stale_candidate, expected=stale_expected)
        assert first.get(original.id) == winner
