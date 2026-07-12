from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("swisseph")

from fastapi.testclient import TestClient

from sidereal.auth import RejectingAuthenticator
from sidereal.interpret.store import InterpretationStore
from sidereal.natal import MemoryNatalStore
from sidereal.web import create_app


class FakeAISeedQueue:
    def __init__(self) -> None:
        self.started = 0
        self.closed = 0
        self.enqueued: list[str] = []

    def start(self) -> None:
        self.started += 1

    def close(self) -> None:
        self.closed += 1

    def enqueue(self, entry_id: str) -> bool:
        self.enqueued.append(entry_id)
        return True


def test_sky_listen_only_enqueues_gaps_and_owns_queue_lifecycle(
    tmp_path: Path,
) -> None:
    database = tmp_path / "sidereal.db"
    with InterpretationStore(database) as store:
        store.initialize()

    queue = FakeAISeedQueue()
    app = create_app(
        db_path=database,
        charts_dir=tmp_path / "charts",
        natal_store=MemoryNatalStore(),
        authenticator=RejectingAuthenticator(),
        ai_seed_queue=queue,  # type: ignore[arg-type]
    )
    assert app.state.ai_seed_queue is queue

    with TestClient(app) as client:
        assert queue.started == 1

        chart = client.post(
            "/api/chart",
            json={
                "moment": {
                    "date": "2000-01-01",
                    "time": "12:00",
                    "tz": "UTC",
                    "lat": 0,
                    "lon": 0,
                    "label": "No AI hook",
                },
                "options": {},
            },
        )
        assert chart.status_code == 200, chart.text
        assert queue.enqueued == []

        listen = client.get(
            "/api/sky-listen",
            params={
                "kind": "sign",
                "sign": "aries",
                "when": "2026-07-12T12:00:00",
                "tz": "UTC",
            },
        )
        assert listen.status_code == 200, listen.text
        assert listen.json()["placement"]["status"] == "missing"
        assert queue.enqueued == ["sign:aries"]

    assert queue.closed == 1
