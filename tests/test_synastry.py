from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("swisseph")

from sidereal.cli import build_parser, main
from sidereal.interpret.generate_seeds import resolve_seed_directory
from sidereal.interpret.store import InterpretationStore


def _save_fixture(
    label: str,
    *,
    charts_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> dict[str, object]:
    assert main(
        [
            "save",
            "--label",
            label,
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
    return json.loads(capsys.readouterr().out)


def _seed_database(path: Path) -> None:
    with InterpretationStore(path) as store:
        store.initialize()
        store.import_path(resolve_seed_directory())


def test_saved_synastry_cli_preserves_roles_and_resolves_self_aspects(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    charts_dir = tmp_path / "charts"
    database = tmp_path / "sidereal.db"
    _seed_database(database)
    saved_a = _save_fixture("Chart A", charts_dir=charts_dir, capsys=capsys)
    saved_b = _save_fixture("Chart B", charts_dir=charts_dir, capsys=capsys)
    output = tmp_path / "synastry.json"
    markdown = tmp_path / "synastry.md"

    assert main(
        [
            "synastry",
            "--a",
            "Chart A",
            "--b",
            "Chart B",
            "--charts-dir",
            str(charts_dir),
            "--db",
            str(database),
            "--out",
            str(output),
            "--md",
            str(markdown),
        ]
    ) == 0

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["report_type"] == "synastry"
    assert report["chart_a"]["source"] == "saved"
    assert report["chart_a"]["id"] == saved_a["id"]
    assert report["chart_b"]["source"] == "saved"
    assert report["chart_b"]["id"] == saved_b["id"]
    assert report["epistemic_note"]
    assert all(item["aspect"]["applying"] is None for item in report["relationships"])

    sun_self = next(
        item
        for item in report["relationships"]
        if item["aspect"]["a_point"] == "sun"
        and item["aspect"]["b_point"] == "sun"
        and item["aspect"]["aspect_id"] == "conjunction"
    )
    assert sun_self["same_body"] is True
    assert sun_self["reading"]["id"] == "aspect:sun:conjunction:sun"
    assert sun_self["reading"]["status"] == "ready"
    assert not any(
        gap["key"] == "aspect:sun:conjunction:sun" for gap in report["gaps"]
    )
    angle_self = next(
        item
        for item in report["relationships"]
        if item["aspect"]["a_point"] == "asc"
        and item["aspect"]["b_point"] == "asc"
    )
    assert angle_self["reading"]["status"] == "not_applicable"
    assert not any(
        gap["key"] == "aspect:asc:conjunction:asc" for gap in report["gaps"]
    )

    text = markdown.read_text(encoding="utf-8")
    assert "# Two-natal synastry: Chart A ↔ Chart B" in text
    assert "Same-body contacts" in text
    assert "two fixed" in text.lower()
    assert "compatibility scores" in text


def test_inline_synastry_cli_supports_unknown_time_without_angles(
    tmp_path: Path,
) -> None:
    output = tmp_path / "inline.json"
    assert main(
        [
            "synastry",
            "--a-date",
            "2000-12-12",
            "--a-tz",
            "UTC",
            "--a-label",
            "Unknown A",
            "--b-date",
            "2000-12-12",
            "--b-time",
            "12:00",
            "--b-tz",
            "UTC",
            "--b-lat",
            "0",
            "--b-lon",
            "0",
            "--b-label",
            "Known B",
            "--db",
            str(tmp_path / "absent.db"),
            "--out",
            str(output),
        ]
    ) == 0
    report = json.loads(output.read_text(encoding="utf-8"))

    assert report["chart_a"]["time_known"] is False
    assert report["chart_b"]["time_known"] is True
    assert all(
        item["aspect"]["a_point"] not in {"asc", "mc"}
        for item in report["relationships"]
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ["synastry", "--a", "A", "--b", "B", "--a-label", "invalid"],
        ["synastry", "--a-date", "2000-01-01", "--b", "B"],
        [
            "synastry",
            "--a-date",
            "2000-01-01",
            "--a-tz",
            "UTC",
            "--a-lat",
            "0",
            "--b-date",
            "2000-01-01",
            "--b-tz",
            "UTC",
        ],
    ],
)
def test_synastry_cli_rejects_mixed_or_incomplete_sources(
    arguments: list[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(arguments)
    assert raised.value.code == 2


def test_synastry_parser_requires_both_chart_sources() -> None:
    with pytest.raises(SystemExit) as raised:
        build_parser().parse_args(["synastry", "--a", "A"])
    assert raised.value.code == 2


def test_web_synastry_supports_saved_and_inline_sources(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from sidereal.web import create_app

    database = tmp_path / "sidereal.db"
    charts_dir = tmp_path / "charts"
    _seed_database(database)
    app = create_app(db_path=database, charts_dir=charts_dir)
    client = TestClient(app)
    saved_a = client.post(
        "/api/charts",
        json={
            "moment": {
                "date": "2000-12-12",
                "time": "12:00",
                "tz": "UTC",
                "lat": 0,
                "lon": 0,
                "label": "API A",
            }
        },
    ).json()

    response = client.post(
        "/api/synastry",
        json={
            "a_id": saved_a["id"],
            "b": {
                "date": "2000-12-12",
                "time": "12:00",
                "tz": "UTC",
                "lat": 0,
                "lon": 0,
                "label": "API B",
            },
        },
    )
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["report_type"] == "synastry"
    assert report["chart_a"]["source"] == "saved"
    assert report["chart_b"]["source"] == "inline"
    assert any(item["same_body"] for item in report["relationships"])

    invalid = client.post(
        "/api/synastry",
        json={"a_id": saved_a["id"], "a": {}, "b_id": saved_a["id"]},
    )
    assert invalid.status_code == 400
    assert "exactly one" in invalid.json()["detail"]
