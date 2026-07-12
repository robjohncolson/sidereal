from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Any

import pytest

from sidereal.cli import main
from sidereal.interpret.ai_seed import interpretation_template
from sidereal.interpret.schema import generate_seed1_entries
from sidereal.interpret.store import InterpretationStore


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


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _ready_seed1_entries() -> dict[str, Any]:
    return {entry.id: entry for entry in generate_seed1_entries()}


def _initialize_with_ready_signs(database: Path) -> None:
    with InterpretationStore(database) as store:
        store.initialize()
        for entry in generate_seed1_entries():
            if entry.type == "sign":
                store.upsert_entry(entry, expected=None)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_apply_json_batch_fills_stub_and_skips_ready(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "sidereal.db"
    source = tmp_path / "filled.json"
    target = "sign:aries"
    skipped_id = "sign:taurus"
    ready = _ready_seed1_entries()[skipped_id]

    with InterpretationStore(database) as store:
        store.initialize()
        stub = interpretation_template(target)
        store.upsert_entry(stub, expected=None)
        store.upsert_entry(ready, expected=None)

    _write_json(
        source,
        {
            "schema_version": 1,
            "records": [
                {"id": target, **VALID_CONTENT},
                {"id": skipped_id, **VALID_CONTENT},
            ],
        },
    )

    assert main(
        ["ai-seed", "apply-json", "--file", str(source), "--db", str(database)]
    ) == 0
    assert json.loads(capsys.readouterr().out) == {
        "filled": 1,
        "invalid": 0,
        "skipped": 1,
    }

    with InterpretationStore(database) as store:
        saved = store.get(target)
        assert saved is not None
        assert saved.sign == "aries"
        assert saved.title == VALID_CONTENT["title"]
        assert saved.summary == VALID_CONTENT["summary"]
        assert saved.growth == VALID_CONTENT["growth"]
        assert saved.keywords == tuple(VALID_CONTENT["keywords"])
        assert saved.source == "ai-offline"
        assert saved.license == "personal-use"
        assert saved.status == "ready"
        assert saved.version == stub.version + 1
        assert store.get(skipped_id) == ready


def test_apply_json_accepts_a_single_record_object(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "sidereal.db"
    source = tmp_path / "single.json"
    target = "sign:aries"
    with InterpretationStore(database) as store:
        store.initialize()

    _write_json(source, {"id": target, **VALID_CONTENT})

    assert main(
        ["ai-seed", "apply-json", "--file", str(source), "--db", str(database)]
    ) == 0
    assert json.loads(capsys.readouterr().out) == {
        "filled": 1,
        "invalid": 0,
        "skipped": 0,
    }
    with InterpretationStore(database) as store:
        saved = store.get(target)
        assert saved is not None
        assert saved.source == "ai-offline"
        assert saved.status == "ready"
        assert saved.version == interpretation_template(target).version + 1


def test_apply_json_rejects_a_banned_phrase_without_mutating_the_stub(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "sidereal.db"
    source = tmp_path / "unsafe.json"
    target = "sign:aries"
    with InterpretationStore(database) as store:
        store.initialize()
        stub = interpretation_template(target)
        store.upsert_entry(stub, expected=None)

    _write_json(
        source,
        {
            "id": target,
            **VALID_CONTENT,
            "summary": (
                "Aries offers a guaranteed successful outcome whenever direct action is "
                "taken, regardless of context or consequence."
            ),
        },
    )

    assert main(
        ["ai-seed", "apply-json", "--file", str(source), "--db", str(database)]
    ) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "filled": 0,
        "invalid": 1,
        "skipped": 0,
    }
    assert captured.err == ""
    with InterpretationStore(database) as store:
        assert store.get(target) == stub


def test_export_prompts_is_supported_deterministic_and_key_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "sidereal.db"
    output = tmp_path / "prompts.jsonl"
    _initialize_with_ready_signs(database)
    secret = "offline-export-secret-sentinel"
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)
    monkeypatch.setenv("DEEPSEEK_MODEL", "invalid model with spaces")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "http://not-a-loopback.example")

    assert main(
        [
            "ai-seed",
            "export-prompts",
            "--limit",
            "2",
            "--db",
            str(database),
            "-o",
            str(output),
        ]
    ) == 0

    captured = capsys.readouterr()
    raw = output.read_text(encoding="utf-8")
    records = _read_jsonl(output)
    assert json.loads(captured.out) == {"exported": 2, "output": str(output)}
    assert captured.err == ""
    assert secret not in raw
    assert secret not in captured.out
    assert [record["entry_id"] for record in records] == [
        "planet_in_sign:sun:aries",
        "planet_in_sign:sun:taurus",
    ]
    assert all(record["mode"] == "dry-run" for record in records)
    assert all(record["writes"] is False for record in records)
    assert all(record["request"]["stream"] is False for record in records)
    assert all(
        "Midpoint J2000 geometry remains authoritative"
        in record["request"]["messages"][0]["content"]
        for record in records
    )


