from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from threading import Event
from typing import Any, Mapping

import pytest

from sidereal.cli import main
from sidereal.interpret.ai_seed import (
    AISeedConfigurationError,
    AISeedQueue,
    AISeedValidationError,
    DEFAULT_DEEPSEEK_MODEL,
    DeepSeekClient,
    DeepSeekConfig,
    DeepSeekRequestError,
    EnqueueingEntryLookup,
    GeneratedSeedContent,
    SeedPrompt,
    build_seed_prompt,
    dry_run_interpretation,
    fill_interpretation,
    fill_interpretation_gaps,
    interpretation_template,
    ai_seed_queue_from_env,
    validate_generated_record,
)
from sidereal.interpret.store import InterpretationStore
from sidereal.sky_listen import build_sky_listen


VALID_CONTENT: dict[str, Any] = {
    "title": "Aries as a symbolic beginning",
    "summary": (
        "Aries is a symbolic lens for initiation, candor, and testing a first "
        "step against the situation actually at hand, without forecasting outcomes."
    ),
    "growth": "Pair direct movement with enough pause to choose a useful direction.",
    "keywords": ["initiative", "candor", "discernment"],
}


@pytest.fixture(autouse=True)
def _clear_deepseek_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "DEEPSEEK_BASE_URL"):
        monkeypatch.delenv(name, raising=False)


class FakeTransport:
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


class StaticAuthor:
    def __init__(self, content: GeneratedSeedContent) -> None:
        self.content = content
        self.calls: list[SeedPrompt] = []

    def generate(self, prompt: SeedPrompt) -> GeneratedSeedContent:
        self.calls.append(prompt)
        return self.content


def _completion(content: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(content)},
            }
        ]
    }


def test_generated_record_validator_accepts_exact_safe_schema() -> None:
    generated = validate_generated_record("sign:aries", VALID_CONTENT)
    assert generated.title == VALID_CONTENT["title"]
    assert generated.keywords == ("initiative", "candor", "discernment")


@pytest.mark.parametrize(
    "change",
    (
        {"title": ""},
        {"summary": "Too short."},
        {"summary": "You will win every conflict because this sign guarantees it."},
        {"growth": "This placement can diagnose the hidden condition."},
        {"keywords": []},
        {"keywords": ["echo", "ECHO"]},
        {"extra": "not part of the schema"},
    ),
)
def test_generated_record_validator_rejects_unsafe_or_invalid_output(
    change: dict[str, Any],
) -> None:
    payload = {**VALID_CONTENT, **change}
    with pytest.raises(AISeedValidationError):
        validate_generated_record("sign:aries", payload)


@pytest.mark.parametrize(
    "entry_id",
    (
        "house:1",
        "sign:serpentarius",
        "planet_in_sign:earth:aries",
        "aspect:sun:trine:moon",
        "aspect:asc:trine:asc",
        "aspect:moon:quincunx:sun",
    ),
)
def test_ai_target_ids_are_supported_and_canonical(entry_id: str) -> None:
    with pytest.raises(AISeedValidationError):
        interpretation_template(entry_id)


def test_type_specific_prompts_contain_only_shared_catalog_context() -> None:
    sign = build_seed_prompt("sign:ophiuchus")
    placement = build_seed_prompt("planet_in_sign:mars:aries")
    aspect = build_seed_prompt("aspect:moon:trine:saturn")
    combined = json.dumps(
        [sign.to_dict(), placement.to_dict(), aspect.to_dict()],
        ensure_ascii=False,
    )

    assert "Ophiuchus as a first-class sign" in sign.system
    assert "planetary placement" not in placement.user.lower()
    assert "shared placement entry" in placement.user
    assert "moving-to-natal transit" in aspect.user
    assert "birth_date" not in combined
    assert "user_id" not in combined
    assert "latitude" not in combined


