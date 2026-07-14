from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time
import json
from pathlib import Path
from types import SimpleNamespace
from threading import Event
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from sidereal.interpret.ai_seed import DeepSeekConfig
from sidereal.natal import NatalRecord
from sidereal.sky_chat import (
    DeepSeekSkyChatAuthor,
    GeneratedSkyChatReply,
    MemorySkyChatStore,
    SKY_CHAT_FACTS_TYPE,
    SKY_CHAT_MAX_REPLIES_PER_DAY,
    SQLiteSkyChatStore,
    SkyChatFocus,
    SkyChatRateLimitError,
    SkyChatService,
    SkyChatTurn,
    SkyChatValidationError,
    build_sky_chat_facts,
    normalize_sky_chat_focus,
    validate_sky_chat_message,
    validate_sky_chat_reply,
)
from sidereal.transit_essay import build_transit_essay_facts, natal_fingerprint


WHEN = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
FINGERPRINT_A = "a" * 64
FINGERPRINT_B = "b" * 64


def _record(*, time_unknown: bool = False) -> NatalRecord:
    return NatalRecord(
        user_id="private-user",
        birth_date=date(1983, 11, 29),
        birth_time=None if time_unknown else time(22, 24),
        time_unknown=time_unknown,
        tz="America/New_York",
        lat=40.7128,
        lon=-74.006,
        place_label="DO NOT LEAK THIS PRIVATE PLACE",
        updated_at=WHEN,
    )


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        return {
            *(str(key) for key in value),
            *(key for item in value.values() for key in _all_keys(item)),
        }
    if isinstance(value, (list, tuple)):
        return {key for item in value for key in _all_keys(item)}
    return set()


def _minimal_facts() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "type": SKY_CHAT_FACTS_TYPE,
        "cache_date": "2026-07-13",
        "timezone": "UTC",
        "epoch_utc": WHEN.isoformat(),
        "focus": {
            "kind": "aspect",
            "body": "mars",
            "natal_point": "moon",
            "aspect_id": "square",
        },
        "natal_placements_short": [],
        "movers_short": [],
        "aspects": [
            {
                "transit_body": "mars",
                "natal_point": "moon",
                "aspect_id": "square",
                "separation": 89.5,
                "orb": 0.5,
                "orb_limit": 7.0,
                "applying": True,
            }
        ],
    }


def _service_facts(
    record: NatalRecord,
    focus: SkyChatFocus,
    *,
    when: datetime,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "type": SKY_CHAT_FACTS_TYPE,
        "cache_date": when.astimezone(ZoneInfo(record.tz)).date().isoformat(),
        "timezone": record.tz,
        "epoch_utc": when.astimezone(UTC).isoformat(),
        "focus": focus.to_dict(),
        "natal_placements_short": [],
        "movers_short": [],
        "aspects": [],
    }


class RecordingTransport:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []

    def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        self.calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "payload": dict(payload),
                "timeout_seconds": timeout_seconds,
            }
        )
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": json.dumps({"reply": self.reply}),
                    },
                }
            ]
        }


def test_focus_and_message_validation_canonicalize_only_server_selectors() -> None:
    focus = normalize_sky_chat_focus(
        {
            "kind": " Aspect ",
            "body": "Mars",
            "natal_point": "Moon",
            "aspect_id": "Square",
            "label": "client display only",
        }
    )
    assert focus.to_dict() == {
        "kind": "aspect",
        "body": "mars",
        "natal_point": "moon",
        "aspect_id": "square",
    }
    assert validate_sky_chat_message("  What is known here?  ") == "What is known here?"

    with pytest.raises(SkyChatValidationError, match="at most 800"):
        validate_sky_chat_message("x" * 801)
    with pytest.raises(SkyChatValidationError, match="control"):
        validate_sky_chat_message("hello\x00world")
    with pytest.raises(SkyChatValidationError, match="natal_point"):
        normalize_sky_chat_focus({"kind": "natal", "natal_point": "desc"})
    with pytest.raises(SkyChatValidationError, match="unsupported focus field"):
        normalize_sky_chat_focus({"kind": "sky", "lat": 40.0})

    service = SkyChatService(
        MemorySkyChatStore(),
        _service_facts,
        clock=lambda: WHEN,
    )
    with pytest.raises(SkyChatValidationError, match="current natal civil day"):
        service.post(
            _record(),
            {
                "message": "Try to open a second day allowance",
                "focus": {"kind": "sky"},
                "when": "2026-07-14T12:00:00Z",
            },
        )


