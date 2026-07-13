from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock
from typing import Any, Mapping

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("swisseph")

from fastapi.testclient import TestClient

from sidereal.auth import AuthenticationError
from sidereal.ephemeris import EphemerisError
from sidereal.interpret.store import InterpretationStoreError
from sidereal.natal import MemoryNatalStore, NatalRecord, natal_record_from_payload
from sidereal.transit_essay import (
    GeneratedTransitEssay,
    MemoryTransitEssayStore,
    SKY_BRIEF_EPISTEMIC,
    TransitEssayService,
    TransitEssayStoreError,
    format_sky_brief_text,
    natal_fingerprint,
    transit_essay_cache_date,
)
from sidereal.web import create_app


FIXED_NOW = datetime(2026, 7, 13, 14, 30, tzinfo=UTC)
PERSONAL_ORIGIN = "https://aim-dojo.vercel.app"


def _record(user_id: str = "user-a") -> NatalRecord:
    return natal_record_from_payload(
        user_id,
        {
            "birth_date": "1983-11-29",
            "birth_time": "22:24:00",
            "time_unknown": False,
            "tz": "America/New_York",
            "lat": 40.7128,
            "lon": -74.006,
            "place_label": "PRIVATE PLACE LABEL",
        },
        updated_at=FIXED_NOW,
    )


def _facts(record: NatalRecord, *, when: datetime) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "type": "transit_essay_facts",
        "cache_date": transit_essay_cache_date(record, when),
        "timezone": record.tz,
        "epoch_utc": when.astimezone(UTC).isoformat(),
        "natal": {
            "time_unknown": record.time_unknown,
            "tz": record.tz,
            "placements": [
                {
                    "body": "sun",
                    "sign": "scorpio",
                    "degree_in_sign": 12.34,
                    "retro": False,
                    "house": 5,
                },
                {
                    "body": "asc",
                    "sign": "gemini",
                    "degree_in_sign": 2.05,
                    "house": 1,
                },
            ],
            "lat": 51.5007123,
            "lon": -0.1246123,
            "email": "private-natal@example.invalid",
        },
        "sky": {
            "movers": [
                {
                    "body": "mars",
                    "sign": "leo",
                    "degree_in_sign": 4.08,
                    "retro": True,
                    "natal_house": 7,
                }
            ],
            "email": "private-sky@example.invalid",
        },
        "aspects": [
            {
                "transit_body": "mars",
                "natal_point": "moon",
                "aspect_id": "square",
                "orb": 1.17,
                "applying": True,
            },
            {
                "transit_body": "sun",
                "natal_point": "mc",
                "aspect_id": "conjunction",
                "orb": 0.0,
                "applying": None,
            },
        ],
        "same_body_delta": [{"body": "sun", "delta_deg": 47.16}],
        "lat": 51.5007123,
        "lon": -0.1246123,
        "email": "private-user@example.invalid",
        "user_id": record.user_id,
        "place_label": record.place_label,
    }


def _ready_essay() -> dict[str, Any]:
    return {
        "status": "ready",
        "headline": "A measured view of today’s sky",
        "body": "Hold the listed contacts as symbolic prompts.\r\nContext still matters.",
        "watchpoints": ["Notice the tightest contact before naming a theme."],
    }


def test_format_sky_brief_has_canonical_sections_ready_note_and_no_private_fields() -> None:
    record = replace(_record(), time_unknown=True, birth_time=None)
    facts = _facts(record, when=FIXED_NOW)

    text = format_sky_brief_text(facts, essay=_ready_essay())

    assert text.startswith(
        "# Moon Chorus sky brief\n"
        "date: 2026-07-13 (America/New_York)\n"
        f"epoch_utc: {FIXED_NOW.isoformat()}\n"
    )
    assert f"epistemic: {SKY_BRIEF_EPISTEMIC}" in text
    assert "## Natal placements" in text
    assert "Sun · Scorpio · 12.3° · house 5" in text
    assert "Ascendant · Gemini · 2.0° · house 1" in text
    assert "Time unknown · houses and angles may be omitted or marked uncertain." in text
    assert "## Today’s movers (transit)" in text
    assert "Mars · Leo · 4.1° · Rx · natal house 7" in text
    assert "## Transit → natal contacts" in text
    assert "Transit Mars square natal Moon · orb 1.2° · applying" in text
    assert "Transit Sun conjunction natal Midheaven · orb 0.0° · exact" in text
    assert "## Same-body deltas (optional short list)" in text
    assert "Sun · transit vs natal separation 47.2°" in text
    assert "## Today’s sky note" in text
    assert "headline: A measured view of today’s sky" in text
    assert "Hold the listed contacts as symbolic prompts.\nContext still matters." in text
    assert "watchpoints:\n- Notice the tightest contact" in text
    assert "\r" not in text
    assert text.endswith("\n")

    for private_value in (
        "51.5007123",
        "-0.1246123",
        "40.7128",
        "-74.006",
        "private-natal@example.invalid",
        "private-sky@example.invalid",
        "private-user@example.invalid",
        record.user_id,
        record.place_label,
    ):
        assert private_value not in text


