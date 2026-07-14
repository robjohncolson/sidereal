from __future__ import annotations

from collections.abc import Mapping, Sequence
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
from sidereal.sky_chat import (
    GeneratedSkyChatReply,
    MemorySkyChatStore,
    SKY_CHAT_EPISTEMIC,
    SKY_CHAT_FACTS_TYPE,
    SkyChatFocus,
    SkyChatService,
    build_sky_chat_facts,
)
from sidereal.transit_essay import transit_essay_cache_date
from sidereal.web import create_app


FIXED_NOW = datetime(2026, 7, 13, 14, 30, tzinfo=UTC)
PERSONAL_ORIGIN = "https://aim-dojo.vercel.app"
READY_REPLY = (
    "Stay with the supplied geometry as a reflective study prompt. Compare its "
    "tighter patterns, notice what draws attention, and leave room for more than "
    "one interpretation before choosing a practical response."
)


class TestAuthenticator:
    def authenticate(self, token: str) -> str:
        users = {"token-a": "user-a", "token-b": "user-b"}
        try:
            return users[token]
        except KeyError as exc:
            raise AuthenticationError("invalid test token") from exc


class FixedAuthor:
    model = "test-sky-chat-model"

    def __init__(self, reply: str = READY_REPLY) -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []

    def generate(
        self,
        facts: Mapping[str, Any],
        history: Sequence[Mapping[str, str]],
        message: str,
    ) -> GeneratedSkyChatReply:
        self.calls.append(
            {
                "facts": deepcopy(dict(facts)),
                "history": deepcopy(list(history)),
                "message": message,
            }
        )
        return GeneratedSkyChatReply(self.reply)


class BlockingAuthor(FixedAuthor):
    def __init__(self) -> None:
        super().__init__()
        self.started = Event()
        self.release = Event()

    def generate(
        self,
        facts: Mapping[str, Any],
        history: Sequence[Mapping[str, str]],
        message: str,
    ) -> GeneratedSkyChatReply:
        self.calls.append(
            {
                "facts": deepcopy(dict(facts)),
                "history": deepcopy(list(history)),
                "message": message,
            }
        )
        self.started.set()
        if not self.release.wait(timeout=5.0):
            raise RuntimeError("test Sky Chat author was not released")
        return GeneratedSkyChatReply(self.reply)


class UnsafeAuthor(FixedAuthor):
    def __init__(self) -> None:
        super().__init__("This is a guaranteed outcome that must happen next.")


class CapturingRealFactsBuilder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        record: NatalRecord,
        focus: SkyChatFocus,
        *,
        when: datetime,
    ) -> dict[str, Any]:
        facts = build_sky_chat_facts(record, focus, when=when)
        self.calls.append(deepcopy(facts))
        return facts


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


def _minimal_facts(
    record: NatalRecord,
    focus: SkyChatFocus,
    *,
    when: datetime,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "type": SKY_CHAT_FACTS_TYPE,
        "cache_date": transit_essay_cache_date(record, when),
        "timezone": record.tz,
        "epoch_utc": when.astimezone(UTC).isoformat(),
        "focus": focus.to_dict(),
        "natal_placements_short": [],
        "movers_short": [],
        "aspects": [],
    }


def _app(
    tmp_path: Path,
    natal_store: MemoryNatalStore,
    service: SkyChatService,
) -> Any:
    return create_app(
        db_path=tmp_path / "missing.db",
        charts_dir=tmp_path / "charts",
        natal_store=natal_store,
        authenticator=TestAuthenticator(),
        sky_chat_service=service,
    )


def _headers(token: str = "token-a", *, origin: bool = False) -> dict[str, str]:
    result = {"Authorization": f"Bearer {token}"}
    if origin:
        result["Origin"] = PERSONAL_ORIGIN
    return result


def _request(message: str = "What deserves attention in this sky?") -> dict[str, Any]:
    return {"message": message, "focus": {"kind": "sky"}}


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