def test_focus_fact_packets_are_private_capped_and_keep_selected_contact() -> None:
    record = _record()
    complete = build_transit_essay_facts(record, when=WHEN, max_aspects=143)
    assert len(complete["aspects"]) > 24
    below_essay_cut = complete["aspects"][-1]
    aspect_focus = {
        "kind": "aspect",
        "body": below_essay_cut["transit_body"],
        "natal_point": below_essay_cut["natal_point"],
        "aspect_id": below_essay_cut["aspect_id"],
        "label": record.place_label,
    }

    aspect = build_sky_chat_facts(record, aspect_focus, when=WHEN)
    body = build_sky_chat_facts(record, {"kind": "body", "body": "mars"}, when=WHEN)
    natal = build_sky_chat_facts(
        record,
        {"kind": "natal", "natal_point": "moon"},
        when=WHEN,
    )
    sky = build_sky_chat_facts(record, {"kind": "sky"}, when=WHEN)

    assert aspect["type"] == SKY_CHAT_FACTS_TYPE
    assert aspect["focus_aspect"]["orb"] == below_essay_cut["orb"]
    assert aspect["aspects"][0] == aspect["focus_aspect"]
    assert len(aspect["neighbor_aspects"]) <= 4
    assert len(aspect["aspects"]) <= 5
    assert len(body["aspects"]) <= 6
    assert all(item["transit_body"] == "mars" for item in body["aspects"])
    assert len(natal["aspects"]) <= 6
    assert all(item["natal_point"] == "moon" for item in natal["aspects"])
    assert len(sky["aspects"]) == 8
    assert tuple(item["body"] for item in sky["luminaries"]["transit"]) == (
        "sun",
        "moon",
    )

    private_keys = {
        "user_id",
        "birth_date",
        "birth_time",
        "lat",
        "lon",
        "place_label",
        "email",
        "natal_fingerprint",
        "api_key",
    }
    assert private_keys.isdisjoint(_all_keys(aspect))
    rendered = json.dumps(aspect, sort_keys=True)
    for private_value in (
        record.user_id,
        record.place_label,
        record.birth_date.isoformat(),
        str(record.lat),
        str(record.lon),
    ):
        assert private_value not in rendered


def test_sign_facts_use_only_ready_shared_summary_and_unknown_angles_are_rejected() -> None:
    class Catalog:
        def __init__(self, status: str) -> None:
            self.status = status

        def get(self, entry_id: str) -> Any:
            if entry_id != "sign:leo":
                return None
            return SimpleNamespace(
                status=self.status,
                summary="A shared Leo catalog summary.",
            )

    ready = build_sky_chat_facts(
        _record(),
        {"kind": "sign", "sign": "leo"},
        when=WHEN,
        store=Catalog("ready"),
    )
    stub = build_sky_chat_facts(
        _record(),
        {"kind": "sign", "sign": "leo"},
        when=WHEN,
        store=Catalog("stub"),
    )
    assert ready["sign_seed_summary"] == "A shared Leo catalog summary."
    assert "sign_seed_summary" not in stub
    assert ready["aspects"] == []

    with pytest.raises(SkyChatValidationError, match="unavailable"):
        build_sky_chat_facts(
            _record(time_unknown=True),
            {"kind": "natal", "natal_point": "asc"},
            when=WHEN,
        )


