from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
import json
from pathlib import Path
from threading import Event
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("swisseph")

from fastapi.testclient import TestClient

from sidereal.auth import AuthenticationError
from sidereal.natal import MemoryNatalStore, NatalRecord, natal_record_from_payload
from sidereal.transit_essay import (
    GeneratedTransitEssay,
    MemoryTransitEssayStore,
    TRANSIT_ESSAY_FACTS_TYPE,
    TransitEssayService,
    build_transit_essay_facts,
    transit_essay_cache_date,
)
from sidereal.web import create_app


FIXED_NOW = datetime(2026, 7, 12, 2, 0, tzinfo=UTC)
PERSONAL_ORIGIN = "https://aim-dojo.vercel.app"


class TestAuthenticator:
    def authenticate(self, token: str) -> str:
        users = {"token-a": "user-a", "token-b": "user-b"}
        try:
            return users[token]
        except KeyError as exc:
            raise AuthenticationError("invalid test token") from exc


class BlockingAuthor:
    model = "test-transit-model"

    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self.calls: list[dict[str, Any]] = []

    def generate(self, facts: Mapping[str, Any]) -> GeneratedTransitEssay:
        self.calls.append(deepcopy(dict(facts)))
        self.started.set()
        if not self.release.wait(timeout=10.0):
            raise RuntimeError("test author was not released")
        return GeneratedTransitEssay(
            headline="A wider pattern comes into view",
            body=(
                "Several strands of the present sky can be held together without "
                "forcing a single conclusion. Notice which themes feel immediate, "
                "which need patience, and which become clearer through reflection."
            ),
            watchpoints=("Compare the tightest contacts before naming a theme.",),
        )


class UnsafeAuthor:
    model = "unsafe-test-model"

    def generate(self, facts: Mapping[str, Any]) -> GeneratedTransitEssay:
        del facts
        return GeneratedTransitEssay(
            headline="A guaranteed outcome",
            body=(
                "This symbolic pattern promises a guaranteed outcome and describes "
                "what must occur next, even though that certainty is not supported "
                "by a careful reading of the supplied geometry."
            ),
            watchpoints=(),
        )


def _headers(token: str = "token-a", *, origin: bool = False) -> dict[str, str]:
    result = {"Authorization": f"Bearer {token}"}
    if origin:
        result["Origin"] = PERSONAL_ORIGIN
    return result


def _record(user_id: str = "user-a") -> NatalRecord:
    return natal_record_from_payload(
        user_id,
        {
            "birth_date": "1983-11-29",
            "birth_time": "22:24:00",
            "time_unknown": False,
            "tz": "Asia/Tokyo",
            "lat": 35.68,
            "lon": 139.69,
            "place_label": "Tokyo, Japan",
        },
        updated_at=FIXED_NOW,
    )


def _app(
    tmp_path: Path,
    natal_store: MemoryNatalStore,
    service: TransitEssayService,
) -> Any:
    return create_app(
        db_path=tmp_path / "missing.db",
        charts_dir=tmp_path / "charts",
        natal_store=natal_store,
        authenticator=TestAuthenticator(),
        transit_essay_service=service,
    )


def _minimal_facts(record: NatalRecord, *, when: datetime) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "type": TRANSIT_ESSAY_FACTS_TYPE,
        "cache_date": transit_essay_cache_date(record, when),
        "aspects": [],
    }