def _nested_keys(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        return {
            *(str(key) for key in value),
            *(
                nested
                for item in value.values()
                for nested in _nested_keys(item)
            ),
        }
    if isinstance(value, list | tuple):
        return {nested for item in value for nested in _nested_keys(item)}
    return set()


def test_sky_chat_auth_natal_cors_bad_body_and_unavailable(tmp_path: Path) -> None:
    natal_store = MemoryNatalStore()
    service = SkyChatService(
        MemorySkyChatStore(),
        _minimal_facts,
        clock=lambda: FIXED_NOW,
    )
    app = _app(tmp_path, natal_store, service)

    with TestClient(app) as client:
        for method, kwargs in (
            ("get", {}),
            ("post", {"json": _request()}),
        ):
            unauthorized = getattr(client, method)("/api/me/sky-chat", **kwargs)
            assert unauthorized.status_code == 401
            assert unauthorized.json() == {
                "detail": "Invalid or missing bearer token"
            }
            assert unauthorized.headers["www-authenticate"] == "Bearer"
            assert unauthorized.headers["cache-control"] == "private, no-store"

        invalid = client.get(
            "/api/me/sky-chat",
            headers={"Authorization": "Bearer wrong", "Origin": PERSONAL_ORIGIN},
        )
        assert invalid.status_code == 401
        assert invalid.headers["access-control-allow-origin"] == PERSONAL_ORIGIN
        assert invalid.headers["cache-control"] == "private, no-store"

        for method, kwargs in (
            ("get", {}),
            ("post", {"json": _request()}),
        ):
            missing = getattr(client, method)(
                "/api/me/sky-chat",
                headers=_headers(origin=True),
                **kwargs,
            )
            assert missing.status_code == 404
            assert missing.json() == {"detail": "No natal profile is saved"}
            assert missing.headers["access-control-allow-origin"] == PERSONAL_ORIGIN
            assert missing.headers["cache-control"] == "private, no-store"

        preflight = client.options(
            "/api/me/sky-chat",
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
        assert "Content-Type" in preflight.headers["access-control-allow-headers"]

        natal_store.upsert(_record())
        for kwargs in (
            {},
            {"json": []},
            {"json": {"message": "", "focus": {"kind": "sky"}}},
            {"json": {"message": "Question", "focus": {"kind": "body"}}},
            {
                "json": {
                    "message": "x" * 801,
                    "focus": {"kind": "sky"},
                }
            },
        ):
            bad = client.post(
                "/api/me/sky-chat",
                headers=_headers(origin=True),
                **kwargs,
            )
            assert bad.status_code == 400, bad.text
            assert set(bad.json()) == {"detail"}
            assert bad.headers["access-control-allow-origin"] == PERSONAL_ORIGIN
            assert bad.headers["cache-control"] == "private, no-store"

        malformed = client.post(
            "/api/me/sky-chat",
            content="{bad",
            headers={
                **_headers(origin=True),
                "Content-Type": "application/json",
            },
        )
        assert malformed.status_code == 400
        assert malformed.json() == {
            "detail": "Sky Chat request body must be valid JSON"
        }
        assert malformed.headers["access-control-allow-origin"] == PERSONAL_ORIGIN
        assert malformed.headers["cache-control"] == "private, no-store"

        unavailable = client.post(
            "/api/me/sky-chat",
            json=_request(),
            headers=_headers(origin=True),
        )
        assert unavailable.status_code == 200
        assert unavailable.json() == {
            "schema_version": 1,
            "type": "sky_chat",
            "status": "unavailable",
            "thread_id": None,
            "cache_date": "2026-07-13",
            "turn_id": None,
            "focus": {"kind": "sky"},
            "turns": [],
            "epistemic": SKY_CHAT_EPISTEMIC,
            "remaining_turns": 10,
        }
        assert unavailable.headers["access-control-allow-origin"] == PERSONAL_ORIGIN
        assert unavailable.headers["cache-control"] == "private, no-store"

        empty = client.get(
            "/api/me/sky-chat",
            headers=_headers(origin=True),
        )
        assert empty.status_code == 200
        assert empty.json()["status"] == "unavailable"
        assert empty.json()["turns"] == []
        assert empty.json()["focus"] == {}


def test_sky_chat_pending_to_ready_uses_private_ephemeris_facts(
    tmp_path: Path,
) -> None:
    record = _record()
    natal_store = MemoryNatalStore((record,))
    facts_builder = CapturingRealFactsBuilder()
    author = BlockingAuthor()
    service = SkyChatService(
        MemorySkyChatStore(),
        facts_builder,
        author=author,
        clock=lambda: FIXED_NOW,
    )
    app = _app(tmp_path, natal_store, service)

    with TestClient(app) as client:
        try:
            pending = client.post(
                "/api/me/sky-chat",
                json=_request("How can I study this whole sky?"),
                headers=_headers(origin=True),
            )
            assert pending.status_code == 200, pending.text
            payload = pending.json()
            assert payload["status"] == "pending"
            assert payload["thread_id"]
            assert payload["turn_id"]
            assert payload["focus"] == {"kind": "sky"}
            assert payload["remaining_turns"] == 10
            assert payload["epistemic"] == SKY_CHAT_EPISTEMIC
            assert payload["turns"] == [
                {
                    "role": "user",
                    "text": "How can I study this whole sky?",
                    "at": FIXED_NOW.isoformat(),
                    "focus": {"kind": "sky"},
                }
            ]
            assert pending.headers["access-control-allow-origin"] == PERSONAL_ORIGIN
            assert pending.headers["cache-control"] == "private, no-store"
            assert author.started.wait(timeout=5.0)

            assert len(author.calls) == 1
            call = author.calls[0]
            facts = call["facts"]
            assert facts == facts_builder.calls[0]
            assert facts["type"] == SKY_CHAT_FACTS_TYPE
            assert facts["cache_date"] == "2026-07-13"
            assert facts["focus"] == {"kind": "sky"}
            assert len(facts["aspects"]) <= 8
            assert call["history"] == []
            assert call["message"] == "How can I study this whole sky?"

            forbidden_keys = {
                "birth_date",
                "birth_time",
                "lat",
                "lon",
                "place_label",
                "user_id",
                "email",
                "api_key",
                "authorization",
            }
            assert forbidden_keys.isdisjoint(_nested_keys(facts))
            rendered = json.dumps(facts, sort_keys=True)
            for private_value in (
                record.user_id,
                record.place_label,
                record.birth_date.isoformat(),
                record.birth_time.isoformat(),
                "token-a",
            ):
                assert private_value not in rendered

            author.release.set()
            assert service.wait_until_idle(timeout_seconds=5.0)
            ready = client.get(
                "/api/me/sky-chat",
                params={"thread_id": payload["thread_id"]},
                headers=_headers(origin=True),
            )
            assert ready.status_code == 200
            completed = ready.json()
            assert completed["status"] == "ready"
            assert completed["thread_id"] == payload["thread_id"]
            assert completed["turn_id"] == payload["turn_id"]
            assert completed["remaining_turns"] == 9
            assert completed["turns"][-1] == {
                "role": "assistant",
                "text": READY_REPLY,
                "at": FIXED_NOW.isoformat(),
                "status": "ready",
            }
            assert ready.headers["access-control-allow-origin"] == PERSONAL_ORIGIN
            assert ready.headers["cache-control"] == "private, no-store"
        finally:
            author.release.set()


def test_sky_chat_stale_thread_id_never_crosses_users(tmp_path: Path) -> None:
    natal_store = MemoryNatalStore((_record("user-a"), _record("user-b")))
    service = SkyChatService(
        MemorySkyChatStore(),
        _minimal_facts,
        author=FixedAuthor(),
        clock=lambda: FIXED_NOW,
    )
    app = _app(tmp_path, natal_store, service)

    with TestClient(app) as client:
        first = client.post(
            "/api/me/sky-chat",
            json=_request("User A private question"),
            headers=_headers("token-a"),
        )
        assert first.status_code == 200
        assert service.wait_until_idle(timeout_seconds=5.0)
        a_thread = client.get(
            "/api/me/sky-chat", headers=_headers("token-a")
        ).json()
        assert a_thread["status"] == "ready"
        a_thread_id = a_thread["thread_id"]
        assert a_thread_id

        isolated_get = client.get(
            "/api/me/sky-chat",
            params={"thread_id": a_thread_id},
            headers=_headers("token-b"),
        )
        assert isolated_get.status_code == 200
        assert isolated_get.json()["status"] == "none"
        assert isolated_get.json()["thread_id"] is None
        assert isolated_get.json()["turns"] == []

        b_post = client.post(
            "/api/me/sky-chat",
            json={
                **_request("User B private question"),
                "thread_id": a_thread_id,
            },
            headers=_headers("token-b"),
        )
        assert b_post.status_code == 200
        assert service.wait_until_idle(timeout_seconds=5.0)
        b_thread = client.get(
            "/api/me/sky-chat", headers=_headers("token-b")
        ).json()
        assert b_thread["status"] == "ready"
        assert b_thread["thread_id"] != a_thread_id
        assert "User A private question" not in json.dumps(b_thread)

        stale_post = client.post(
            "/api/me/sky-chat",
            json={
                **_request("User A follows the current day thread"),
                "thread_id": "stale-thread-from-another-day",
            },
            headers=_headers("token-a"),
        )
        assert stale_post.status_code == 200
        assert service.wait_until_idle(timeout_seconds=5.0)
        refreshed_a = client.get(
            "/api/me/sky-chat", headers=_headers("token-a")
        ).json()
        assert refreshed_a["thread_id"] == a_thread_id
        assert "User B private question" not in json.dumps(refreshed_a)
        assert [
            turn["text"] for turn in refreshed_a["turns"] if turn["role"] == "user"
        ] == ["User A private question", "User A follows the current day thread"]


def test_sky_chat_unsafe_reply_becomes_generic_failed_turn(tmp_path: Path) -> None:
    natal_store = MemoryNatalStore((_record(),))
    unsafe = "This is a guaranteed outcome that must happen next."
    service = SkyChatService(
        MemorySkyChatStore(),
        _minimal_facts,
        author=UnsafeAuthor(),
        clock=lambda: FIXED_NOW,
    )
    app = _app(tmp_path, natal_store, service)

    with TestClient(app) as client:
        enqueued = client.post(
            "/api/me/sky-chat",
            json=_request(),
            headers=_headers(origin=True),
        )
        assert enqueued.status_code == 200
        assert enqueued.json()["status"] in {"pending", "failed"}
        assert service.wait_until_idle(timeout_seconds=5.0)

        failed = client.get(
            "/api/me/sky-chat",
            headers=_headers(origin=True),
        )
        assert failed.status_code == 200
        payload = failed.json()
        assert payload["status"] == "failed"
        assert payload["remaining_turns"] == 10
        assert payload["turns"][-1]["role"] == "assistant"
        assert payload["turns"][-1]["status"] == "failed"
        assert payload["turns"][-1]["text"] == ""
        assert unsafe not in failed.text
        assert "test-sky-chat-model" not in failed.text
        assert failed.headers["access-control-allow-origin"] == PERSONAL_ORIGIN
        assert failed.headers["cache-control"] == "private, no-store"


def test_sky_chat_day_cap_is_top_level_429_after_ten_successes(
    tmp_path: Path,
) -> None:
    natal_store = MemoryNatalStore((_record(),))
    author = FixedAuthor()
    service = SkyChatService(
        MemorySkyChatStore(),
        _minimal_facts,
        author=author,
        clock=lambda: FIXED_NOW,
    )
    app = _app(tmp_path, natal_store, service)

    with TestClient(app) as client:
        thread_id: str | None = None
        for index in range(10):
            response = client.post(
                "/api/me/sky-chat",
                json={
                    **_request(f"Question {index + 1}"),
                    **({"thread_id": thread_id} if thread_id is not None else {}),
                },
                headers=_headers(),
            )
            assert response.status_code == 200, response.text
            thread_id = response.json()["thread_id"]
            assert service.wait_until_idle(timeout_seconds=5.0)
            current = client.get(
                "/api/me/sky-chat", headers=_headers()
            ).json()
            assert current["status"] == "ready"
            assert current["remaining_turns"] == 9 - index

        same_geometry = client.post(
            "/api/me/natal",
            json={**_natal_payload(), "place_label": "RENAMED PRIVATE PLACE"},
            headers=_headers(),
        )
        assert same_geometry.status_code == 200, same_geometry.text
        preserved = client.get(
            "/api/me/sky-chat",
            headers=_headers(),
        ).json()
        assert preserved["thread_id"] == thread_id
        assert len(preserved["turns"]) == 20

        limited = client.post(
            "/api/me/sky-chat",
            json={**_request("Question 11"), "thread_id": thread_id},
            headers=_headers(origin=True),
        )
        assert limited.status_code == 429
        payload = limited.json()
        assert payload["status"] == "limited"
        assert payload["remaining_turns"] == 0
        assert payload["thread_id"] == thread_id
        assert "detail" not in payload
        assert "Question 11" not in limited.text
        assert len(payload["turns"]) == 20
        assert len(author.calls) == 10
        assert limited.headers["access-control-allow-origin"] == PERSONAL_ORIGIN
        assert limited.headers["cache-control"] == "private, no-store"

        deleted = client.delete("/api/me/natal", headers=_headers())
        assert deleted.status_code == 204
        restored = client.post(
            "/api/me/natal",
            json=_natal_payload(),
            headers=_headers(),
        )
        assert restored.status_code == 200, restored.text
        still_limited = client.post(
            "/api/me/sky-chat",
            json=_request("Deletion must not reset the day allowance"),
            headers=_headers(),
        )
        assert still_limited.status_code == 429
        assert still_limited.json()["status"] == "limited"
        assert still_limited.json()["remaining_turns"] == 0
        assert len(author.calls) == 10