def test_reply_validator_rejects_banned_and_invented_geometry() -> None:
    facts = _minimal_facts()
    allowed = validate_sky_chat_reply(
        {
            "reply": (
                "Transit Mars square natal Moon is the contact in this packet. "
                "It can be held as a reflective tension between movement and the "
                "fixed lunar point, without forcing a single conclusion."
            )
        },
        facts,
    )
    assert allowed.reply.startswith("Transit Mars")

    with pytest.raises(SkyChatValidationError, match="banned fragment"):
        validate_sky_chat_reply(
            {"reply": "You will receive a guaranteed outcome from this contact."},
            facts,
        )
    with pytest.raises(SkyChatValidationError, match="absent"):
        validate_sky_chat_reply(
            {
                "reply": (
                    "Transit Venus trine natal Sun is presented as a concrete "
                    "contact even though it is not in the supplied packet."
                )
            },
            facts,
        )
    empty = {**facts, "aspects": []}
    for invented in (
        "A square links transit Mars to natal Moon.",
        "A square links Venus to Sun.",
        "The Venus-Sun connection forms a square.",
        "Transit Mars makes a square aspect to natal Moon.",
        "The transit Mars–natal Moon square is exact.",
        "Natal Moon is squared by transit Mars.",
    ):
        with pytest.raises(SkyChatValidationError, match="absent"):
            validate_sky_chat_reply({"reply": invented}, empty)
    for invented in (
        "Mars is in Leo now.",
        "Transit Mars lies in Leo.",
        "Mars rests in Leo.",
        "Mars enters Leo.",
        "Leo contains transit Mars.",
        "Transit Mars can be found in Leo.",
        "Transit Mars resides in Virgo.",
        "Transit Mars is located in Virgo.",
        "Virgo is occupied by transit Mars.",
        "Mars is at 10 degrees Leo.",
        "Transit Mars occupies Leo now.",
        "Natal Moon is in Gemini.",
        "Mars is retrograde now.",
        "Mars has turned retrograde.",
        "Mars stations direct.",
        "Transit Mars is moving backward.",
        "Transit Mars is stationing retrograde.",
        "The orb is 0.2 degrees and applying.",
        "The contact is 9.9 degrees from exact.",
        "The square is 9.9 degrees wide.",
        "The square is tightening.",
        "Transit Mars square natal Moon is exact.",
        "Transit Mars square natal Moon has a 2 degree orb.",
        "Transit Venus forms a 90-degree angle with natal Sun.",
    ):
        with pytest.raises(SkyChatValidationError, match="absent"):
            validate_sky_chat_reply({"reply": invented}, empty)

    grounded = {
        **facts,
        "movers_short": [
            {"body": "mars", "sign": "leo", "degree_in_sign": 4.0, "retro": True}
        ],
        "natal_placements_short": [
            {"body": "moon", "sign": "gemini", "degree_in_sign": 8.0, "retro": False}
        ],
    }
    grounded_reply = validate_sky_chat_reply(
        {
            "reply": (
                "Transit Mars is in Leo. Transit Mars is retrograde. "
                "Natal Moon is in Gemini. The orb is 0.5 degrees and applying."
            )
        },
        grounded,
    )
    assert grounded_reply.reply.startswith("Transit Mars")
    grounded_variants = validate_sky_chat_reply(
        {
            "reply": (
                "Transit Mars is located in Leo. Leo is occupied by transit Mars. "
                "Transit Mars is at 4 degrees Leo. Transit Mars is stationing "
                "retrograde. Transit Mars square natal Moon has a 0.5 degree orb. "
                "Transit Mars forms a 89.5-degree angle with natal Moon."
            )
        },
        grounded,
    )
    assert grounded_variants.reply.startswith("Transit Mars")
    exact = validate_sky_chat_reply(
        {"reply": "Transit Mars square natal Moon is exact."},
        {
            **grounded,
            "aspects": [{**grounded["aspects"][0], "orb": 0.0}],
        },
    )
    assert exact.reply.endswith("exact.")
    reversed_pair = validate_sky_chat_reply(
        {
            "reply": (
                "The Moon–Mars square has an orb of 0.5 degrees and is applying."
            )
        },
        grounded,
    )
    assert reversed_pair.reply.startswith("The Moon–Mars")
    ordinary_gerund = validate_sky_chat_reply(
        {"reply": "Applying this insight can help you reflect."},
        {**facts, "aspects": []},
    )
    assert ordinary_gerund.reply.startswith("Applying")
    conjunction_gerund = validate_sky_chat_reply(
        {"reply": "Pause and applying this insight may help."},
        {**facts, "aspects": []},
    )
    assert conjunction_gerund.reply.startswith("Pause")

    multiple_contacts = {
        **facts,
        "aspects": [
            *facts["aspects"],
            {
                "transit_body": "venus",
                "natal_point": "sun",
                "aspect_id": "trine",
                "separation": 122.0,
                "orb": 2.0,
                "orb_limit": 7.0,
                "applying": False,
            },
        ],
    }
    for laundered in (
        "Transit Mars square natal Moon has an orb of 2.0 degrees.",
        "Transit Mars square natal Moon is separating.",
        "Transit Mars square natal Moon has an orb of 9.9 degrees.",
        (
            "Transit Mars square natal Moon is separating, while transit Venus "
            "trine natal Sun is applying."
        ),
        (
            "Transit Mars square natal Moon has an orb of 2 degrees, while "
            "transit Venus trine natal Sun has an orb of 0.5 degrees."
        ),
    ):
        with pytest.raises(SkyChatValidationError, match="absent"):
            validate_sky_chat_reply({"reply": laundered}, multiple_contacts)

    grounded_multiple = validate_sky_chat_reply(
        {
            "reply": (
                "Transit Mars square natal Moon has an orb of 0.5 degrees and is "
                "applying, while transit Venus trine natal Sun has an orb of 2 "
                "degrees and is separating."
            )
        },
        multiple_contacts,
    )
    assert grounded_multiple.reply.startswith("Transit Mars")

    with pytest.raises(SkyChatValidationError, match="absent"):
        validate_sky_chat_reply(
            {
                "reply": (
                    "There is a trine between transit Venus and natal Sun, "
                    "although that contact is absent from this packet."
                )
            },
            facts,
        )


