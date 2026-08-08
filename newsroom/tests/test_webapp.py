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
    # /api/run drives the real pipeline, including real Discord notification
    # calls. Without this, a developer's local .env webhook would receive a
    # live message built from this file's fake fixtures (e.g. "Dashboard
    # Game" / .../p/dash, which isn't a real store URL) every time the suite
    # runs. notify_* no-ops when there's no webhook, so this makes the tests
    # network-silent regardless of what's configured locally.
    monkeypatch.setattr(settings, "discord_webhook_url", None)
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


def test_api_state_dateless_events() -> None:
    from unittest.mock import patch

    from newsroom.models import (
        AccessModel,
        Category,
        EventType,
        NewsEvent,
        OwnershipModel,
        PromotionType,
        Source,
    )
    from newsroom.webapp import get_state

    e1 = NewsEvent(
        source=Source.PLAYSTATION_PLUS,
        category=Category.SUBSCRIPTION,
        promotion_type=PromotionType.GIVEAWAY,
        event_type=EventType.CLAIMABLE_GAME,
        access_model=AccessModel.CLAIMABLE,
        ownership_model=OwnershipModel.PERMANENT_WHILE_ACCOUNT_EXISTS,
        title="Dateless Event",
        url="http://a",
        available_from=None,
        confidence=__import__("newsroom.models").models.Confidence(score=95, reasons=["mock"]),
    )

    with (
        patch("newsroom.webapp.load_all_events", return_value=[e1]),
        patch("newsroom.webapp.load_source_health", return_value=[]),
        patch("newsroom.webapp.load_new_releases", return_value=[]),
        patch("newsroom.webapp.load_deals", return_value=[]),
    ):
        state = get_state()
        assert len(state["giveaways"]) == 1
        assert state["giveaways"][0]["title"] == "Dateless Event"
