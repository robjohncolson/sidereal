from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("swisseph")

from sidereal.cli import main


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_save_list_show_and_interpret_round_trip(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    charts_dir = tmp_path / "charts"
    database = tmp_path / "sidereal.db"
    assert main(["db", "init", "--db", str(database)]) == 0
    capsys.readouterr()
    assert main(
        [
            "db",
            "import",
            str(PROJECT_ROOT / "data" / "seeds"),
            "--db",
            str(database),
        ]
    ) == 0
    capsys.readouterr()

    assert main(
        [
            "save",
            "--label",
            "J2000 Comparison",
            "--date",
            "2000-01-01",
            "--time",
            "12:00",
            "--tz",
            "UTC",
            "--lat",
            "0",
            "--lon",
            "0",
            "--compare",
            "tropical",
            "--charts-dir",
            str(charts_dir),
        ]
    ) == 0
    saved = json.loads(capsys.readouterr().out)
    assert saved["label"] == "J2000 Comparison"
    assert saved["systems"] == ["midpoint_v1", "tropical"]
    assert list(charts_dir.glob("*.json")) == [charts_dir / f"{saved['id']}.json"]

    assert main(["list", "--charts-dir", str(charts_dir)]) == 0
    listing = capsys.readouterr().out
    assert "ID\tLABEL\tLOCAL DATETIME\tTZ\tSYSTEMS" in listing
    assert saved["id"] in listing
    assert "J2000 Comparison" in listing
    assert "midpoint_v1,tropical" in listing

    assert main(["show", "J2000 Comparison", "--charts-dir", str(charts_dir)]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["id"] == saved["id"]
    assert shown["chart"]["meta"]["input"]["label"] == "J2000 Comparison"
    assert shown["chart"]["points"][0]["id"] == "sun"

    markdown = tmp_path / "saved.md"
    assert main(
        [
            "show",
            saved["id"],
            "--charts-dir",
            str(charts_dir),
            "--md",
            str(markdown),
        ]
    ) == 0
    assert "# Saved chart: J2000 Comparison" in markdown.read_text(encoding="utf-8")

    report_path = tmp_path / "interpreted.json"
    assert main(
        [
            "interpret",
            saved["id"],
            "--charts-dir",
            str(charts_dir),
            "--db",
            str(database),
            "--out",
            str(report_path),
        ]
    ) == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["comparison"]["systems"] == ["midpoint_v1", "tropical"]
    assert report["interpretation"]["planets"][0]["readings"][-1]["status"] == "ready"
    refreshed = json.loads((charts_dir / f"{saved['id']}.json").read_text(encoding="utf-8"))
    assert refreshed["last_report_path"] == str(report_path)
