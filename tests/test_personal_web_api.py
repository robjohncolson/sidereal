from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("swisseph")

from fastapi.testclient import TestClient

from sidereal.auth import AuthenticationError
from sidereal.interpret.generate_seeds import resolve_seed_directory
from sidereal.interpret.store import InterpretationStore
from sidereal.natal import MemoryNatalStore, NatalStoreError
from sidereal.web import create_app


class TestAuthenticator:
    def authenticate(self, token: str) -> str:
        users = {"token-a": "user-a", "token-b": "user-b"}
        try:
            return users[token]
        except KeyError as exc:
            raise AuthenticationError("invalid test token") from exc


class FailingNatalStore:
    def get(self, user_id: str) -> None:
        del user_id
        raise NatalStoreError("sensitive backend detail")

    def upsert(self, record: object) -> object:
        del record
        raise NatalStoreError("sensitive backend detail")

    def delete(self, user_id: str) -> bool:
        del user_id
        raise NatalStoreError("sensitive backend detail")


def _headers(token: str = "token-a", *, origin: bool = False) -> dict[str, str]:
    result = {"Authorization": f"Bearer {token}"}
    if origin:
        result["Origin"] = "https://aim-dojo.vercel.app"
    return result


def _payload(*, unknown: bool = False) -> dict[str, Any]:
    return {
        "birth_date": "1983-11-29",
        "birth_time": None if unknown else "22:24:00",
        "time_unknown": unknown,
        "tz": "Asia/Tokyo",
        "lat": 35.68,
        "lon": 139.69,
        "place_label": "Tokyo, Japan",
    }


@pytest.fixture
def personal_client(tmp_path: Path) -> tuple[TestClient, MemoryNatalStore]:
    database = tmp_path / "sidereal.db"
    with InterpretationStore(database) as store:
        store.initialize()
        store.import_path(resolve_seed_directory())
    natal_store = MemoryNatalStore()
    app = create_app(
        db_path=database,
        charts_dir=tmp_path / "charts",
        natal_store=natal_store,
        authenticator=TestAuthenticator(),
    )
    return TestClient(app), natal_store


