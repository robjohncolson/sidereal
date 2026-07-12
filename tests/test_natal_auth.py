from __future__ import annotations

import base64
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
import hashlib
import hmac
import json

import pytest

try:
    import fastapi  # noqa: F401 - verifies the optional web package is importable
    import httpx
except ImportError:  # core auth/natal/cache tests still run under ``.[dev]``
    httpx = None  # type: ignore[assignment]

from sidereal.auth import AuthenticationError, SupabaseJWTAuthenticator
from sidereal.natal import (
    MemoryNatalStore,
    NatalRecord,
    NatalStoreError,
    natal_record_from_payload,
)
from sidereal.personal_sky import PersonalSkyCache, compute_natal_chart
if httpx is not None:
    from sidereal.web.supabase_natal import SupabaseNatalStore, natal_store_from_env


requires_web_store = pytest.mark.skipif(
    httpx is None,
    reason="Supabase store tests require the optional web dependencies",
)


def _record(
    user_id: str = "user-a",
    *,
    updated_at: datetime = datetime(2026, 7, 12, 12, tzinfo=UTC),
) -> NatalRecord:
    return NatalRecord(
        user_id=user_id,
        birth_date=date(1983, 11, 29),
        birth_time=time(22, 24),
        time_unknown=False,
        tz="Asia/Tokyo",
        lat=35.68,
        lon=139.69,
        place_label="Tokyo, Japan",
        updated_at=updated_at,
    )


def _jwt(secret: str, claims: dict[str, object], *, algorithm: str = "HS256") -> str:
    def encoded(value: object) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    header = encoded({"alg": algorithm, "typ": "JWT"})
    payload = encoded(claims)
    signature = hmac.new(
        secret.encode(),
        f"{header}.{payload}".encode(),
        hashlib.sha256,
    ).digest()
    return f"{header}.{payload}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def test_supabase_hs256_authenticator_validates_standard_claims() -> None:
    secret = "test-secret"
    claims: dict[str, object] = {
        "sub": "user-a",
        "exp": 2_000,
        "iat": 900,
        "nbf": 800,
        "aud": "authenticated",
        "role": "authenticated",
        "iss": "https://project.supabase.co/auth/v1",
    }
    auth = SupabaseJWTAuthenticator(
        secret,
        issuer="https://project.supabase.co/auth/v1",
        clock=lambda: 1_000,
        leeway_seconds=0,
    )
    assert auth.authenticate(_jwt(secret, claims)) == "user-a"

    invalid_claims = (
        {**claims, "exp": 999},
        {**claims, "nbf": 1_001},
        {**claims, "iat": 1_001},
        {**claims, "aud": "anon"},
        {**claims, "role": "service_role"},
        {**claims, "iss": "https://attacker.example/auth/v1"},
        {key: value for key, value in claims.items() if key != "sub"},
    )
    for payload in invalid_claims:
        with pytest.raises(AuthenticationError):
            auth.authenticate(_jwt(secret, payload))
    with pytest.raises(AuthenticationError):
        auth.authenticate(_jwt("wrong-secret", claims))
    with pytest.raises(AuthenticationError):
        auth.authenticate(_jwt(secret, claims, algorithm="none"))
    with pytest.raises(AuthenticationError):
        auth.authenticate("not-a-jwt")


def test_natal_payload_normalizes_unknown_time_and_memory_store() -> None:
    record = natal_record_from_payload(
        "user-a",
        {
            "birth_date": "1983-11-29",
            "birth_time": None,
            "time_unknown": False,
            "tz": "Asia/Tokyo",
            "lat": 35.68,
            "lon": 139.69,
            "place_label": "Tokyo, Japan",
        },
        updated_at=datetime(2026, 7, 12, tzinfo=UTC),
    )
    assert record.birth_time is None
    assert record.time_unknown is True
    chart, _config = compute_natal_chart(record)
    assert chart.meta.time_known is False
    assert chart.meta.local_datetime.hour == 12
    assert chart.cusps is None
    assert all(point.id not in {"asc", "mc", "desc", "ic"} for point in chart.points)

    store = MemoryNatalStore()
    assert store.get("user-a") is None
    assert store.upsert(record) == record
    assert store.get("user-a") == record
    assert store.get("user-b") is None
    assert store.delete("user-a") is True
    assert store.delete("user-a") is False

    explicitly_unknown = natal_record_from_payload(
        "user-a",
        {
            "birth_date": "1983-11-29",
            "birth_time": "22:24:00",
            "time_unknown": True,
            "tz": "Asia/Tokyo",
            "lat": None,
            "lon": None,
            "place_label": "",
        },
        updated_at=datetime(2026, 7, 12, tzinfo=UTC),
    )
    assert explicitly_unknown.birth_time is None
    assert explicitly_unknown.time_unknown is True
    assert explicitly_unknown.lat is None and explicitly_unknown.lon is None


@pytest.mark.parametrize(
    "change",
    (
        {"birth_date": "19831129"},
        {"birth_date": "2026-02-30"},
        {"birth_time": "222400"},
        {"time_unknown": "yes"},
        {"tz": "Mars/Olympus_Mons"},
        {"tz": "+05:30"},
        {"lon": None},
        {"lat": 90},
        {"lon": 181},
        {"user_id": "body-controlled"},
    ),
)
def test_natal_payload_rejects_invalid_private_metadata(
    change: dict[str, object],
) -> None:
    payload: dict[str, object] = {
        "birth_date": "1983-11-29",
        "birth_time": "22:24:00",
        "time_unknown": False,
        "tz": "Asia/Tokyo",
        "lat": 35.68,
        "lon": 139.69,
        "place_label": "Tokyo",
    }
    payload.update(change)
    with pytest.raises(ValueError):
        natal_record_from_payload("user-a", payload)


