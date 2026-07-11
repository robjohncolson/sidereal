"""Argument-validation and public CLI surface acceptance tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sidereal.cli import build_parser, main


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_parser_accepts_the_required_known_time_chart_command(tmp_path: Path) -> None:
    output = tmp_path / "chart.json"
    markdown = tmp_path / "chart.md"
    args = build_parser().parse_args(
        [
            "chart",
            "--date",
            "2000-01-01",
            "--time",
            "12:00",
            "--tz",
            "UTC",
            "--fold",
            "0",
            "--lat",
            "0",
            "--lon",
            "0",
            "--md",
            str(markdown),
            "--out",
            str(output),
        ]
    )

    assert args.command == "chart"
    assert args.local_date.isoformat() == "2000-01-01"
    assert args.local_time.isoformat() == "12:00:00"
    assert args.tz == "UTC"
    assert args.fold == 0
    assert (args.lat, args.lon) == (0.0, 0.0)
    assert args.out == output
    assert args.md == markdown


@pytest.mark.parametrize(
    "coordinates",
    [
        ["--lat", "40.0"],
        ["--lon", "-74.0"],
        ["--lat", "90", "--lon", "0"],
        ["--lat", "-90", "--lon", "0"],
        ["--lat", "0", "--lon", "180.1"],
    ],
)
def test_chart_rejects_incomplete_or_out_of_range_location(
    coordinates: list[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["chart", "--date", "2000-01-01", "--tz", "UTC", *coordinates])

    assert raised.value.code == 2


def test_chart_rejects_offset_baked_into_local_time() -> None:
    with pytest.raises(SystemExit) as raised:
        build_parser().parse_args(
            [
                "chart",
                "--date",
                "2000-01-01",
                "--time",
                "12:00+01:00",
                "--tz",
                "UTC",
            ]
        )

    assert raised.value.code == 2


@pytest.mark.parametrize("db_command", ["init", "gaps"])
def test_db_parser_accepts_commands_without_extra_required_flags(
    db_command: str,
) -> None:
    args = build_parser().parse_args(["db", db_command])
    assert args.command == "db"
    assert args.db_command == db_command
    assert args.db == Path("data/sidereal.db")


def test_db_parser_accepts_import_and_get_contracts() -> None:
    imported = build_parser().parse_args(["db", "import", "data/seeds/"])
    packaged = build_parser().parse_args(["db", "import"])
    fetched = build_parser().parse_args(
        ["db", "get", "planet_in_sign:sun:virgo"]
    )

    assert imported.source == Path("data/seeds")
    assert packaged.source is None
    assert fetched.key == "planet_in_sign:sun:virgo"


def test_no_command_prints_help_and_returns_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "chart" in capsys.readouterr().out


def test_db_cli_imports_and_audits_the_complete_seed_inventory(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "nested" / "sidereal.db"

    assert main(["db", "init", "--db", str(database)]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "db",
                "import",
                str(PROJECT_ROOT / "data/seeds"),
                "--db",
                str(database),
            ]
        )
        == 0
    )
    imported = json.loads(capsys.readouterr().out)
    assert imported["inserted"] + imported["updated"] > 0

    assert (
        main(
            [
                "db",
                "import",
                str(PROJECT_ROOT / "data/seeds"),
                "--db",
                str(database),
            ]
        )
        == 0
    )
    repeated = json.loads(capsys.readouterr().out)
    assert repeated["inserted"] == 0
    assert repeated["updated"] == 0

    assert main(["db", "gaps", "--db", str(database)]) == 0
    audit = json.loads(capsys.readouterr().out)
    assert audit["expected"] == 912
    assert audit["ready"] == 437  # Seeds 1–3: 76 + 105 + 256
    assert audit["stub"] == 475
    assert audit["missing"] == 0
    assert audit["missing_ids"] == []
    assert len(audit["ready_ids"]) == 437
    assert len(audit["stub_ids"]) == 475

    assert (
        main(
            [
                "db",
                "get",
                "planet_in_sign:sun:ophiuchus",
                "--db",
                str(database),
            ]
        )
        == 0
    )
    entry = json.loads(capsys.readouterr().out)
    assert entry["status"] == "ready"
    assert entry["sign"] == "ophiuchus"


def test_db_import_without_source_resolves_shipped_seeds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "default-seeds.db"
    assert main(["db", "init", "--db", str(database)]) == 0
    capsys.readouterr()
    assert main(["db", "import", "--db", str(database)]) == 0
    imported = json.loads(capsys.readouterr().out)
    assert imported["inserted"] == 912


def test_no_houses_preserves_supplied_location_provenance(tmp_path: Path) -> None:
    output = tmp_path / "no-houses.json"
    assert (
        main(
            [
                "chart",
                "--date",
                "2000-01-01",
                "--time",
                "12:00",
                "--tz",
                "UTC",
                "--lat",
                "40",
                "--lon",
                "-74",
                "--no-houses",
                "--out",
                str(output),
            ]
        )
        == 0
    )
    chart = json.loads(output.read_text(encoding="utf-8"))["chart"]
    assert chart["meta"]["location_known"] is True
    assert chart["meta"]["input"]["lat"] == 40.0
    assert chart["meta"]["input"]["lon"] == -74.0
    assert chart["cusps"] is None
    assert all(point["kind"] == "body" for point in chart["points"])
    assert any("disabled by configuration" in warning for warning in chart["meta"]["warnings"])
    markdown = output.with_suffix(".md")
    assert (
        main(
            [
                "chart", "--date", "2000-01-01", "--time", "12:00",
                "--tz", "UTC", "--lat", "40", "--lon", "-74",
                "--no-houses", "--md", str(markdown),
            ]
        )
        == 0
    )
    assert "disabled by configuration" in markdown.read_text(encoding="utf-8")


def test_chart_rejects_one_path_for_both_json_and_markdown(tmp_path: Path) -> None:
    output = tmp_path / "collision.out"
    with pytest.raises(SystemExit) as raised:
        main(
            [
                "chart", "--date", "2000-01-01", "--tz", "UTC",
                "--out", str(output), "--md", str(output),
            ]
        )
    assert raised.value.code == 2
    assert not output.exists()