def test_format_sky_brief_omits_non_ready_essay_appendix() -> None:
    facts = _facts(_record(), when=FIXED_NOW)

    text = format_sky_brief_text(
        facts,
        essay={
            "status": "pending",
            "headline": "MUST NOT APPEAR",
            "body": "MUST NOT APPEAR",
            "watchpoints": [],
        },
    )

    assert "## Today’s sky note" not in text
    assert "MUST NOT APPEAR" not in text


class CountingFactsBuilder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.last_result: dict[str, Any] | None = None
        self._lock = Lock()

    def __call__(self, record: NatalRecord, *, when: datetime) -> dict[str, Any]:
        with self._lock:
            self.calls.append((record.user_id, when.isoformat()))
        result = _facts(record, when=when)
        self.last_result = result
        return result


class BlockingFactsBuilder(CountingFactsBuilder):
    def __init__(self) -> None:
        super().__init__()
        self.started = Event()
        self.release = Event()

    def __call__(self, record: NatalRecord, *, when: datetime) -> dict[str, Any]:
        result = super().__call__(record, when=when)
        self.started.set()
        if not self.release.wait(timeout=5.0):
            raise RuntimeError("test facts builder was not released")
        return result


class FixedEssayAuthor:
    model = "cache-reuse-test-model"

    def generate(self, facts: Mapping[str, Any]) -> GeneratedTransitEssay:
        assert facts["type"] == "transit_essay_facts"
        return GeneratedTransitEssay(
            headline="A shared daily fact snapshot",
            body=(
                "The same daily facts can support both a plain-text brief and a "
                "private symbolic essay without repeating the chart calculation. "
                "Context and reflection remain central to this study note."
            ),
            watchpoints=("Notice how the closest contact changes emphasis.",),
        )


