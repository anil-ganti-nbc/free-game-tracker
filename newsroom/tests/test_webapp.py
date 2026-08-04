"""Tests for the local web dashboard, via FastAPI's TestClient (no browser)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from newsroom import cli, database, webapp
from newsroom.config import settings
from newsroom.database import to_row
from newsroom.models import Confidence, NewsEvent, PromotionType, Source


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setattr(settings, "database_path", tmp_path / "test.db")
    monkeypatch.setattr(settings, "reports_dir", tmp_path / "reports")
    database.reset_engine()
    database.init_db()
    yield tmp_path
    database.reset_engine()


@pytest.fixture
def client() -> TestClient:
    return TestClient(webapp.app)


def _seed_event() -> NewsEvent:
    return NewsEvent(
        source=Source.EPIC,
        title="Dashboard Game",
        url="https://store.epicgames.com/en-US/p/dash",
        promotion_type=PromotionType.GIVEAWAY,
        original_price=19.99,
        current_price=0.0,
        promotion_end=datetime(2026, 8, 1, tzinfo=UTC),
        confidence=Confidence(score=100, reasons=["free"]),
    )


def test_index_serves_html(env: Path, client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Newsroom" in resp.text
    assert "Run now" in resp.text


def test_state_reflects_stored_events(env: Path, client: TestClient) -> None:
    with database.session_scope() as session:
        session.add(to_row(_seed_event()))
    database.record_source_result("epic", ok=True, count=1)

    data = client.get("/api/state").json()
    assert data["counts"]["giveaways"] == 1
    assert data["giveaways"][0]["title"] == "Dashboard Game"
    assert data["giveaways"][0]["original_price"] == 19.99
    health = {h["source"]: h for h in data["health"]}
    assert health["epic"]["status"] == "ok"
    assert health["epic"]["count"] == 1


def test_run_now_triggers_pipeline(
    env: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_SOURCES", {"stub": lambda: [_seed_event()]})
    resp = client.post("/api/run")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["summary"]["new"] == 1
    # The run persisted the event.
    assert len(database.load_all_events()) == 1


def test_run_now_is_serialized(env: Path, client: TestClient) -> None:
    """If a run holds the lock, a second request is rejected with 409."""
    webapp._run_lock.acquire()
    try:
        resp = client.post("/api/run")
        assert resp.status_code == 409
        assert resp.json()["ok"] is False
    finally:
        webapp._run_lock.release()