def test_dry_run_needs_no_key_database_or_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-appear")
    result = dry_run_interpretation("planet_in_sign:mars:aries")

    assert result["mode"] == "dry-run"
    assert result["writes"] is False
    assert result["request"]["model"] == DEFAULT_DEEPSEEK_MODEL
    assert result["endpoint"] == "https://api.deepseek.com/chat/completions"
    assert "must-not-appear" not in json.dumps(result)
    assert list(tmp_path.iterdir()) == []

    assert main(
        ["ai-seed", "dry-run", "--id", "planet_in_sign:mars:aries"]
    ) == 0
    cli_result = json.loads(capsys.readouterr().out)
    assert cli_result["writes"] is False
    assert list(tmp_path.iterdir()) == []


def test_deepseek_client_uses_current_json_chat_contract_and_hides_key() -> None:
    transport = FakeTransport(_completion(VALID_CONTENT))
    config = DeepSeekConfig(
        api_key="server-secret",
        base_url="https://deepseek.example",
        model="deepseek-v4-flash",
        timeout_seconds=3,
    )
    client = DeepSeekClient(config, transport=transport)
    generated = client.generate(build_seed_prompt("sign:aries"))

    assert generated.summary == VALID_CONTENT["summary"]
    call = transport.calls[0]
    assert call["url"] == "https://deepseek.example/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer server-secret"
    assert call["payload"]["response_format"] == {"type": "json_object"}
    assert call["payload"]["thinking"] == {"type": "disabled"}
    assert call["payload"]["stream"] is False
    assert "server-secret" not in json.dumps(call["payload"])
    assert "server-secret" not in repr(config)


def test_deepseek_client_rejects_incomplete_or_unsafe_responses() -> None:
    prompt = build_seed_prompt("sign:aries")
    for response in (
        {},
        {"choices": []},
        {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": json.dumps(VALID_CONTENT)},
                }
            ]
        },
        {
            "choices": [
                {"finish_reason": "stop", "message": {"content": "not-json"}}
            ]
        },
    ):
        client = DeepSeekClient(
            DeepSeekConfig(api_key="server-secret"),
            transport=FakeTransport(response),
        )
        with pytest.raises(DeepSeekRequestError):
            client.generate(prompt)

    with pytest.raises(AISeedConfigurationError, match="HTTPS"):
        DeepSeekConfig(
            api_key="server-secret",
            base_url="http://127.0.0.1.attacker.example",
        )


def test_mocked_fill_upgrades_stub_and_listen_prefers_ready_text(
    tmp_path: Path,
) -> None:
    database = tmp_path / "sidereal.db"
    target = "sign:aries"
    transport = FakeTransport(_completion(VALID_CONTENT))
    client = DeepSeekClient(
        DeepSeekConfig(api_key="server-secret"),
        transport=transport,
    )

    with InterpretationStore(database) as store:
        store.initialize()
        stub = interpretation_template(target)
        store.upsert_entry(stub, expected=None)

        result = fill_interpretation(
            target,
            store,
            client=client,
            today=lambda: date(2026, 7, 12),
        )
        saved = store.get(target)
        assert result.action == "filled"
        assert saved is not None
        assert saved.status == "ready"
        assert saved.source == "ai-deepseek"
        assert saved.version == stub.version + 1
        assert saved.summary == VALID_CONTENT["summary"]

        class RecordingQueue:
            def __init__(self) -> None:
                self.ids: list[str] = []

            def enqueue(self, entry_id: str) -> bool:
                self.ids.append(entry_id)
                return True

            def start(self) -> None:
                pass

            def close(self) -> None:
                pass

        recording_queue = RecordingQueue()

        listen = build_sky_listen(
            sign="aries",
            when="2026-07-12T12:00:00",
            tz="UTC",
            store=EnqueueingEntryLookup(
                store,
                recording_queue,
            ),
        )
        assert listen["placement"]["status"] == "ready"
        assert listen["placement"]["text"] == VALID_CONTENT["summary"]
        assert recording_queue.ids == []
    assert len(transport.calls) == 1