def test_brief_facts_cache_is_keyed_copied_invalidated_and_single_flight() -> None:
    record = _record()
    builder = CountingFactsBuilder()
    service = TransitEssayService(
        MemoryTransitEssayStore(),
        builder,
        clock=lambda: FIXED_NOW,
    )

    first = service.brief(record)
    assert first["status"] == "ready"
    assert len(builder.calls) == 1
    assert builder.last_result is not None
    builder.last_result["natal"]["placements"][0]["body"] = "poisoned"
    assert "Poisoned" not in service.brief(record)["text"]
    assert len(builder.calls) == 1

    changed = replace(record, birth_time=record.birth_time.replace(minute=25))
    assert service.brief(changed)["status"] == "ready"
    assert len(builder.calls) == 2
    assert service.brief(_record("user-b"))["status"] == "ready"
    assert len(builder.calls) == 3

    service.invalidate_user(record.user_id)
    assert service.brief(record)["status"] == "ready"
    assert len(builder.calls) == 4

    blocking = BlockingFactsBuilder()
    coordinated = TransitEssayService(
        MemoryTransitEssayStore(),
        blocking,
        clock=lambda: FIXED_NOW,
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(coordinated.brief, record)
        assert blocking.started.wait(timeout=2.0)
        second_future = pool.submit(coordinated.brief, record)
        blocking.release.set()
        assert first_future.result(timeout=5.0)["status"] == "ready"
        assert second_future.result(timeout=5.0)["status"] == "ready"
    assert len(blocking.calls) == 1


def test_brief_facts_cache_is_reused_by_essay_ensure() -> None:
    builder = CountingFactsBuilder()
    service = TransitEssayService(
        MemoryTransitEssayStore(),
        builder,
        author=FixedEssayAuthor(),
        clock=lambda: FIXED_NOW,
    )
    service.start()
    try:
        assert service.brief(_record())["status"] == "ready"
        assert service.ensure(_record())["status"] == "pending"
        assert service.wait_until_idle(timeout_seconds=5.0)
        assert service.get(_record())["status"] == "ready"
        assert len(builder.calls) == 1
    finally:
        service.close()


def test_brief_facts_cache_rolls_at_natal_civil_midnight() -> None:
    builder = CountingFactsBuilder()
    now = [datetime(2026, 7, 14, 3, 59, 59, tzinfo=UTC)]
    service = TransitEssayService(
        MemoryTransitEssayStore(),
        builder,
        clock=lambda: now[0],
    )

    before = service.brief(_record())
    assert before["cache_date"] == "2026-07-13"
    now[0] = datetime(2026, 7, 14, 4, 0, tzinfo=UTC)
    after = service.brief(_record())
    assert after["cache_date"] == "2026-07-14"
    assert len(builder.calls) == 2


class ReadFailingEssayStore(MemoryTransitEssayStore):
    def get(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint_value: str,
    ) -> None:
        del user_id, cache_date, natal_fingerprint_value
        raise TransitEssayStoreError("PRIVATE STORE DETAIL")


@pytest.mark.parametrize(
    "error",
    (
        EphemerisError("ephemeris unavailable"),
        InterpretationStoreError("catalog unavailable"),
    ),
)
def test_brief_soft_fails_geometry_or_catalog_errors(error: Exception) -> None:
    def failing_builder(record: NatalRecord, *, when: datetime) -> dict[str, Any]:
        del record, when
        raise error

    payload = TransitEssayService(
        MemoryTransitEssayStore(),
        failing_builder,
        clock=lambda: FIXED_NOW,
    ).brief(_record())

    assert payload == {
        "status": "failed",
        "cache_date": "2026-07-13",
        "timezone": "America/New_York",
        "text": "",
        "has_essay": False,
        "epistemic": SKY_BRIEF_EPISTEMIC,
    }


def test_brief_omits_appendix_when_optional_essay_store_read_fails() -> None:
    payload = TransitEssayService(
        ReadFailingEssayStore(),
        _facts,
        clock=lambda: FIXED_NOW,
    ).brief(_record())

    assert payload["status"] == "ready"
    assert payload["has_essay"] is False
    assert "## Today’s sky note" not in payload["text"]


class TestAuthenticator:
    def authenticate(self, token: str) -> str:
        users = {"token-a": "user-a", "token-b": "user-b"}
        try:
            return users[token]
        except KeyError as exc:
            raise AuthenticationError("invalid test token") from exc


class GuardedTransitEssayService(TransitEssayService):
    def ensure(self, record: NatalRecord) -> dict[str, Any]:
        del record
        raise AssertionError("sky brief GET must not enqueue an essay")


class StubPersonalSkyCache:
    def __init__(self) -> None:
        self.invalidated: list[str] = []

    def invalidate(self, user_id: str) -> None:
        self.invalidated.append(user_id)

    def get(self, record: NatalRecord) -> dict[str, Any]:
        return {"schema_version": 2, "type": "skypack", "natal_id": record.user_id}


def _headers(token: str = "token-a", *, origin: bool = False) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if origin:
        headers["Origin"] = PERSONAL_ORIGIN
    return headers


def _natal_payload() -> dict[str, Any]:
    return {
        "birth_date": "1983-11-29",
        "birth_time": "22:24:00",
        "time_unknown": False,
        "tz": "America/New_York",
        "lat": 40.7128,
        "lon": -74.006,
        "place_label": "PRIVATE PLACE LABEL",
    }


def test_sky_brief_route_auth_chart_gate_ready_essay_privacy_and_invalidation(
    tmp_path: Path,
) -> None:
    record = _record()
    natal_store = MemoryNatalStore((record,))
    essay_store = MemoryTransitEssayStore()
    builder = CountingFactsBuilder()
    fingerprint = natal_fingerprint(record)
    cache_date = transit_essay_cache_date(record, FIXED_NOW)
    essay_store.ensure_pending(record.user_id, cache_date, fingerprint)
    essay_store.mark_ready(
        record.user_id,
        cache_date,
        fingerprint,
        GeneratedTransitEssay(
            headline="A measured view of today’s sky",
            body="The current contacts can be held as reflective symbolic prompts.",
            watchpoints=("Notice the tightest contact first.",),
        ),
        model="fixture-model",
        generated_at=FIXED_NOW,
    )
    service = GuardedTransitEssayService(
        essay_store,
        builder,
        clock=lambda: FIXED_NOW,
    )
    app = create_app(
        db_path=tmp_path / "missing.db",
        charts_dir=tmp_path / "charts",
        natal_store=natal_store,
        authenticator=TestAuthenticator(),
        personal_sky_cache=StubPersonalSkyCache(),
        transit_essay_service=service,
    )

    with TestClient(app) as client:
        unauthorized = client.get("/api/me/sky-brief")
        assert unauthorized.status_code == 401
        assert unauthorized.headers["www-authenticate"] == "Bearer"
        assert unauthorized.headers["cache-control"] == "private, no-store"

        no_chart = client.get("/api/me/sky-brief", headers=_headers("token-b"))
        assert no_chart.status_code == 404
        assert no_chart.json() == {"detail": "No natal profile is saved"}

        response = client.get(
            "/api/me/sky-brief",
            headers=_headers(origin=True),
        )
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["access-control-allow-origin"] == PERSONAL_ORIGIN
        payload = response.json()
        assert set(payload) == {
            "status",
            "cache_date",
            "timezone",
            "text",
            "has_essay",
            "epistemic",
        }
        assert payload["status"] == "ready"
        assert payload["cache_date"] == "2026-07-13"
        assert payload["timezone"] == record.tz
        assert payload["has_essay"] is True
        assert payload["epistemic"] == SKY_BRIEF_EPISTEMIC
        assert "## Today’s sky note" in payload["text"]
        assert len(builder.calls) == 1
        assert client.get(
            "/api/me/sky-brief", headers=_headers()
        ).json() == payload
        assert len(builder.calls) == 1

        for private_value in (
            "51.5007123",
            "-0.1246123",
            "40.7128",
            "-74.006",
            "private-user@example.invalid",
            record.user_id,
            record.place_label,
        ):
            assert private_value not in payload["text"]

        # Even a same-fingerprint save invalidates both the ready essay and facts.
        saved = client.post(
            "/api/me/natal",
            json=_natal_payload(),
            headers=_headers(),
        )
        assert saved.status_code == 200, saved.text
        after_save = client.get("/api/me/sky-brief", headers=_headers()).json()
        assert after_save["status"] == "ready"
        assert after_save["has_essay"] is False
        assert "## Today’s sky note" not in after_save["text"]
        assert len(builder.calls) == 2

        deleted = client.delete("/api/me/natal", headers=_headers())
        assert deleted.status_code == 204
        natal_store.upsert(record)
        after_delete = client.get("/api/me/sky-brief", headers=_headers())
        assert after_delete.status_code == 200
        assert len(builder.calls) == 3


class DeleteFailingEssayStore(MemoryTransitEssayStore):
    def delete_user(self, user_id: str) -> None:
        del user_id
        raise TransitEssayStoreError("PRIVATE DELETE DETAIL")


def test_natal_save_commits_when_optional_essay_invalidation_fails(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    record = _record()
    natal_store = MemoryNatalStore((record,))
    builder = CountingFactsBuilder()
    service = TransitEssayService(
        DeleteFailingEssayStore(),
        builder,
        clock=lambda: FIXED_NOW,
    )
    assert service.brief(record)["status"] == "ready"
    assert len(builder.calls) == 1
    app = create_app(
        db_path=tmp_path / "missing.db",
        charts_dir=tmp_path / "charts",
        natal_store=natal_store,
        authenticator=TestAuthenticator(),
        personal_sky_cache=StubPersonalSkyCache(),
        transit_essay_service=service,
    )
    same_fingerprint_payload = _natal_payload()

    with TestClient(app) as client, caplog.at_level("WARNING"):
        saved = client.post(
            "/api/me/natal",
            json=same_fingerprint_payload,
            headers=_headers(),
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["birth_time"] == "22:24:00"
        assert natal_store.get(record.user_id).birth_time.isoformat() == "22:24:00"
        assert "PRIVATE DELETE DETAIL" not in caplog.text
        assert "TransitEssayStoreError" in caplog.text

        refreshed = client.get("/api/me/sky-brief", headers=_headers())
        assert refreshed.status_code == 200
        assert refreshed.json()["status"] == "ready"
        # invalidate_user clears facts in finally even when essay deletion fails.
        assert len(builder.calls) == 2