def test_export_prompts_few_shot_prefers_original_same_type_and_truncates(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "sidereal.db"
    output = tmp_path / "few-shot.jsonl"
    _initialize_with_ready_signs(database)
    ready = _ready_seed1_entries()
    long_tail = "END-OF-LONG-SUMMARY-MUST-NOT-APPEAR"
    original_example = replace(
        ready["planet_in_sign:sun:gemini"],
        title="ORIGINAL SAME TYPE EXAMPLE",
        summary="A deliberately long same-type example. " + "x" * 800 + long_tail,
    )
    non_original_example = replace(
        interpretation_template("planet_in_sign:mars:aries"),
        title="NONORIGINAL EXAMPLE MUST NOT APPEAR",
        status="ready",
        source="ai-deepseek",
        version=2,
    )
    cross_type_example = replace(
        ready["house:1"],
        title="CROSS TYPE EXAMPLE MUST NOT APPEAR",
    )
    with InterpretationStore(database) as store:
        store.upsert_entry(original_example, expected=None)
        store.upsert_entry(non_original_example, expected=None)
        store.upsert_entry(cross_type_example, expected=None)

    assert main(
        [
            "ai-seed",
            "export-prompts",
            "--limit",
            "1",
            "--few-shot",
            "1",
            "--db",
            str(database),
            "-o",
            str(output),
        ]
    ) == 0
    capsys.readouterr()

    record = _read_jsonl(output)[0]
    assert record["entry_id"] == "planet_in_sign:sun:aries"
    assert len(record["few_shot"]) == 1
    example = record["few_shot"][0]
    assert example["id"] == original_example.id
    assert example["title"] == original_example.title
    assert len(example["summary"]) <= 500
    assert example["summary"].endswith("…")
    assert long_tail not in example["summary"]
    user_prompt = record["request"]["messages"][1]["content"]
    assert original_example.title in user_prompt
    assert long_tail not in user_prompt
    assert non_original_example.title not in user_prompt
    assert cross_type_example.title not in user_prompt


def test_export_prompts_attaches_only_matching_text_notes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "sidereal.db"
    output = tmp_path / "notes-prompts.jsonl"
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "aries.md").write_text("ARIES NOTE SENTINEL", encoding="utf-8")
    (notes / "sun.txt").write_text("SUN NOTE SENTINEL", encoding="utf-8")
    (notes / "venus.md").write_text("VENUS NOTE MUST NOT APPEAR", encoding="utf-8")
    (notes / "ignored.json").write_text("JSON NOTE MUST NOT APPEAR", encoding="utf-8")
    _initialize_with_ready_signs(database)

    assert main(
        [
            "ai-seed",
            "export-prompts",
            "--limit",
            "1",
            "--notes-dir",
            str(notes),
            "--db",
            str(database),
            "-o",
            str(output),
        ]
    ) == 0
    capsys.readouterr()

    raw = output.read_text(encoding="utf-8")
    record = _read_jsonl(output)[0]
    assert record["entry_id"] == "planet_in_sign:sun:aries"
    assert record["source_notes"] == [
        {"source": "aries.md", "content": "ARIES NOTE SENTINEL"},
        {"source": "sun.txt", "content": "SUN NOTE SENTINEL"},
    ]
    user_prompt = record["request"]["messages"][1]["content"]
    assert "ARIES NOTE SENTINEL" in user_prompt
    assert "SUN NOTE SENTINEL" in user_prompt
    assert "VENUS NOTE MUST NOT APPEAR" not in raw
    assert "JSON NOTE MUST NOT APPEAR" not in raw
    assert str(notes.resolve()) not in raw