def test_deepseek_author_sends_facts_last_eight_history_and_message_without_key() -> None:
    facts = _minimal_facts()
    secret = "server-only-sky-chat-secret"
    reply = (
        "Transit Mars square natal Moon is the listed contact. Its current orb "
        "can be studied as a precise symbolic tension while leaving room for "
        "context, choice, and more than one interpretation."
    )
    transport = RecordingTransport(reply)
    author = DeepSeekSkyChatAuthor(
        DeepSeekConfig(
            api_key=secret,
            base_url="https://deepseek.example",
            model="deepseek-v4-flash",
            timeout_seconds=4,
        ),
        transport=transport,
    )
    history = tuple(
        {"role": "user" if index % 2 == 0 else "assistant", "text": f"turn {index}"}
        for index in range(10)
    )

    generated = author.generate(facts, history, "What is this contact showing?")

    assert generated.reply == reply
    assert len(transport.calls) == 1
    call = transport.calls[0]
    sent = json.loads(call["payload"]["messages"][1]["content"])
    assert sent["facts"] == facts
    assert sent["history"] == list(history[-8:])
    assert sent["message"] == "What is this contact showing?"
    assert call["headers"]["Authorization"] == f"Bearer {secret}"
    assert secret not in json.dumps(call["payload"], sort_keys=True)
    assert secret not in repr(author)


