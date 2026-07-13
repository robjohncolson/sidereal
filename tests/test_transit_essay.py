from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from sidereal.config import BODY_IDS
from sidereal.interpret.ai_seed import DeepSeekConfig, interpretation_template
from sidereal.interpret.store import InterpretationStore
from sidereal.natal import NatalRecord
from sidereal.personal_sky import build_personal_skypack
from sidereal.transit_essay import (
    DeepSeekTransitEssayAuthor,
    GeneratedTransitEssay,
    MemoryTransitEssayStore,
    SQLiteTransitEssayStore,
    TransitEssayValidationError,
    build_transit_essay_facts,
    natal_fingerprint,
    transit_essay_cache_date,
    validate_transit_essay_content,
)


_WHEN = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
_FINGERPRINT_A = "a" * 64
_FINGERPRINT_B = "b" * 64
_VALID_GENERATED = {
    "headline": "A careful reading of today's moving sky",
    "body": (
        "The listed contacts invite patient observation of changing emphasis. "
        "Treat each image as a symbolic study prompt, leaving room for context, "
        "choice, and meanings that emerge through reflection rather than certainty."
    ),
    "watchpoints": ["Notice which themes repeat without forcing a conclusion."],
}


def _record(
    user_id: str = "private-user-47",
    *,
    timezone: str = "America/New_York",
) -> NatalRecord:
    return NatalRecord(
        user_id=user_id,
        birth_date=date(1983, 11, 29),
        birth_time=time(22, 24),
        time_unknown=False,
        tz=timezone,
        lat=40.7128,
        lon=-74.006,
        place_label="DO NOT LEAK THIS PRIVATE PLACE",
        updated_at=datetime(2026, 7, 1, 8, 30, tzinfo=UTC),
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


def _normalized_aspect_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        float(item["orb"]) / float(item["orb_limit"]),
        float(item["orb"]),
        str(item["transit_body"]),
        str(item["natal_point"]),
        str(item["aspect_id"]),
    )


def _facts_with_one_aspect() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "type": "transit_essay_facts",
        "cache_date": "2026-07-12",
        "timezone": "UTC",
        "epoch_utc": "2026-07-12T12:00:00+00:00",
        "natal": {"time_unknown": False, "tz": "UTC", "placements": []},
        "sky": {"movers": []},
        "same_body_delta": [],
        "aspects": [
            {
                "transit_body": "mars",
                "natal_point": "moon",
                "aspect_id": "square",
                "orb": 0.5,
                "orb_limit": 7.0,
                "applying": True,
                "seed_status": "missing",
            }
        ],
    }


class RecordingTransport:
    def __init__(self, response: Mapping[str, Any]) -> None:
        self.response = response
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
        return self.response


def _completion(content: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(content)},
            }
        ]
    }


def test_facts_are_private_multi_body_ranked_capped_and_have_exact_deltas() -> None:
    record = _record()
    facts = build_transit_essay_facts(record, when=_WHEN)
    capped = build_transit_essay_facts(record, when=_WHEN, max_aspects=5)

    assert set(facts) == {
        "schema_version",
        "type",
        "cache_date",
        "timezone",
        "epoch_utc",
        "natal",
        "sky",
        "same_body_delta",
        "aspects",
    }
    assert facts["schema_version"] == 1
    assert facts["type"] == "transit_essay_facts"
    assert facts["cache_date"] == "2026-07-12"
    assert facts["timezone"] == record.tz
    assert facts["epoch_utc"] == _WHEN.isoformat()

    private_field_names = {
        "user_id",
        "birth_date",
        "birth_time",
        "lat",
        "lon",
        "place_label",
        "updated_at",
        "email",
        "api_key",
        "authorization",
        "supabase_token",
        "natal_fingerprint",
    }
    assert private_field_names.isdisjoint(_all_keys(facts))
    rendered = json.dumps(facts, sort_keys=True)
    assert record.user_id not in rendered
    assert record.place_label not in rendered
    assert record.birth_date.isoformat() not in rendered
    assert record.birth_time is not None
    assert record.birth_time.isoformat() not in rendered

    movers = facts["sky"]["movers"]
    assert tuple(item["body"] for item in movers) == BODY_IDS
    assert len(facts["aspects"]) == 24
    assert len({item["transit_body"] for item in facts["aspects"]}) > 1
    assert len({item["natal_point"] for item in facts["aspects"]}) > 1
    assert all(item["seed_status"] == "missing" for item in facts["aspects"])

    actual_order = [_normalized_aspect_key(item) for item in facts["aspects"]]
    assert actual_order == sorted(actual_order)
    assert len(capped["aspects"]) == 5
    assert capped["aspects"] == facts["aspects"][:5]

    deltas = facts["same_body_delta"]
    assert tuple(item["body"] for item in deltas) == BODY_IDS
    assert all(0.0 <= item["delta_deg"] <= 180.0 for item in deltas)

    # The existing private skypack is an independent public projection of the
    # same J2000 shortest-arc geometry.
    pack = build_personal_skypack(record, when=_WHEN)
    pack_deltas = {item["id"]: item["delta_deg"] for item in pack["same_body_delta"]}
    for item in deltas:
        assert item["delta_deg"] == pytest.approx(
            pack_deltas[item["body"]],
            abs=1e-6,
        )


