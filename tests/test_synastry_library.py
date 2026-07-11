from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from sidereal.interpret.generate_seeds import resolve_seed_directory
from sidereal.interpret.store import InterpretationStore
from sidereal.library import ChartLibraryError
from sidereal.synastry_library import (
    list_synastries,
    load_synastry,
    save_synastry_snapshot,
)


def _minimal_report(*, marker: str = "initial") -> dict[str, object]:
    return {
        "report_version": 1,
        "report_type": "synastry",
        "chart_a": {"label": "Chart A", "source": "saved", "id": "chart-a"},
        "chart_b": {"label": "Chart B", "source": "saved", "id": "chart-b"},
        "relationships": [{"marker": marker}],
        "gaps": [],
        "warnings": [],
    }


def _seed_database(path: Path) -> None:
    with InterpretationStore(path) as store:
        store.initialize()
        store.import_path(resolve_seed_directory())


def test_synastry_snapshot_library_round_trip_and_safe_overwrite(
    tmp_path: Path,
) -> None:
    charts_dir = tmp_path / "charts"
    saved = save_synastry_snapshot(
        _minimal_report(),
        label="Chart A ↔ Chart B",
        charts_dir=charts_dir,
        snapshot_id="pair-one",
        chart_a_id="chart-a",
        chart_b_id="chart-b",
    )

    assert saved.source_path == charts_dir / "synastry" / "pair-one.json"
    assert saved.source_path.is_file()
    assert [item.id for item in list_synastries(charts_dir)] == ["pair-one"]
    loaded = load_synastry("Chart A ↔ Chart B", charts_dir)
    assert loaded.id == "pair-one"
    assert loaded.chart_a_id == "chart-a"
    assert loaded.chart_b_id == "chart-b"
    assert loaded.summary_dict()["relationship_count"] == 1

    updated = save_synastry_snapshot(
        _minimal_report(marker="updated"),
        label=loaded.label,
        charts_dir=charts_dir,
        snapshot_id=loaded.id,
        chart_a_id=loaded.chart_a_id,
        chart_b_id=loaded.chart_b_id,
        overwrite=True,
    )
    assert updated.id == saved.id
    assert load_synastry("pair-one", charts_dir).report["relationships"] == [
        {"marker": "updated"}
    ]


@pytest.mark.parametrize(
    "snapshot_id",
    (
        "../escape",
        "nested/value",
        "..",
        "moon☉",
        "Pair-One",
        "con",
        "COM1",
        "x" * 97,
    ),
)
def test_synastry_snapshot_id_cannot_escape_private_library(
    tmp_path: Path,
    snapshot_id: str,
) -> None:
    charts_dir = tmp_path / "charts"
    with pytest.raises(ChartLibraryError, match="snapshot id"):
        save_synastry_snapshot(
            _minimal_report(),
            label="Safe label",
            charts_dir=charts_dir,
            snapshot_id=snapshot_id,
        )
    assert not (tmp_path / "escape.json").exists()