def test_transit_essay_auth_natal_404_unavailable_and_cors_private(
    tmp_path: Path,
) -> None:
    natal_store = MemoryNatalStore()
    service = TransitEssayService(
        MemoryTransitEssayStore(),
        _minimal_facts,
        clock=lambda: FIXED_NOW,
    )
    app = _app(tmp_path, natal_store, service)

    with TestClient(app) as client:
        for method in ("get", "post"):
            unauthorized = getattr(client, method)("/api/me/transit-essay")
            assert unauthorized.status_code == 401
            assert unauthorized.headers["www-authenticate"] == "Bearer"
            assert unauthorized.headers["cache-control"] == "private, no-store"

        invalid = client.get(
            "/api/me/transit-essay",
            headers={
                "Authorization": "Bearer wrong",
                "Origin": PERSONAL_ORIGIN,
            },
        )
        assert invalid.status_code == 401
        assert invalid.headers["access-control-allow-origin"] == PERSONAL_ORIGIN
        assert invalid.headers["cache-control"] == "private, no-store"

        for method in ("get", "post"):
            missing = getattr(client, method)(
                "/api/me/transit-essay",
                headers=_headers(origin=True),
            )
            assert missing.status_code == 404
            assert missing.json() == {"detail": "No natal profile is saved"}
            assert missing.headers["access-control-allow-origin"] == PERSONAL_ORIGIN
            assert missing.headers["cache-control"] == "private, no-store"

        natal_store.upsert(_record())
        expected = {
            "schema_version": 1,
            "type": "personal_transit_essay",
            "status": "unavailable",
            "cache_date": "2026-07-12",
        }
        for method in ("get", "post"):
            unavailable = getattr(client, method)(
                "/api/me/transit-essay",
                headers=_headers(origin=True),
            )
            assert unavailable.status_code == 200
            assert unavailable.json() == expected
            assert unavailable.headers["access-control-allow-origin"] == PERSONAL_ORIGIN
            assert unavailable.headers["cache-control"] == "private, no-store"

        preflight = client.options(
            "/api/me/transit-essay",
            headers={
                "Origin": PERSONAL_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == PERSONAL_ORIGIN
        assert "POST" in preflight.headers["access-control-allow-methods"]
        assert "Authorization" in preflight.headers["access-control-allow-headers"]


def test_transit_essay_pending_ready_facts_privacy_and_idempotency(
    tmp_path: Path,
) -> None:
    natal_store = MemoryNatalStore((_record(),))
    author = BlockingAuthor()

    def facts_builder(record: NatalRecord, *, when: datetime) -> dict[str, Any]:
        return build_transit_essay_facts(record, when=when)

    service = TransitEssayService(
        MemoryTransitEssayStore(),
        facts_builder,
        author=author,
        clock=lambda: FIXED_NOW,
    )
    app = _app(tmp_path, natal_store, service)

    try:
        with TestClient(app) as client:
            pending = client.post(
                "/api/me/transit-essay",
                headers=_headers(origin=True),
            )
            assert pending.status_code == 200, pending.text
            assert pending.json() == {
                "schema_version": 1,
                "type": "personal_transit_essay",
                "status": "pending",
                "cache_date": "2026-07-12",
            }
            assert pending.headers["access-control-allow-origin"] == PERSONAL_ORIGIN
            assert pending.headers["cache-control"] == "private, no-store"
            assert author.started.wait(timeout=5.0)

            duplicate_pending = client.post(
                "/api/me/transit-essay",
                headers=_headers(),
            )
            assert duplicate_pending.status_code == 200
            assert duplicate_pending.json()["status"] == "pending"

            still_pending = client.get(
                "/api/me/transit-essay",
                headers=_headers(),
            )
            assert still_pending.status_code == 200
            assert still_pending.json()["status"] == "pending"

            assert len(author.calls) == 1
            facts = author.calls[0]
            assert facts["schema_version"] == 1
            assert facts["type"] == TRANSIT_ESSAY_FACTS_TYPE
            assert facts["cache_date"] == "2026-07-12"
            assert len(facts["sky"]["movers"]) > 1
            assert len(facts["same_body_delta"]) > 1
            assert len(facts["aspects"]) > 1
            assert len({item["transit_body"] for item in facts["aspects"]}) > 1
            rendered_facts = json.dumps(facts, sort_keys=True)
            for private_value in (
                "birth_date",
                "1983-11-29",
                "birth_time",
                "22:24:00",
                "place_label",
                "Tokyo, Japan",
                "user-a",
                "token-a",
            ):
                assert private_value not in rendered_facts

            author.release.set()
            assert service.wait_until_idle(timeout_seconds=5.0)
            ready = client.get(
                "/api/me/transit-essay",
                headers=_headers(origin=True),
            )
            assert ready.status_code == 200, ready.text
            payload = ready.json()
            assert payload["status"] == "ready"
            assert payload["cache_date"] == "2026-07-12"
            assert payload["headline"] == "A wider pattern comes into view"
            assert payload["body"]
            assert payload["watchpoints"] == [
                "Compare the tightest contacts before naming a theme."
            ]
            assert payload["epistemic"] == "symbolic study notes, not predictions"
            assert payload["model"] == "test-transit-model"
            assert payload["source"] == "ai-deepseek"
            assert payload["generated_at"] == FIXED_NOW.isoformat()
            assert ready.headers["access-control-allow-origin"] == PERSONAL_ORIGIN
            assert ready.headers["cache-control"] == "private, no-store"

            repeated = client.post(
                "/api/me/transit-essay",
                headers=_headers(),
            )
            assert repeated.status_code == 200
            assert repeated.json() == payload
            assert len(author.calls) == 1
    finally:
        author.release.set()


def test_unsafe_transit_essay_author_becomes_generic_failed_status(
    tmp_path: Path,
) -> None:
    natal_store = MemoryNatalStore((_record(),))
    service = TransitEssayService(
        MemoryTransitEssayStore(),
        _minimal_facts,
        author=UnsafeAuthor(),
        clock=lambda: FIXED_NOW,
    )
    app = _app(tmp_path, natal_store, service)

    with TestClient(app) as client:
        enqueued = client.post(
            "/api/me/transit-essay",
            headers=_headers(),
        )
        assert enqueued.status_code == 200
        assert enqueued.json()["status"] in {"pending", "failed"}
        assert service.wait_until_idle(timeout_seconds=5.0)

        failed = client.get(
            "/api/me/transit-essay",
            headers=_headers(origin=True),
        )
        assert failed.status_code == 200
        assert failed.json() == {
            "schema_version": 1,
            "type": "personal_transit_essay",
            "status": "failed",
            "cache_date": "2026-07-12",
            "detail": "Transit essay generation failed.",
        }
        assert "guaranteed outcome" not in failed.text
        assert "unsafe-test-model" not in failed.text
        assert failed.headers["access-control-allow-origin"] == PERSONAL_ORIGIN
        assert failed.headers["cache-control"] == "private, no-store"