def test_cache_date_uses_natal_timezone_and_fingerprint_tracks_geometry() -> None:
    record = _record()
    before_local_midnight = datetime(2026, 7, 12, 3, 59, 59, tzinfo=UTC)
    at_local_midnight = before_local_midnight + timedelta(seconds=1)

    assert transit_essay_cache_date(record, before_local_midnight) == "2026-07-11"
    assert transit_essay_cache_date(record, at_local_midnight) == "2026-07-12"
    tokyo = replace(record, tz="Asia/Tokyo")
    assert transit_essay_cache_date(tokyo, before_local_midnight) == "2026-07-12"
    with pytest.raises(ValueError, match="timezone-aware"):
        transit_essay_cache_date(record, datetime(2026, 7, 12, 12))

    fingerprint = natal_fingerprint(record)
    assert len(fingerprint) == 64
    assert set(fingerprint) <= set("0123456789abcdef")
    assert natal_fingerprint(
        replace(
            record,
            place_label="A renamed place",
            updated_at=record.updated_at + timedelta(days=1),
        )
    ) == fingerprint
    assert natal_fingerprint(replace(record, user_id="another-user")) == fingerprint
    assert natal_fingerprint(
        replace(record, birth_time=time(22, 25))
    ) != fingerprint
    assert natal_fingerprint(tokyo) != fingerprint


def test_content_validator_rejects_banned_language_and_invented_aspects() -> None:
    facts = _facts_with_one_aspect()
    allowed = {
        **_VALID_GENERATED,
        "body": (
            "Transit Mars square natal Moon is one listed symbolic contact. "
            "It can be studied as a prompt for reflection while context and choice "
            "remain more important than any fixed conclusion."
        ),
    }
    validated = validate_transit_essay_content(allowed, facts)
    assert validated.headline == allowed["headline"]

    banned = {
        **allowed,
        "body": (
            "You will receive a guaranteed outcome from this transit, according to "
            "language that a symbolic and non-predictive study must never present."
        ),
    }
    with pytest.raises(TransitEssayValidationError, match="banned fragment"):
        validate_transit_essay_content(banned, facts)

    invented = {
        **allowed,
        "body": (
            "Transit Venus trine natal Sun offers a symbolic theme for patient study, "
            "but that formal contact does not occur anywhere in the supplied fact set."
        ),
    }
    with pytest.raises(TransitEssayValidationError, match="absent from the facts"):
        validate_transit_essay_content(invented, facts)

    for claim in (
        "Transit Venus is square natal Moon",
        "Transiting Venus squares the natal Moon",
        "Venus forms a square to the Moon",
        "Venus and the natal Moon form a square",
    ):
        with pytest.raises(
            TransitEssayValidationError,
            match="absent from the facts",
        ):
            validate_transit_essay_content(
                {
                    **allowed,
                    "body": (
                        f"{claim}. This unsupported formal claim is padded with "
                        "reflective language so the body otherwise meets the schema."
                    ),
                },
                facts,
            )

    for noncanonical_claim in (
        "A square links transit Venus and natal Moon",
        "Transit Venus and natal Moon are in a square",
        "The transit Venus-natal Moon square is prominent",
    ):
        with pytest.raises(
            TransitEssayValidationError,
            match="canonical fact-reference grammar",
        ):
            validate_transit_essay_content(
                {
                    **allowed,
                    "body": (
                        f"{noncanonical_claim}. This explicit claim is padded with "
                        "reflective language so the body otherwise meets the schema."
                    ),
                },
                facts,
            )