@pytest.mark.parametrize("backend", ("memory", "sqlite"))
def test_thread_store_roundtrip_isolation_failure_recovery_and_day_cap(
    backend: str,
    tmp_path: Path,
) -> None:
    store = (
        MemorySkyChatStore()
        if backend == "memory"
        else SQLiteSkyChatStore(tmp_path / "sidereal.db")
    )
    focus = SkyChatFocus(kind="sky")
    try:
        thread = store.ensure_thread("user-a", "2026-07-13", FINGERPRINT_A)
        isolated = store.ensure_thread("user-a", "2026-07-13", FINGERPRINT_B)
        assert thread.thread_id != isolated.thread_id

        failed_turn = SkyChatTurn(
            turn_id="failed-turn",
            role="user",
            text="First question",
            at=WHEN,
            focus=focus,
            epoch=WHEN,
        )
        thread = store.append_user_turn(
            "user-a", "2026-07-13", FINGERPRINT_A, failed_turn
        )
        assert thread.pending_turn_id == "failed-turn"
        thread = store.mark_failed(
            "user-a",
            "2026-07-13",
            FINGERPRINT_A,
            "failed-turn",
            at=WHEN,
        )
        assert thread.status == "failed"
        assert thread.success_count == 0
        assert thread.turns[-1].text == ""

        for index in range(SKY_CHAT_MAX_REPLIES_PER_DAY):
            turn_id = f"ready-{index}"
            user_turn = SkyChatTurn(
                turn_id=turn_id,
                role="user",
                text=f"Question {index}",
                at=WHEN,
                focus=focus,
                epoch=WHEN,
            )
            store.append_user_turn(
                "user-a", "2026-07-13", FINGERPRINT_A, user_turn
            )
            thread = store.mark_ready(
                "user-a",
                "2026-07-13",
                FINGERPRINT_A,
                turn_id,
                GeneratedSkyChatReply(reply=f"Reflective answer {index}."),
                at=WHEN,
            )
        assert thread.success_count == SKY_CHAT_MAX_REPLIES_PER_DAY

        overflow = SkyChatTurn(
            turn_id="overflow",
            role="user",
            text="One question too many",
            at=WHEN,
            focus=focus,
            epoch=WHEN,
        )
        with pytest.raises(SkyChatRateLimitError):
            store.append_user_turn(
                "user-a", "2026-07-13", FINGERPRINT_A, overflow
            )
        assert store.get("user-a", "2026-07-13", FINGERPRINT_B) == isolated
        assert (
            store.success_count_for_day("user-a", "2026-07-13")
            == SKY_CHAT_MAX_REPLIES_PER_DAY
        )

        # A natal fingerprint change starts a new thread, but not a new
        # per-user civil-day allowance.
        store.delete_user("user-a")
        store.ensure_thread("user-a", "2026-07-13", FINGERPRINT_B)
        with pytest.raises(SkyChatRateLimitError):
            store.append_user_turn(
                "user-a", "2026-07-13", FINGERPRINT_B, overflow
            )

        if backend == "sqlite":
            store.close()
            store = SQLiteSkyChatStore(tmp_path / "sidereal.db")
            assert (
                store.success_count_for_day("user-a", "2026-07-13")
                == SKY_CHAT_MAX_REPLIES_PER_DAY
            )
    finally:
        store.close()


def test_natal_fingerprint_never_enters_fact_payload() -> None:
    record = _record()
    facts = build_sky_chat_facts(record, {"kind": "sky"}, when=WHEN)
    assert natal_fingerprint(record) not in json.dumps(facts, sort_keys=True)