def test_invalid_fill_never_replaces_stub_and_ready_never_calls_author(
    tmp_path: Path,
) -> None:
    database = tmp_path / "sidereal.db"
    target = "sign:aries"
    unsafe = GeneratedSeedContent(
        title="Unsafe Aries",
        summary="You will receive a guaranteed outcome from this symbolic placement.",
        growth="Pause.",
        keywords=("certainty",),
    )

    with InterpretationStore(database) as store:
        store.initialize()
        stub = interpretation_template(target)
        store.upsert_entry(stub, expected=None)
        with pytest.raises(AISeedValidationError):
            fill_interpretation(target, store, client=StaticAuthor(unsafe))
        assert store.get(target) == stub

        ready = validate_generated_record(target, VALID_CONTENT)
        author = StaticAuthor(ready)
        filled = fill_interpretation(
            target,
            store,
            client=author,
            today=lambda: date(2026, 7, 12),
        )
        assert filled.action == "filled"
        call_count = len(author.calls)
        repeated = fill_interpretation(target, store, client=author)
        assert repeated.action == "already_ready"
        assert len(author.calls) == call_count


def test_fill_without_key_is_clear_and_leaves_database_unchanged(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "sidereal.db"
    target = "sign:aries"
    with InterpretationStore(database) as store:
        store.initialize()
        stub = interpretation_template(target)
        store.upsert_entry(stub, expected=None)

    assert main(
        ["ai-seed", "fill", "--id", target, "--db", str(database)]
    ) == 1
    assert "DEEPSEEK_API_KEY" in capsys.readouterr().err
    with InterpretationStore(database) as store:
        assert store.get(target) == stub


def test_malformed_key_never_appears_in_cli_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "sidereal.db"
    target = "sign:aries"
    with InterpretationStore(database) as store:
        store.initialize()
        store.upsert_entry(interpretation_template(target), expected=None)

    secret = "top-secret\nX-Test: injected"
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)
    assert main(
        ["ai-seed", "fill", "--id", target, "--db", str(database)]
    ) == 1
    error = capsys.readouterr().err
    assert "DEEPSEEK_API_KEY" in error
    assert "top-secret" not in error
    assert "X-Test" not in error

    monkeypatch.setenv("DEEPSEEK_API_KEY", "   ")
    assert ai_seed_queue_from_env(database) is None


def test_fill_gaps_filters_supported_inventory_and_respects_limit(
    tmp_path: Path,
) -> None:
    content = validate_generated_record(
        "sign:aries",
        {
            "title": "A shared symbolic study entry",
            "summary": (
                "This shared catalog note offers a reflective symbolic lens and "
                "invites proportion, observation, and revision without predicting outcomes."
            ),
            "growth": "Test the symbolic theme against lived context and other chart factors.",
            "keywords": ["reflection", "context", "proportion"],
        },
    )
    author = StaticAuthor(content)
    with InterpretationStore(tmp_path / "sidereal.db") as store:
        store.initialize()
        result = fill_interpretation_gaps(
            store,
            limit=2,
            client=author,
            today=lambda: date(2026, 7, 12),
        )
        assert result.selected_ids == ("sign:aries", "sign:taurus")
        assert len(result.results) == 2
        assert all(item.action == "filled" for item in result.results)
        assert all(
            store.get(entry_id) is not None
            and store.get(entry_id).status == "ready"  # type: ignore[union-attr]
            for entry_id in result.selected_ids
        )
    assert [prompt.entry_id for prompt in author.calls] == list(result.selected_ids)


def test_queue_deduplicates_queued_and_inflight_ids() -> None:
    entered = Event()
    release = Event()
    calls: list[str] = []

    def worker(entry_id: str) -> None:
        calls.append(entry_id)
        entered.set()
        assert release.wait(timeout=2)

    seed_queue = AISeedQueue(worker, maxsize=2)
    target = "sign:aries"
    assert seed_queue.enqueue(target) is False
    seed_queue.start()
    assert seed_queue.enqueue(target) is True
    assert seed_queue.enqueue(target) is False
    assert entered.wait(timeout=2)
    assert seed_queue.enqueue(target) is False
    assert seed_queue.enqueue("house:1") is False
    release.set()
    assert seed_queue.wait_until_idle(timeout_seconds=2)
    assert calls == [target]
    seed_queue.close()
    assert seed_queue.enqueue(target) is False