def test_deepseek_author_sends_fact_only_user_payload_and_keeps_key_server_side() -> None:
    facts = _facts_with_one_aspect()
    secret = "server-only-deepseek-secret"
    transport = RecordingTransport(_completion(_VALID_GENERATED))
    config = DeepSeekConfig(
        api_key=secret,
        base_url="https://deepseek.example",
        model="deepseek-v4-flash",
        timeout_seconds=4,
    )
    author = DeepSeekTransitEssayAuthor(config, transport=transport)

    generated = author.generate(facts)

    assert generated.body == _VALID_GENERATED["body"]
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["url"] == "https://deepseek.example/chat/completions"
    assert call["headers"]["Authorization"] == f"Bearer {secret}"
    assert call["payload"]["response_format"] == {"type": "json_object"}
    assert call["payload"]["thinking"] == {"type": "disabled"}
    assert call["payload"]["stream"] is False
    assert json.loads(call["payload"]["messages"][1]["content"]) == facts
    assert secret not in json.dumps(call["payload"], sort_keys=True)
    assert secret not in repr(config)
    assert secret not in repr(author)


@pytest.mark.parametrize("backend", ("memory", "sqlite"))
def test_essay_stores_roundtrip_and_keep_fingerprints_isolated(
    backend: str,
    tmp_path: Path,
) -> None:
    path = tmp_path / "sidereal.db"
    store = (
        MemoryTransitEssayStore()
        if backend == "memory"
        else SQLiteTransitEssayStore(path)
    )
    content = GeneratedTransitEssay(
        headline=str(_VALID_GENERATED["headline"]),
        body=str(_VALID_GENERATED["body"]),
        watchpoints=tuple(_VALID_GENERATED["watchpoints"]),
    )

    pending_a = store.ensure_pending("user-a", "2026-07-12", _FINGERPRINT_A)
    assert pending_a.status == "pending"
    assert store.ensure_pending(
        "user-a", "2026-07-12", _FINGERPRINT_A
    ) == pending_a
    pending_b = store.ensure_pending("user-a", "2026-07-12", _FINGERPRINT_B)
    other_user = store.ensure_pending("user-b", "2026-07-12", _FINGERPRINT_A)

    ready_a = store.mark_ready(
        "user-a",
        "2026-07-12",
        _FINGERPRINT_A,
        content,
        model="deepseek-v4-flash",
        generated_at=_WHEN,
    )
    assert store.get("user-a", "2026-07-12", _FINGERPRINT_A) == ready_a
    assert store.get("user-a", "2026-07-12", _FINGERPRINT_B) == pending_b
    assert store.get("user-b", "2026-07-12", _FINGERPRINT_A) == other_user
    assert "user_id" not in ready_a.to_api_dict()
    assert "natal_fingerprint" not in ready_a.to_api_dict()

    if backend == "sqlite":
        store.close()
        reopened = SQLiteTransitEssayStore(path)
        try:
            assert reopened.get(
                "user-a", "2026-07-12", _FINGERPRINT_A
            ) == ready_a
            assert reopened.get(
                "user-a", "2026-07-12", _FINGERPRINT_B
            ) == pending_b
        finally:
            reopened.close()
    else:
        store.close()


def test_sqlite_essay_table_coexists_with_interpretation_catalog(tmp_path: Path) -> None:
    database = tmp_path / "sidereal.db"
    catalog_entry = interpretation_template("sign:aries")
    with InterpretationStore(database) as catalog:
        catalog.initialize()
        catalog.upsert_entry(catalog_entry, expected=None)

    essay_store = SQLiteTransitEssayStore(database)
    try:
        essay_store.ensure_pending("user-a", "2026-07-12", _FINGERPRINT_A)
    finally:
        essay_store.close()

    with InterpretationStore(database) as catalog:
        assert catalog.get(catalog_entry.id) == catalog_entry