def test_service_allows_only_one_pending_job_then_accepts_follow_up() -> None:
    reply = "Hold the supplied geometry as a reflective prompt with room for context."

    class BlockingAuthor:
        model = "test-model"

        def __init__(self) -> None:
            self.started = Event()
            self.release = Event()
            self.calls: list[dict[str, Any]] = []

        def generate(
            self,
            facts: Mapping[str, Any],
            history: Sequence[Mapping[str, str]],
            message: str,
        ) -> GeneratedSkyChatReply:
            del facts
            self.calls.append({"history": list(history), "message": message})
            if len(self.calls) == 1:
                self.started.set()
                if not self.release.wait(timeout=5.0):
                    raise RuntimeError("test author was not released")
            return GeneratedSkyChatReply(reply)

    author = BlockingAuthor()
    service = SkyChatService(
        MemorySkyChatStore(),
        _service_facts,
        author=author,
        clock=lambda: WHEN,
    )
    record = _record()
    service.start()
    try:
        first = service.post(
            record,
            {"message": "First question", "focus": {"kind": "sky"}},
        )
        assert first["status"] == "pending"
        assert author.started.wait(timeout=5.0)

        second = service.post(
            record,
            {"message": "Second question", "focus": {"kind": "sky"}},
        )
        assert second["status"] == "pending"
        assert second["turn_id"] == first["turn_id"]
        assert [turn["text"] for turn in second["turns"]] == [
            "First question",
        ]

        author.release.set()
        assert service.wait_until_idle(timeout_seconds=5.0)
        follow_up = service.post(
            record,
            {"message": "Second question", "focus": {"kind": "sky"}},
        )
        assert follow_up["turn_id"] != first["turn_id"]
        assert service.wait_until_idle(timeout_seconds=5.0)
        ready = service.get(record)
        assert ready["status"] == "ready"
        assert [turn["role"] for turn in ready["turns"]] == [
            "user",
            "assistant",
            "user",
            "assistant",
        ]
        assert [call["message"] for call in author.calls] == [
            "First question",
            "Second question",
        ]
        assert author.calls[0]["history"] == []
        assert author.calls[1]["history"] == [
            {"role": "user", "text": "First question"},
            {"role": "assistant", "text": reply},
        ]
    finally:
        author.release.set()
        service.close()


def test_get_uses_owned_thread_id_and_recovers_persisted_pending_work() -> None:
    reply = "Study only the supplied facts, keeping the interpretation tentative."

    class FixedAuthor:
        model = "test-model"

        def __init__(self) -> None:
            self.calls = 0

        def generate(
            self,
            facts: Mapping[str, Any],
            history: Sequence[Mapping[str, str]],
            message: str,
        ) -> GeneratedSkyChatReply:
            del facts, history, message
            self.calls += 1
            return GeneratedSkyChatReply(reply)

    record = _record()
    store = MemorySkyChatStore()
    fingerprint = natal_fingerprint(record)
    historic = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
    thread = store.ensure_thread("private-user", "2026-07-12", fingerprint)
    turn = SkyChatTurn(
        turn_id="persisted-turn",
        role="user",
        text="Persisted question",
        at=WHEN,
        focus=SkyChatFocus(kind="sky"),
        epoch=historic,
    )
    store.append_user_turn(
        "private-user",
        "2026-07-12",
        fingerprint,
        turn,
    )
    author = FixedAuthor()
    service = SkyChatService(
        store,
        _service_facts,
        author=author,
        clock=lambda: WHEN,
    )
    service.start()
    try:
        pending = service.get(record, thread_id=thread.thread_id)
        assert pending["cache_date"] == "2026-07-12"
        assert pending["status"] in {"pending", "ready"}
        assert service.wait_until_idle(timeout_seconds=5.0)
        ready = service.get(record, thread_id=thread.thread_id)
        assert ready["status"] == "ready"
        assert ready["cache_date"] == "2026-07-12"
        assert ready["thread_id"] == thread.thread_id
        assert author.calls == 1

        today = service.get(record)
        assert today["status"] == "none"
        assert today["cache_date"] == "2026-07-13"
    finally:
        service.close()