def test_personal_routes_require_auth_and_cors_covers_401(
    personal_client: tuple[TestClient, MemoryNatalStore],
) -> None:
    client, _store = personal_client
    for method, path, kwargs in (
        ("get", "/api/me/natal", {}),
        ("post", "/api/me/natal", {"json": _payload()}),
        ("post", "/api/me/natal", {}),
        ("post", "/api/me/natal", {"json": []}),
        ("delete", "/api/me/natal", {}),
        ("get", "/api/me/skypack", {}),
    ):
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 401, (method, path, response.text)
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.headers["cache-control"] == "private, no-store"

    invalid = client.get(
        "/api/me/natal",
        headers={"Authorization": "Bearer wrong", "Origin": "https://aim-dojo.vercel.app"},
    )
    assert invalid.status_code == 401
    assert invalid.headers["access-control-allow-origin"] == (
        "https://aim-dojo.vercel.app"
    )

    preflight = client.options(
        "/api/me/natal",
        headers={
            "Origin": "https://aim-dojo.vercel.app",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == (
        "https://aim-dojo.vercel.app"
    )
    assert "Authorization" in preflight.headers["access-control-allow-headers"]
    assert "POST" in preflight.headers["access-control-allow-methods"]

    hostile_host = client.get(
        "/api/me/natal",
        headers={
            "Host": "evil.example",
            "Origin": "https://aim-dojo.vercel.app",
            "Authorization": "Bearer token-a",
        },
    )
    assert hostile_host.status_code == 400
    assert "access-control-allow-origin" not in hostile_host.headers


def test_personal_natal_crud_private_pack_and_user_isolation(
    personal_client: tuple[TestClient, MemoryNatalStore],
) -> None:
    client, _store = personal_client
    saved_response = client.post(
        "/api/me/natal",
        json=_payload(),
        headers=_headers(origin=True),
    )
    assert saved_response.status_code == 200, saved_response.text
    assert saved_response.headers["cache-control"] == "private, no-store"
    assert saved_response.headers["access-control-allow-origin"] == (
        "https://aim-dojo.vercel.app"
    )
    saved = saved_response.json()
    assert saved["type"] == "natal_profile"
    assert saved["user_id"] == "user-a"
    assert saved["birth_date"] == "1983-11-29"
    assert saved["birth_time"] == "22:24:00"
    assert "chart" not in saved and "points" not in saved

    for invalid_date, invalid_time in (
        ("2026-03-08", "02:30:00"),  # DST gap
        ("2026-11-01", "01:30:00"),  # DST fold cannot be disambiguated in v1
    ):
        invalid_civil_time = {
            **_payload(),
            "birth_date": invalid_date,
            "birth_time": invalid_time,
            "tz": "America/New_York",
            "lat": 40.7128,
            "lon": -74.006,
            "place_label": "New York, USA",
        }
        rejected = client.post(
            "/api/me/natal",
            json=invalid_civil_time,
            headers=_headers(),
        )
        assert rejected.status_code == 400

    fetched = client.get("/api/me/natal", headers=_headers())
    assert fetched.status_code == 200
    assert fetched.json() == saved
    other_user = client.get("/api/me/natal", headers=_headers("token-b"))
    assert other_user.status_code == 404
    assert other_user.headers["cache-control"] == "private, no-store"

    pack_response = client.get("/api/me/skypack", headers=_headers())
    assert pack_response.status_code == 200, pack_response.text
    pack = pack_response.json()
    assert pack["schema_version"] == 2
    assert pack["type"] == "skypack"
    assert pack["privacy"] == "user_private"
    assert pack["natal_id"] == "user-a"
    assert pack["natal_label"] == "Saved sky"
    assert pack["location"] is None
    assert len(pack["movers"]) == 12
    assert len(pack["natal_ghosts"]) == 12
    assert len(pack["same_body_delta"]) == 12
    assert all(
        forbidden not in json_text
        for forbidden in ("birth_date", "birth_time", "place_label", "Tokyo, Japan")
        for json_text in [pack_response.text]
    )
    cached = client.get("/api/me/skypack", headers=_headers())
    assert cached.json() == pack

    deleted = client.delete("/api/me/natal", headers=_headers())
    assert deleted.status_code == 204
    assert client.get("/api/me/natal", headers=_headers()).status_code == 404
    assert client.get("/api/me/skypack", headers=_headers()).status_code == 404


def test_authenticated_sky_listen_uses_user_natal_and_keeps_legacy_choice_clear(
    personal_client: tuple[TestClient, MemoryNatalStore],
) -> None:
    client, _store = personal_client
    assert client.post(
        "/api/me/natal", json=_payload(unknown=True), headers=_headers()
    ).status_code == 200
    response = client.get(
        "/api/sky-listen",
        params={"body": "uranus", "when": "2026-07-11T18:09:00", "tz": "UTC"},
        headers=_headers(origin=True),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["personal"]["available"] is True
    assert payload["personal"]["natal_id"] == "user-a"
    assert payload["personal"]["title"]
    assert payload["personal"]["text"]
    assert "birth_date" not in response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["access-control-allow-origin"] == (
        "https://aim-dojo.vercel.app"
    )

    no_chart = client.get(
        "/api/sky-listen",
        params={"body": "sun", "when": "2026-07-11T18:09:00", "tz": "UTC"},
        headers=_headers("token-b"),
    )
    assert no_chart.status_code == 200
    assert no_chart.json()["personal"] == {"available": False}
    assert no_chart.headers["cache-control"] == "private, no-store"

    ambiguous = client.get(
        "/api/sky-listen",
        params={"natal_id": "legacy", "body": "sun"},
        headers=_headers(),
    )
    assert ambiguous.status_code == 400
    invalid = client.get(
        "/api/sky-listen",
        params={"body": "sun"},
        headers={"Authorization": "Bearer wrong"},
    )
    assert invalid.status_code == 401
    assert invalid.headers["cache-control"] == "private, no-store"


def test_dev_auth_is_explicit_and_public_sky_day_remains_natal_free(
    tmp_path: Path,
) -> None:
    store = MemoryNatalStore()
    enabled = TestClient(
        create_app(
            db_path=tmp_path / "missing.db",
            charts_dir=tmp_path / "charts",
            natal_store=store,
            authenticator=TestAuthenticator(),
            allow_dev_auth=True,
        )
    )
    saved = enabled.post(
        "/api/me/natal",
        json=_payload(),
        headers={"X-Dev-User-Id": "dev-user"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["user_id"] == "dev-user"

    disabled = TestClient(
        create_app(
            db_path=tmp_path / "missing-2.db",
            charts_dir=tmp_path / "charts-2",
            natal_store=MemoryNatalStore(),
            authenticator=TestAuthenticator(),
            allow_dev_auth=False,
        )
    )
    assert disabled.get(
        "/api/me/natal", headers={"X-Dev-User-Id": "dev-user"}
    ).status_code == 401

    sky_day = enabled.get(
        "/api/sky-day",
        params={"tz": "UTC", "date": "2026-07-12"},
    )
    assert sky_day.status_code == 200, sky_day.text
    public = sky_day.json()
    assert public["privacy"] == "public"
    assert "natal_id" not in public
    assert public["natal_ghosts"] == []
    assert "birth_date" not in sky_day.text

    with pytest.raises(ValueError, match="loopback"):
        create_app(
            db_path=tmp_path / "missing-public.db",
            charts_dir=tmp_path / "charts-public",
            bind_host="0.0.0.0",
            allow_lan=True,
            natal_store=MemoryNatalStore(),
            authenticator=TestAuthenticator(),
            allow_dev_auth=True,
        )


def test_personal_backend_failures_are_private_and_sanitized(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            db_path=tmp_path / "missing.db",
            charts_dir=tmp_path / "charts",
            natal_store=FailingNatalStore(),
            authenticator=TestAuthenticator(),
        )
    )
    response = client.get(
        "/api/me/natal",
        headers=_headers(origin=True),
    )
    assert response.status_code == 503
    assert response.json() == {
        "detail": "Natal storage is temporarily unavailable"
    }
    assert "sensitive backend detail" not in response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["access-control-allow-origin"] == (
        "https://aim-dojo.vercel.app"
    )
