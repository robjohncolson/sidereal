from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("swisseph")

from fastapi.testclient import TestClient

from sidereal.cli import build_parser, main
from sidereal.interpret.audit import report_interpretation_ids
from sidereal.interpret.generate_seeds import resolve_seed_directory
from sidereal.interpret.store import InterpretationStore
from sidereal.web import create_app


def _moment(*, label: str = "Web Demo") -> dict[str, object]:
    return {
        "date": "2000-12-12",
        "time": "12:00",
        "tz": "UTC",
        "lat": 0,
        "lon": 0,
        "label": label,
    }


@pytest.fixture
def web_client(tmp_path: Path) -> TestClient:
    database = tmp_path / "sidereal.db"
    with InterpretationStore(database) as store:
        store.initialize()
        store.import_path(resolve_seed_directory())
    app = create_app(db_path=database, charts_dir=tmp_path / "charts")
    return TestClient(app)


def test_web_chart_health_and_static_shell(web_client: TestClient) -> None:
    health = web_client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["ephemeris_backend"] in {"swisseph", "moseph"}

    shell = web_client.get("/")
    assert shell.status_code == 200
    assert "birth data and saved charts stay on this machine" in shell.text.lower()
    assert "epistemic" in shell.text.lower()

    response = web_client.post(
        "/api/chart",
        json={"moment": _moment(), "options": {"compare_tropical": True}},
    )
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["chart"]["meta"]["input"]["label"] == "Web Demo"
    assert report["comparison"]["systems"] == ["midpoint_v1", "tropical"]
    assert "one true system" in report["comparison"]["note"]
    assert report["epistemic_note"]

    rebinding = web_client.get("/api/charts", headers={"Host": "evil.example"})
    assert rebinding.status_code == 400
    assert rebinding.json()["detail"] == "Untrusted Host header"


def test_web_library_interpret_and_transit_round_trip(web_client: TestClient) -> None:
    saved_response = web_client.post(
        "/api/charts",
        json={"moment": _moment(label="Saved Web"), "options": {}},
    )
    assert saved_response.status_code == 200, saved_response.text
    saved = saved_response.json()

    listing = web_client.get("/api/charts")
    assert listing.status_code == 200
    assert listing.json()["charts"][0]["id"] == saved["id"]
    shown = web_client.get(f"/api/charts/{saved['id']}")
    assert shown.status_code == 200
    assert shown.json()["chart"] == saved["chart"]

    interpreted = web_client.post(f"/api/charts/{saved['id']}/interpret")
    assert interpreted.status_code == 200, interpreted.text
    assert interpreted.json()["interpretation"]["planets"]

    transit = web_client.post(
        "/api/transit",
        json={
            "natal_id": saved["id"],
            "transit": {"date": "2026-07-11", "time": "12:00", "tz": "UTC"},
            "options": {},
        },
    )
    assert transit.status_code == 200, transit.text
    transit_report = transit.json()
    assert transit_report["report_type"] == "transit"
    assert transit_report["natal"]["source"] == "saved"
    assert len(transit_report["placements"]) == 12
    assert any(
        item["aspect"]["transit_body"] == "uranus"
        and item["aspect"]["natal_point"] == "jupiter"
        and item["aspect"]["exactness"] < 1.0
        for item in transit_report["relationships"]
    )
    assert report_interpretation_ids(transit_report)

    scoped = web_client.get("/api/db/gaps", params={"chart_id": saved["id"]})
    assert scoped.status_code == 200
    assert scoped.json()["missing"] == 0
    assert scoped.json()["expected"] < 967
    entry = web_client.get("/api/db/entry/planet:sun")
    assert entry.status_code == 200
    assert entry.json()["status"] == "ready"