def test_persisted_pending_fact_failure_becomes_failed_instead_of_sticking() -> None:
    class NeverAuthor:
        model = "test-model"

        def generate(
            self,
            facts: Mapping[str, Any],
            history: Sequence[Mapping[str, str]],
            message: str,
        ) -> GeneratedSkyChatReply:
            del facts, history, message
            raise AssertionError("provider must not run when fact recovery fails")

    record = _record()
    store = MemorySkyChatStore()
    fingerprint = natal_fingerprint(record)
    thread = store.ensure_thread(record.user_id, "2026-07-13", fingerprint)
    store.append_user_turn(
        record.user_id,
        "2026-07-13",
        fingerprint,
        SkyChatTurn(
            turn_id="broken-facts-turn",
            role="user",
            text="Persisted question",
            at=WHEN,
            focus=SkyChatFocus(kind="sky"),
            epoch=WHEN,
        ),
    )

    def broken_facts(
        record: NatalRecord,
        focus: SkyChatFocus,
        *,
        when: datetime,
    ) -> dict[str, Any]:
        del record, focus, when
        raise RuntimeError("simulated private fact failure")

    service = SkyChatService(
        store,
        broken_facts,
        author=NeverAuthor(),
        clock=lambda: WHEN,
    )
    try:
        failed = service.get(record, thread_id=thread.thread_id)
        assert failed["status"] == "failed"
        assert failed["turn_id"] == "broken-facts-turn"
        persisted = store.get(record.user_id, "2026-07-13", fingerprint)
        assert persisted is not None
        assert persisted.pending_turn_id is None
        assert persisted.turns[-1].role == "assistant"
        assert persisted.turns[-1].status == "failed"
        assert persisted.turns[-1].text == ""
    finally:
        service.close()


def test_invalidation_drops_stale_queued_turn_before_provider_call() -> None:
    reply = "Keep the supplied facts tentative and bounded by their stated scope."

    class FirstCallBlockingAuthor:
        model = "test-model"

        def __init__(self) -> None:
            self.started = Event()
            self.release = Event()
            self.messages: list[str] = []

        def generate(
            self,
            facts: Mapping[str, Any],
            history: Sequence[Mapping[str, str]],
            message: str,
        ) -> GeneratedSkyChatReply:
            del facts, history
            self.messages.append(message)
            if len(self.messages) == 1:
                self.started.set()
                if not self.release.wait(timeout=5.0):
                    raise RuntimeError("test author was not released")
            return GeneratedSkyChatReply(reply)

    author = FirstCallBlockingAuthor()
    service = SkyChatService(
        MemorySkyChatStore(),
        _service_facts,
        author=author,
        clock=lambda: WHEN,
    )
    record_a = _record()
    record_b = NatalRecord(
        user_id="user-b",
        birth_date=record_a.birth_date,
        birth_time=record_a.birth_time,
        time_unknown=record_a.time_unknown,
        tz=record_a.tz,
        lat=record_a.lat,
        lon=record_a.lon,
        place_label=record_a.place_label,
        updated_at=record_a.updated_at,
    )
    service.start()
    try:
        service.post(
            record_b,
            {"message": "Blocking question", "focus": {"kind": "sky"}},
        )
        assert author.started.wait(timeout=5.0)
        service.post(
            record_a,
            {"message": "Old private question", "focus": {"kind": "sky"}},
        )
        service.invalidate_user(record_a.user_id)
        replacement = service.post(
            record_a,
            {"message": "New question", "focus": {"kind": "sky"}},
        )
        assert replacement["status"] == "pending"
        assert replacement["turn_id"] is not None
        assert [turn["text"] for turn in replacement["turns"]] == ["New question"]

        author.release.set()
        assert service.wait_until_idle(timeout_seconds=5.0)
        ready = service.get(record_a)
        assert ready["status"] == "ready"
        assert author.messages == ["Blocking question", "New question"]
        assert "Old private question" not in json.dumps(ready)
    finally:
        author.release.set()
        service.close()
