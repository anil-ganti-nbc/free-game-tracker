"""End-to-end tests for the run pipeline, with no network fetch.

These exercise ``cli._execute_run`` — the part of ``run`` after fetching — so we
feed it hand-built events and assert on the diff, the written reports, and the
resulting database state.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from newsroom import cli, database
from newsroom.config import settings
from newsroom.models import Confidence, NewsEvent, PromotionType, Source


@pytest.fixture
def temp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Isolate the database and reports directory under a temp path."""
    monkeypatch.setattr(settings, "database_path", tmp_path / "test.db")
    monkeypatch.setattr(settings, "reports_dir", tmp_path / "reports")
    database.reset_engine()
    database.init_db()
    yield tmp_path
    database.reset_engine()


def _event(url: str) -> NewsEvent:
    return NewsEvent(
        source=Source.EPIC,
        title=f"Game {url}",
        url=f"https://store.epicgames.com/en-US/p/{url}",
        promotion_type=PromotionType.GIVEAWAY,
        original_price=19.99,
        current_price=0.0,
        promotion_end=datetime(2026, 8, 1, tzinfo=UTC),
        confidence=Confidence(score=100, reasons=["free"]),
    )


def test_first_run_reports_all_new_and_persists(temp_env: Path) -> None:
    now = datetime(2026, 7, 19, 18, 30, tzinfo=UTC)
    diff, markdown_path, json_path = cli._execute_run([_event("a"), _event("b")], now)

    assert len(diff.new) == 2
    assert markdown_path.exists()
    assert json_path.exists()
    assert len(database.load_all_events()) == 2


def test_second_run_detects_new_and_expired(temp_env: Path) -> None:
    now = datetime(2026, 7, 19, 18, 30, tzinfo=UTC)
    cli._execute_run([_event("a"), _event("b")], now)
    diff, _, _ = cli._execute_run([_event("b"), _event("c")], now)

    assert {e.title for e in diff.new} == {"Game c"}
    assert {e.title for e in diff.expired} == {"Game a"}
    # The stored snapshot now reflects only the latest run.
    stored = {e.title for e in database.load_all_events()}
    assert stored == {"Game b", "Game c"}


def test_stable_run_reports_no_changes(temp_env: Path) -> None:
    now = datetime(2026, 7, 19, 18, 30, tzinfo=UTC)
    cli._execute_run([_event("a")], now)
    diff, _, _ = cli._execute_run([_event("a")], now)
    assert diff.has_changes is False


def test_dry_run_does_not_persist(temp_env: Path) -> None:
    now = datetime(2026, 7, 19, 18, 30, tzinfo=UTC)
    diff, md, _ = cli._execute_run([_event("a")], now, persist=False)
    assert len(diff.new) == 1  # still detected and reported
    assert md.exists()
    assert database.load_all_events() == []  # but nothing stored


def test_failing_source_is_isolated(
    temp_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One source raising an unexpected error must not lose the others."""

    def _boom() -> list[NewsEvent]:
        raise RuntimeError("parser blew up")

    monkeypatch.setattr(
        cli, "_SOURCES", {"good": lambda: [_event("a")], "bad": _boom}
    )
    events = cli._fetch_all_sources([])
    assert {e.title for e in events} == {"Game a"}

    # Health is recorded for both outcomes.
    health = {h.source: h for h in database.load_source_health()}
    assert health["good"].last_status == "ok"
    assert health["good"].last_count == 1
    assert health["bad"].last_status == "error"
    assert health["bad"].last_success_at is None


def test_source_filter_selects_subset(
    temp_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cli, "_SOURCES", {"one": lambda: [_event("a")], "two": lambda: [_event("b")]}
    )
    events = cli._fetch_all_sources(["two"])
    assert {e.title for e in events} == {"Game b"}


def test_latest_reports_are_written(temp_env: Path) -> None:
    now = datetime(2026, 7, 19, 18, 30, tzinfo=UTC)
    cli._execute_run([_event("a")], now)
    reports_dir = temp_env / "reports"
    assert (reports_dir / "latest.md").exists()
    assert (reports_dir / "latest.json").exists()


def test_quality_gate_suppresses_surfacing_but_still_stores(
    temp_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "min_confidence", 70)
    monkeypatch.setattr(settings, "require_known_price", True)
    now = datetime(2026, 7, 19, 18, 30, tzinfo=UTC)

    strong = _event("strong")  # score 100, priced
    weak = NewsEvent(
        source=Source.GAMERPOWER,
        title="Weak Nothingburger",
        url="https://www.gamerpower.com/open/weak",
        promotion_type=PromotionType.GIVEAWAY,
        original_price=None,  # unlisted value
        current_price=0.0,
        confidence=Confidence(score=50, reasons=["aggregator, unpriced"]),
    )

    surfaced, _, _ = cli._execute_run([strong, weak], now)

    # Only the strong detection surfaces...
    assert {e.title for e in surfaced.new} == {"Game strong"}
    # ...but both are stored — nothing is lost.
    assert len(database.load_all_events()) == 2