def test_web_skypack_export_and_errors(web_client: TestClient) -> None:
    saved_response = web_client.post(
        "/api/charts",
        json={"moment": _moment(label="Sky Pack Web"), "options": {}},
    )
    assert saved_response.status_code == 200, saved_response.text
    saved = saved_response.json()

    response = web_client.get(
        "/api/skypack",
        params={
            "natal_id": saved["id"],
            "when": "2026-07-11T18:09:00",
            "tz": "UTC",
        },
    )
    assert response.status_code == 200, response.text
    pack = response.json()
    assert pack["schema_version"] == 1
    assert pack["type"] == "skypack"
    assert pack["projection"] == "ecliptic_dome_v1"
    assert pack["epoch_utc"] == "2026-07-11T18:09:00+00:00"
    assert len(pack["sign_band"]) == 13
    assert len(pack["movers"]) == 12
    assert len(pack["natal_ghosts"]) == 12

    missing = web_client.get(
        "/api/skypack",
        params={"natal_id": "does-not-exist"},
    )
    assert missing.status_code == 404
    bad_when = web_client.get(
        "/api/skypack",
        params={"natal_id": saved["id"], "when": "not-a-datetime"},
    )
    assert bad_when.status_code == 400
    bad_timezone = web_client.get(
        "/api/skypack",
        params={"natal_id": saved["id"], "tz": "Mars/Olympus_Mons"},
    )
    assert bad_timezone.status_code == 400
    no_identifier = web_client.get("/api/skypack")
    assert no_identifier.status_code == 400


def test_web_inline_transit_and_validation_errors(web_client: TestClient) -> None:
    transit = web_client.post(
        "/api/transit",
        json={
            "natal": {
                "date": "2000-12-12",
                "tz": "UTC",
                "label": "Unknown time",
            },
            "transit": {"date": "2026-07-11", "time": "12:00", "tz": "UTC"},
        },
    )
    assert transit.status_code == 200, transit.text
    report = transit.json()
    assert report["natal"]["time_known"] is False
    assert all(item["natal_house"] is None for item in report["placements"])
    assert all(
        item["aspect"]["natal_point"] not in {"asc", "mc"}
        for item in report["relationships"]
    )

    bad_location = web_client.post(
        "/api/chart",
        json={"moment": {**_moment(), "lon": None}},
    )
    assert bad_location.status_code == 400
    assert "supplied together" in bad_location.json()["detail"]
    no_natal = web_client.post(
        "/api/transit",
        json={"transit": {"date": "2026-07-11", "time": "12:00", "tz": "UTC"}},
    )
    assert no_natal.status_code == 400


def test_serve_defaults_to_loopback_and_refuses_implicit_public_bind() -> None:
    args = build_parser().parse_args(["serve"])
    assert args.host == "127.0.0.1"
    assert args.port == 8742
    assert args.allow_lan is False

    with pytest.raises(SystemExit) as raised:
        main(["serve", "--host", "0.0.0.0"])
    assert raised.value.code == 2

    with pytest.raises(SystemExit) as raised:
        main(["serve", "--port", "70000"])
    assert raised.value.code == 2


def test_serve_allows_an_explicit_lan_bind_with_a_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    called: dict[str, object] = {}

    def fake_run(app: object, *, host: str, port: int) -> None:
        called.update(app=app, host=host, port=port)

    monkeypatch.setattr("uvicorn.run", fake_run)
    assert main(
        [
            "serve",
            "--host",
            "0.0.0.0",
            "--allow-lan",
            "--trusted-host",
            "astrology.lan",
            "--port",
            "9876",
            "--db",
            str(tmp_path / "sidereal.db"),
            "--charts-dir",
            str(tmp_path / "charts"),
        ]
    ) == 0

    assert called["host"] == "0.0.0.0"
    assert called["port"] == 9876
    assert getattr(called["app"], "title") == "Sidereal local desk"
    assert "no authentication" in capsys.readouterr().err.lower()

    lan_client = TestClient(called["app"], base_url="http://192.168.1.50")
    assert lan_client.get("/api/charts").status_code == 200
    assert lan_client.get(
        "/api/charts",
        headers={"Host": "rebind.attacker.example"},
    ).status_code == 400
    named_lan_client = TestClient(called["app"], base_url="http://astrology.lan")
    assert named_lan_client.get("/api/charts").status_code == 200
