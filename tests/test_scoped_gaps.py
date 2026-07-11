from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("swisseph")

from sidereal.cli import build_parser, main
from sidereal.interpret.audit import report_interpretation_ids


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _seed_database(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["db", "init", "--db", str(path)]) == 0
    capsys.readouterr()
    assert main(
        [
            "db",
            "import",
            str(PROJECT_ROOT / "data" / "seeds"),
            "--db",
            str(path),
        ]
    ) == 0
    capsys.readouterr()


def test_report_interpretation_ids_walks_nested_readings_only() -> None:
    report = {
        "chart": {"points": [{"id": "sun"}]},
        "interpretation": {
            "planets": [
                {
                    "readings": [
                        {"id": "planet:sun", "status": "ready"},
                        {"id": "planet_in_sign:jupiter:aries", "status": "stub"},
                    ]
                }
            ]
        },
        "gaps": [{"key": "planet_in_sign:jupiter:aries", "kind": "stub"}],
    }

    assert report_interpretation_ids(report) == (
        "planet:sun",
        "planet_in_sign:jupiter:aries",
    )
    with pytest.raises(ValueError, match="no interpretation readings"):
        report_interpretation_ids({"chart": {"points": [{"id": "sun"}]}})


def test_db_gaps_can_scope_to_report_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "sidereal.db"
    _seed_database(database, capsys)
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "interpretation": {
                    "readings": [
                        {"id": "planet:sun", "status": "ready"},
                        {
                            "id": "aspect:neptune:square:uranus",
                            "status": "stub",
                        },
                        {"id": "planet_in_sign:chiron:aries", "status": "missing"},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    assert main(
        [
            "db",
            "gaps",
            "--db",
            str(database),
            "--chart",
            str(report_path),
        ]
    ) == 0
    audit = json.loads(capsys.readouterr().out)
    assert (audit["expected"], audit["ready"], audit["stub"], audit["missing"]) == (
        3,
        1,
        1,
        1,
    )
    assert audit["ready_ids"] == ["planet:sun"]
    assert audit["stub_ids"] == ["aspect:neptune:square:uranus"]
    assert audit["missing_ids"] == ["planet_in_sign:chiron:aries"]


def test_db_gaps_can_scope_to_saved_chart_label(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "sidereal.db"
    charts_dir = tmp_path / "charts"
    _seed_database(database, capsys)
    assert main(
        [
            "save",
            "--label",
            "Scoped",
            "--date",
            "2000-12-12",
            "--time",
            "12:00",
            "--tz",
            "UTC",
            "--lat",
            "0",
            "--lon",
            "0",
            "--charts-dir",
            str(charts_dir),
        ]
    ) == 0
    capsys.readouterr()

    assert main(
        [
            "db",
            "gaps",
            "--db",
            str(database),
            "--chart-id",
            "Scoped",
            "--charts-dir",
            str(charts_dir),
        ]
    ) == 0
    audit = json.loads(capsys.readouterr().out)
    assert 0 < audit["expected"] < 967
    assert audit["ready"] + audit["stub"] == audit["expected"]
    assert audit["missing"] == 0
    assert audit["stub"] > 0


def test_db_gaps_rejects_two_chart_scopes() -> None:
    with pytest.raises(SystemExit) as raised:
        build_parser().parse_args(
            [
                "db",
                "gaps",
                "--chart",
                "report.json",
                "--chart-id",
                "Saved",
            ]
        )
    assert raised.value.code == 2
