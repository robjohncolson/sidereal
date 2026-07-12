from __future__ import annotations

import math
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("swisseph")

from fastapi.testclient import TestClient

from sidereal.cli import build_parser, main
from sidereal.interpret.audit import report_interpretation_ids
from sidereal.interpret.generate_seeds import resolve_seed_directory
from sidereal.interpret.store import InterpretationStore
from sidereal.skypack import ASPECT_GLYPHS
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
    assert pack["schema_version"] == 2
    assert pack["type"] == "skypack"
    assert pack["projection"] == "ecliptic_band_v2"
    assert pack["epoch_utc"] == "2026-07-11T18:09:00+00:00"
    assert len(pack["sign_band"]) == 13
    assert len(pack["movers"]) == 12
    assert len(pack["natal_ghosts"]) == 12
    assert len(pack["same_body_delta"]) == 12
    assert len(pack["resonance_rank"]) == len(pack["resonances"])

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


def test_web_sky_day_public_cache_and_cors(web_client: TestClient) -> None:
    response = web_client.get(
        "/api/sky-day",
        params={
            "tz": "UTC",
            "date": "2026-07-12",
            "when": "2026-07-12T12:15:00Z",
        },
        headers={"Origin": "https://aim-dojo.vercel.app"},
    )

    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == (
        "https://aim-dojo.vercel.app"
    )
    assert response.headers["cache-control"] == "public, max-age=3600"
    payload = response.json()
    assert payload["schema_version"] == 1
    assert payload["type"] == "skyday"
    assert payload["privacy"] == "public"
    assert payload["cache_date"] == "2026-07-12"
    assert payload["epoch_utc"] == "2026-07-12T12:15:00+00:00"
    assert len(payload["sign_band"]) == 13
    assert len(payload["movers"]) == 12
    assert "natal_id" not in payload
    for field in (
        "natal_ghosts",
        "resonances",
        "same_body_delta",
        "resonance_rank",
    ):
        assert payload[field] == []

    cached = web_client.get(
        "/api/sky-day",
        params={
            "tz": "UTC",
            "date": "2026-07-12",
            "when": "2026-07-12T20:00:00Z",
        },
    )
    assert cached.status_code == 200, cached.text
    assert cached.json() == payload
    assert cached.headers["vary"] == "Origin"

    preflight = web_client.options(
        "/api/sky-day",
        headers={
            "Origin": "https://robjohncolson.github.io",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == (
        "https://robjohncolson.github.io"
    )
    assert preflight.headers["access-control-allow-methods"] == "GET"

    rejected = web_client.options(
        "/api/sky-day",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert rejected.status_code == 400
    assert "access-control-allow-origin" not in rejected.headers

    unrelated = web_client.get(
        "/api/charts",
        headers={"Origin": "https://aim-dojo.vercel.app"},
    )
    assert unrelated.status_code == 200
    assert "access-control-allow-origin" not in unrelated.headers


def test_web_sky_day_env_cors_and_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "SKY_DAY_CORS_ORIGINS",
        " https://sky.example ,https://second.example ",
    )
    client = TestClient(
        create_app(
            db_path=tmp_path / "missing.db",
            charts_dir=tmp_path / "charts",
        )
    )

    custom_origin = client.get(
        "/api/sky-day",
        params={"date": "2026-07-12"},
        headers={"Origin": "https://sky.example"},
    )
    assert custom_origin.status_code == 200, custom_origin.text
    assert custom_origin.headers["access-control-allow-origin"] == (
        "https://sky.example"
    )

    invalid_params = (
        {"tz": "Mars/Olympus_Mons"},
        {"date": "20260712"},
        {"date": "2026-02-30"},
        {"date": "2026-07-12", "when": "not-a-datetime"},
    )
    for params in invalid_params:
        invalid = client.get(
            "/api/sky-day",
            params=params,
            headers={"Origin": "https://aim-dojo.vercel.app"},
        )
        assert invalid.status_code == 400, (params, invalid.text)
        assert invalid.json()["detail"]
        assert invalid.headers["access-control-allow-origin"] == (
            "https://aim-dojo.vercel.app"
        )
        assert invalid.headers["cache-control"] == "no-store"


def test_web_sky_day_ephemeris_failure_is_clear_500(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            db_path=tmp_path / "missing.db",
            charts_dir=tmp_path / "charts",
            boundary_path=tmp_path / "missing-boundaries.json",
        )
    )

    response = client.get(
        "/api/sky-day",
        params={"tz": "UTC", "date": "2026-07-12"},
        headers={"Origin": "https://aim-dojo.vercel.app"},
    )

    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == (
        "https://aim-dojo.vercel.app"
    )
    assert response.headers["cache-control"] == "no-store"
    assert "sky-day calculation failed" in response.json()["detail"].lower()
    assert "boundary" in response.json()["detail"].lower()


def test_web_sky_listen_placement_without_natal(web_client: TestClient) -> None:
    sign_response = web_client.get(
        "/api/sky-listen",
        params={"sign": "libra", "when": "2026-07-11T18:09:00", "tz": "UTC"},
    )
    assert sign_response.status_code == 200, sign_response.text
    sign_payload = sign_response.json()
    assert sign_payload["schema_version"] == 1
    assert sign_payload["type"] == "sky_listen"
    assert sign_payload["system"] == "midpoint_v1"
    assert "not predictions" in sign_payload["epistemic"]
    assert sign_payload["target"] == {
        "kind": "sign",
        "body": None,
        "sign": "libra",
        "lon_j2000": None,
        "degree_in_sign": None,
        "layer": "sky_now",
    }
    assert sign_payload["placement"]["title"] == "Libra"
    assert sign_payload["placement"]["status"] == "ready"
    assert sign_payload["placement"]["text"]
    assert sign_payload["personal"] == {"available": False}

    body_response = web_client.get(
        "/api/sky-listen",
        params={"body": "pluto", "when": "2026-07-11T18:09:00", "tz": "UTC"},
    )
    assert body_response.status_code == 200, body_response.text
    body_payload = body_response.json()
    target = body_payload["target"]
    assert target["kind"] == "body"
    assert target["body"] == "pluto"
    assert target["sign"]
    assert math.isfinite(target["lon_j2000"])
    assert math.isfinite(target["degree_in_sign"])
    assert body_payload["placement"]["title"] == (
        f"Pluto in {target['sign'].title()}"
    )
    assert body_payload["placement"]["status"] == "ready"
    assert body_payload["personal"] == {"available": False}


def test_web_sky_listen_personal_transit_and_cors(
    web_client: TestClient,
) -> None:
    saved_response = web_client.post(
        "/api/charts",
        json={"moment": _moment(label="Sky Listen Web"), "options": {}},
    )
    assert saved_response.status_code == 200, saved_response.text
    saved = saved_response.json()
    natal_id = saved["id"]

    response = web_client.get(
        "/api/sky-listen",
        params={
            "natal_id": natal_id,
            "body": "uranus",
            "when": "2026-07-11T18:09:00",
            "tz": "UTC",
        },
        headers={"Origin": "http://127.0.0.1:8931"},
    )
    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == (
        "http://127.0.0.1:8931"
    )
    payload = response.json()
    personal = payload["personal"]
    assert personal["available"] is True
    assert personal["natal_id"] == natal_id
    assert math.isfinite(personal["delta_deg"])
    assert 0.0 <= personal["delta_deg"] <= 180.0
    transit_lon = payload["target"]["lon_j2000"]
    natal_lon = next(
        point["lon_j2000"]
        for point in saved["chart"]["points"]
        if point["id"] == "uranus"
    )
    raw_delta = abs(transit_lon - natal_lon) % 360.0
    assert personal["delta_deg"] == pytest.approx(
        min(raw_delta, 360.0 - raw_delta),
        abs=1e-6,
    )
    assert personal["title"]
    assert personal["text"]
    assert "you will" not in personal["text"].lower()
    assert 1 <= len(personal["highlights"]) <= 5
    assert all(
        item["aspect_glyph"]
        and item["natal_point"]
        and math.isfinite(item["orb"])
        and item.get("title")
        and item.get("text")
        and item.get("aspect_id")
        for item in personal["highlights"]
    )
    # Glyph row alone is not enough — each seal must carry a study note for the HUD.
    assert all(len(str(item["text"])) > 40 for item in personal["highlights"])

    transit_response = web_client.post(
        "/api/transit",
        json={
            "natal_id": natal_id,
            "transit": {"date": "2026-07-11", "time": "18:09:00", "tz": "UTC"},
            "options": {},
        },
    )
    assert transit_response.status_code == 200, transit_response.text
    uranus_relationships = [
        item
        for item in transit_response.json()["relationships"]
        if item["aspect"]["transit_body"] == "uranus"
    ]
    uranus_relationships.sort(
        key=lambda item: (
            item["aspect"]["exactness"] / item["aspect"]["orb_used"],
            item["aspect"]["natal_point"],
            item["aspect"]["aspect_id"],
        )
    )
    expected_pairs = [
        (
            ASPECT_GLYPHS[item["aspect"]["aspect_id"]],
            item["aspect"]["natal_point"],
            item["aspect"]["exactness"],
        )
        for item in uranus_relationships[:5]
    ]
    got_pairs = [
        (item["aspect_glyph"], item["natal_point"], item["orb"])
        for item in personal["highlights"]
    ]
    assert got_pairs == expected_pairs

    sign_response = web_client.get(
        "/api/sky-listen",
        params={
            "natal_id": natal_id,
            "sign": "libra",
            "when": "2026-07-11T18:09:00",
            "tz": "UTC",
        },
    )
    assert sign_response.status_code == 200, sign_response.text
    sign_personal = sign_response.json()["personal"]
    assert sign_personal["available"] is True
    assert sign_personal["natal_id"] == natal_id
    assert sign_personal["highlights"] == []
    assert isinstance(sign_personal["natal_points"], list)
    assert isinstance(sign_personal["sky_bodies"], list)

    south_node_response = web_client.get(
        "/api/sky-listen",
        params={
            "natal_id": natal_id,
            "body": "south_node",
            "when": "2026-07-11T18:09:00",
            "tz": "UTC",
        },
    )
    assert south_node_response.status_code == 200, south_node_response.text
    south_node_personal = south_node_response.json()["personal"]
    assert south_node_personal["available"] is True
    assert south_node_personal["highlights"] == []
    assert "not configured" in south_node_personal["text"].lower()

    preflight = web_client.options(
        "/api/sky-listen",
        headers={
            "Origin": "http://127.0.0.1:8931",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == (
        "http://127.0.0.1:8931"
    )
    assert "GET" in preflight.headers["access-control-allow-methods"]

    rejected_origin = web_client.options(
        "/api/sky-listen",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert rejected_origin.status_code == 400
    assert "access-control-allow-origin" not in rejected_origin.headers

    rejected_host = web_client.options(
        "/api/sky-listen",
        headers={
            "Host": "evil.example",
            "Origin": "http://127.0.0.1:8931",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert rejected_host.status_code == 400
    assert rejected_host.json()["detail"] == "Untrusted Host header"
    assert "access-control-allow-origin" not in rejected_host.headers

    unrelated = web_client.get(
        "/api/charts",
        headers={"Origin": "http://127.0.0.1:8931"},
    )
    assert unrelated.status_code == 200
    assert "access-control-allow-origin" not in unrelated.headers


def test_web_sky_listen_missing_natal_and_invalid_params(
    web_client: TestClient,
) -> None:
    missing = web_client.get(
        "/api/sky-listen",
        params={"natal_id": "does-not-exist", "body": "sun"},
    )
    assert missing.status_code == 404

    invalid_params = (
        {},
        {"body": "ceres"},
        {"sign": "not_a_sign"},
        {"body": "sun", "kind": "sign"},
        {"sign": "libra", "kind": "body"},
        {"sign": "libra", "kind": "planet"},
        {"body": "sun", "when": "not-a-datetime"},
        {"body": "sun", "tz": "Mars/Olympus_Mons"},
    )
    for params in invalid_params:
        response = web_client.get("/api/sky-listen", params=params)
        assert response.status_code == 400, (params, response.text)
        assert response.json()["detail"]


def test_web_sky_listen_missing_store_is_an_honest_stub(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            db_path=tmp_path / "missing.db",
            charts_dir=tmp_path / "charts",
        )
    )

    response = client.get(
        "/api/sky-listen",
        params={"sign": "libra", "when": "2026-07-11T18:09:00", "tz": "UTC"},
    )

    assert response.status_code == 200, response.text
    placement = response.json()["placement"]
    assert placement["status"] == "missing"
    assert "geometry only" in placement["text"].lower()


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