def test_synastry_snapshot_loader_rejects_unsafe_embedded_id(tmp_path: Path) -> None:
    directory = tmp_path / "charts" / "synastry"
    directory.mkdir(parents=True)
    payload = {
        "schema_version": 1,
        "type": "synastry_snapshot",
        "id": "../escape",
        "label": "Invalid local record",
        "report": _minimal_report(),
    }
    (directory / "invalid.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    with pytest.raises(ChartLibraryError, match="snapshot id"):
        list_synastries(tmp_path / "charts")


def test_snapshot_collisions_are_unique_or_require_explicit_refresh(
    tmp_path: Path,
) -> None:
    charts_dir = tmp_path / "charts"
    with pytest.raises(ChartLibraryError, match="reserved filename"):
        save_synastry_snapshot(
            _minimal_report(),
            label="CON",
            charts_dir=charts_dir,
        )
    first = save_synastry_snapshot(
        _minimal_report(),
        label="Repeated label",
        charts_dir=charts_dir,
        chart_a_id="chart-a",
        chart_b_id="chart-b",
    )
    second = save_synastry_snapshot(
        _minimal_report(),
        label="Repeated label",
        charts_dir=charts_dir,
        chart_a_id="chart-a",
        chart_b_id="chart-b",
    )
    assert (first.id, second.id) == ("repeated-label", "repeated-label-2")

    with pytest.raises(ChartLibraryError, match="already exists"):
        save_synastry_snapshot(
            _minimal_report(),
            label="Repeated label",
            charts_dir=charts_dir,
            snapshot_id=first.id,
            chart_a_id="chart-a",
            chart_b_id="chart-b",
        )
    with pytest.raises(ChartLibraryError, match="different natal charts"):
        save_synastry_snapshot(
            _minimal_report(),
            label="Repeated label",
            charts_dir=charts_dir,
            snapshot_id=first.id,
            chart_a_id="different-a",
            chart_b_id="different-b",
            overwrite=True,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("schema_version", True, "schema_version"),
        ("schema_version", None, "schema_version"),
        ("type", None, "Not a synastry snapshot"),
        ("chart_a_id", 7, "chart_a_id"),
        ("label", "line\nbreak", "control characters"),
    ),
)
def test_snapshot_loader_rejects_malformed_wrapper_fields(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    charts_dir = tmp_path / "charts"
    saved = save_synastry_snapshot(
        _minimal_report(),
        label="Valid record",
        charts_dir=charts_dir,
        snapshot_id="valid-record",
    )
    payload = json.loads(saved.source_path.read_text(encoding="utf-8"))
    if value is None:
        payload.pop(field)
    else:
        payload[field] = value
    saved.source_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ChartLibraryError, match=message):
        list_synastries(charts_dir)


def test_snapshot_loader_rejects_filename_mismatch_and_malformed_report(
    tmp_path: Path,
) -> None:
    charts_dir = tmp_path / "charts"
    saved = save_synastry_snapshot(
        _minimal_report(),
        label="Valid record",
        charts_dir=charts_dir,
        snapshot_id="valid-record",
    )
    payload = json.loads(saved.source_path.read_text(encoding="utf-8"))
    payload["id"] = "wrong-id"
    saved.source_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ChartLibraryError, match="does not match filename"):
        load_synastry("valid-record", charts_dir)

    payload["id"] = "valid-record"
    payload["report"]["gaps"] = 1
    saved.source_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ChartLibraryError, match="report.gaps must be an array"):
        list_synastries(charts_dir)


def test_snapshot_loader_rejects_symlinks_and_nonfinite_json(tmp_path: Path) -> None:
    charts_dir = tmp_path / "charts"
    directory = charts_dir / "synastry"
    directory.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    link = directory / "linked.json"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("filesystem does not permit symlink creation")
    with pytest.raises(ChartLibraryError, match="symlinked"):
        list_synastries(charts_dir)

    link.unlink()
    (directory / "nonfinite.json").write_text(
        '{"schema_version": 1, "value": NaN}',
        encoding="utf-8",
    )
    with pytest.raises(ChartLibraryError, match="non-finite JSON"):
        list_synastries(charts_dir)


def test_failed_strict_json_overwrite_preserves_existing_snapshot(
    tmp_path: Path,
) -> None:
    charts_dir = tmp_path / "charts"
    saved = save_synastry_snapshot(
        _minimal_report(),
        label="Stable record",
        charts_dir=charts_dir,
        snapshot_id="stable-record",
        chart_a_id="chart-a",
        chart_b_id="chart-b",
    )
    before = saved.source_path.read_bytes()
    malformed = _minimal_report()
    malformed["relationships"] = [{"force": float("nan")}]
    with pytest.raises(ValueError, match="Out of range float"):
        save_synastry_snapshot(
            malformed,
            label=saved.label,
            charts_dir=charts_dir,
            snapshot_id=saved.id,
            chart_a_id=saved.chart_a_id,
            chart_b_id=saved.chart_b_id,
            overwrite=True,
        )
    assert saved.source_path.read_bytes() == before


