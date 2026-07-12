"""Parser contract for the shared AI interpretation seed commands."""

from __future__ import annotations

from pathlib import Path

import pytest

from sidereal.cli import build_parser


ENTRY_ID = "planet_in_sign:mars:aries"


def test_ai_seed_dry_run_requires_only_an_interpretation_id() -> None:
    args = build_parser().parse_args(
        ["ai-seed", "dry-run", "--id", ENTRY_ID]
    )

    assert args.command == "ai-seed"
    assert args.ai_seed_command == "dry-run"
    assert args.entry_id == ENTRY_ID
    assert not hasattr(args, "db")


def test_ai_seed_fill_and_fill_gaps_accept_database_contracts(
    tmp_path: Path,
) -> None:
    database = tmp_path / "interpretations.db"

    fill = build_parser().parse_args(
        ["ai-seed", "fill", "--id", ENTRY_ID, "--db", str(database)]
    )
    fill_gaps = build_parser().parse_args(
        ["ai-seed", "fill-gaps", "--limit", "7", "--db", str(database)]
    )

    assert fill.command == "ai-seed"
    assert fill.ai_seed_command == "fill"
    assert fill.entry_id == ENTRY_ID
    assert fill.db == database
    assert fill_gaps.command == "ai-seed"
    assert fill_gaps.ai_seed_command == "fill-gaps"
    assert fill_gaps.limit == 7
    assert fill_gaps.db == database


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "many"])
def test_ai_seed_fill_gaps_requires_a_positive_integer_limit(value: str) -> None:
    with pytest.raises(SystemExit) as raised:
        build_parser().parse_args(
            ["ai-seed", "fill-gaps", "--limit", value]
        )

    assert raised.value.code == 2


@pytest.mark.parametrize("subcommand", ["dry-run", "fill"])
def test_ai_seed_single_entry_commands_require_id(subcommand: str) -> None:
    with pytest.raises(SystemExit) as raised:
        build_parser().parse_args(["ai-seed", subcommand])

    assert raised.value.code == 2


def test_sidereal_db_is_the_preferred_cli_database_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIDEREAL_DB", "canonical.db")
    monkeypatch.setenv("SIDEREAL_DB_PATH", "legacy.db")

    args = build_parser().parse_args(
        ["ai-seed", "fill", "--id", ENTRY_ID]
    )

    assert args.db == Path("canonical.db")


def test_legacy_database_default_remains_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SIDEREAL_DB", raising=False)
    monkeypatch.setenv("SIDEREAL_DB_PATH", "legacy.db")

    args = build_parser().parse_args(
        ["ai-seed", "fill-gaps", "--limit", "1"]
    )

    assert args.db == Path("legacy.db")