def test_personal_sky_cache_keys_user_timezone_date_and_record_version() -> None:
    calls: list[tuple[str, str, str]] = []

    def builder(
        record: NatalRecord,
        *,
        when: datetime,
        tz: str,
    ) -> dict[str, object]:
        calls.append((record.user_id, tz, when.isoformat()))
        return {"privacy": "user_private", "call": len(calls)}

    cache = PersonalSkyCache(builder)
    record = _record()
    now = datetime(2026, 7, 12, 3, tzinfo=UTC)
    first = cache.get(record, tz="UTC", now=now)
    first["mutated"] = True
    assert cache.get(record, tz="Z", now=now) == {
        "privacy": "user_private",
        "call": 1,
    }
    assert len(calls) == 1

    assert cache.get(record, tz="Asia/Tokyo", now=now)["call"] == 2
    assert cache.get(record, tz="UTC", now=now)["call"] == 1
    assert len(calls) == 2

    next_day = now + timedelta(days=1)
    assert cache.get(record, tz="UTC", now=next_day)["call"] == 3
    changed = _record(updated_at=record.updated_at + timedelta(microseconds=1))
    assert cache.get(changed, tz="UTC", now=next_day)["call"] == 4
    same_timestamp_changed_profile = replace(changed, place_label="Osaka, Japan")
    assert cache.get(
        same_timestamp_changed_profile,
        tz="UTC",
        now=next_day,
    )["call"] == 5
    cache.invalidate("user-a")
    assert cache.get(changed, tz="UTC", now=next_day)["call"] == 6


@requires_web_store
def test_supabase_natal_store_crud_and_sanitized_failures() -> None:
    rows: dict[str, dict[str, object]] = {}
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["apikey"] == "sb_secret_test_server_key"
        assert "authorization" not in request.headers
        user_id = "user-a"
        if request.method == "POST":
            row = json.loads(request.content)
            rows[user_id] = row
            return httpx.Response(200, json=[row])
        if request.method == "GET":
            return httpx.Response(200, json=[rows[user_id]] if user_id in rows else [])
        if request.method == "DELETE":
            removed = rows.pop(user_id, None)
            return httpx.Response(200, json=[removed] if removed else [])
        raise AssertionError(request.method)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    store = SupabaseNatalStore(
        "https://project.supabase.co",
        "sb_secret_test_server_key",
        client=client,
    )
    record = _record()
    assert store.get("user-a") is None
    assert store.upsert(record) == record
    assert store.get("user-a") == record
    assert store.delete("user-a") is True
    assert store.delete("user-a") is False
    assert any("on_conflict=user_id" in str(item.url) for item in requests)
    assert any(
        item.headers.get("prefer")
        == "handling=strict,max-affected=1,return=representation"
        for item in requests
        if item.method == "DELETE"
    )

    legacy_requests: list[httpx.Request] = []

    def legacy_handler(request: httpx.Request) -> httpx.Response:
        legacy_requests.append(request)
        return httpx.Response(200, json=[])

    legacy_key = "header.payload.signature"
    legacy = SupabaseNatalStore(
        "https://project.supabase.co",
        legacy_key,
        client=httpx.Client(transport=httpx.MockTransport(legacy_handler)),
    )
    assert legacy.get("user-a") is None
    assert legacy_requests[0].headers["apikey"] == legacy_key
    assert legacy_requests[0].headers["authorization"] == f"Bearer {legacy_key}"

    failing = SupabaseNatalStore(
        "https://project.supabase.co",
        "sb_secret_test_server_key",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(500, text="secret remote detail")
            )
        ),
    )
    with pytest.raises(NatalStoreError, match="request failed") as raised:
        failing.get("user-a")
    assert "secret remote detail" not in str(raised.value)


@pytest.mark.parametrize("method", ("GET", "DELETE"))
@requires_web_store
def test_supabase_store_rejects_wrong_owner_rows(method: str) -> None:
    wrong_row = _record("user-b").storage_dict()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == method
        return httpx.Response(200, json=[wrong_row])

    store = SupabaseNatalStore(
        "https://project.supabase.co",
        "sb_secret_test_server_key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(NatalStoreError, match="wrong user"):
        if method == "GET":
            store.get("user-a")
        else:
            store.delete("user-a")


@requires_web_store
def test_supabase_store_env_selection_rejects_partial_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in (
        "SIDEREAL_NATAL_BACKEND",
        "SUPABASE_URL",
        "SUPABASE_SECRET_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    assert isinstance(natal_store_from_env(), MemoryNatalStore)
    monkeypatch.setenv("SUPABASE_URL", "   ")
    with pytest.raises(ValueError, match="requires both"):
        natal_store_from_env()
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    with pytest.raises(ValueError, match="requires both"):
        natal_store_from_env()
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test_server_key")
    selected = natal_store_from_env()
    assert isinstance(selected, SupabaseNatalStore)
    selected.close()
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "   ")
    with pytest.raises(ValueError, match="requires both"):
        natal_store_from_env()
    monkeypatch.setenv("SIDEREAL_NATAL_BACKEND", "memory")
    assert isinstance(natal_store_from_env(), MemoryNatalStore)


@requires_web_store
@pytest.mark.parametrize(
    "url",
    (
        "http://127.0.0.1.attacker.example",
        "http://localhost.attacker.example",
        "http://example.com",
    ),
)
def test_supabase_store_never_sends_keys_to_non_loopback_http(url: str) -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        SupabaseNatalStore(url, "sb_secret_test_server_key")

    local = SupabaseNatalStore(
        "http://127.0.0.1:54321",
        "sb_secret_test_server_key",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, json=[])
            )
        ),
    )
    assert local.get("user-a") is None