def test_web_synastry_snapshot_save_list_show_and_refresh(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    pytest.importorskip("swisseph")
    from fastapi.testclient import TestClient
    from sidereal.web import create_app

    database = tmp_path / "sidereal.db"
    charts_dir = tmp_path / "charts"
    _seed_database(database)
    client = TestClient(create_app(db_path=database, charts_dir=charts_dir))

    chart_ids: list[str] = []
    for label, date in (("Chart A", "2000-12-12"), ("Chart B", "1990-06-15")):
        response = client.post(
            "/api/charts",
            json={
                "moment": {
                    "date": date,
                    "time": "12:00",
                    "tz": "UTC",
                    "lat": 0,
                    "lon": 0,
                    "label": label,
                }
            },
        )
        assert response.status_code == 200, response.text
        chart_ids.append(response.json()["id"])

    created = client.post(
        "/api/synastry",
        json={
            "a_id": chart_ids[0],
            "b_id": chart_ids[1],
            "save": True,
            "snapshot_id": "pair-one",
            "label": "Chart A ↔ Chart B",
        },
    )
    assert created.status_code == 200, created.text
    created_payload = created.json()
    assert created_payload["saved_synastry"]["id"] == "pair-one"

    listing = client.get("/api/synastries")
    assert listing.status_code == 200
    assert listing.json()["synastries"][0]["id"] == "pair-one"
    shown = client.get("/api/synastries/pair-one")
    assert shown.status_code == 200
    assert shown.json()["report"]["report_type"] == "synastry"

    target = next(
        item["reading"]["id"]
        for item in created_payload["relationships"]
        if item["reading"]["status"] in {"ready", "user"}
    )
    refreshed_summary = "A local test summary loaded from the current interpretation DB."
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE interpretation_entries SET summary = ?, status = 'user' WHERE id = ?",
            (refreshed_summary, target),
        )

    refreshed = client.post("/api/synastries/pair-one/refresh", json={})
    assert refreshed.status_code == 200, refreshed.text
    refreshed_payload = refreshed.json()
    assert refreshed_payload["saved_synastry"]["id"] == "pair-one"
    target_reading = next(
        item["reading"]
        for item in refreshed_payload["report"]["relationships"]
        if item["reading"]["id"] == target
    )
    assert target_reading["summary"] == refreshed_summary
    assert load_synastry("pair-one", charts_dir).report["relationships"]

    snapshot_path = charts_dir / "synastry" / "pair-one.json"
    stable_snapshot = snapshot_path.read_bytes()
    missing_db_client = TestClient(
        create_app(db_path=tmp_path / "missing.db", charts_dir=charts_dir)
    )
    missing_db = missing_db_client.post(
        "/api/synastries/pair-one/refresh",
        json={},
    )
    assert missing_db.status_code == 404
    assert snapshot_path.read_bytes() == stable_snapshot

    inline_save = client.post(
        "/api/synastry",
        json={
            "a": {
                "date": "2000-12-12",
                "time": "12:00",
                "tz": "UTC",
                "lat": 0,
                "lon": 0,
                "label": "Inline A",
            },
            "b": {
                "date": "1990-06-15",
                "time": "12:00",
                "tz": "UTC",
                "lat": 0,
                "lon": 0,
                "label": "Inline B",
            },
            "save": True,
        },
    )
    assert inline_save.status_code == 400
    assert "requires two saved charts" in inline_save.json()["detail"]

    unsafe = client.post(
        "/api/synastry",
        json={
            "a_id": chart_ids[0],
            "b_id": chart_ids[1],
            "save": True,
            "snapshot_id": "../escape",
        },
    )
    assert unsafe.status_code == 400
    assert "snapshot id" in unsafe.json()["detail"]
    duplicate = client.post(
        "/api/synastry",
        json={
            "a_id": chart_ids[0],
            "b_id": chart_ids[1],
            "save": True,
            "snapshot_id": "pair-one",
        },
    )
    assert duplicate.status_code == 400
    assert snapshot_path.read_bytes() == stable_snapshot
    assert client.get("/api/synastries/not-found").status_code == 404
