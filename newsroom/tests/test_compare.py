"""Tests for the run-to-run comparison logic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from newsroom.compare import compare, deduplicate
from newsroom.models import Confidence, NewsEvent, PromotionType, Source


def _event(url: str, *, end: datetime | None = None) -> NewsEvent:
    return NewsEvent(
        source=Source.EPIC,
        title=f"Game {url}",
        url=url,
        promotion_type=PromotionType.GIVEAWAY,
        original_price=19.99,
        current_price=0.0,
        promotion_end=end,
        confidence=Confidence(score=100, reasons=["free"]),
    )


def test_new_events_are_detected() -> None:
    previous = [_event("a")]
    current = [_event("a"), _event("b")]
    diff = compare(previous, current)
    assert {e.url for e in diff.new} == {"b"}


def test_expired_events_are_detected() -> None:
    previous = [_event("a"), _event("b")]
    current = [_event("a")]
    diff = compare(previous, current)
    assert {e.url for e in diff.expired} == {"b"}


def test_ending_soon_only_for_continuing_events() -> None:
    soon = datetime.now(UTC) + timedelta(hours=6)
    previous = [_event("a")]
    current = [_event("a", end=soon)]
    diff = compare(previous, current, ending_soon_hours=48)
    assert {e.url for e in diff.ending_soon} == {"a"}


def test_new_event_ending_soon_is_reported_as_new_only() -> None:
    """A brand-new giveaway that also ends soon must not appear in both buckets."""
    soon = datetime.now(UTC) + timedelta(hours=6)
    previous: list[NewsEvent] = []
    current = [_event("a", end=soon)]
    diff = compare(previous, current, ending_soon_hours=48)
    assert {e.url for e in diff.new} == {"a"}
    assert diff.ending_soon == []


def test_no_changes_when_identical() -> None:
    previous = [_event("a")]
    current = [_event("a")]
    diff = compare(previous, current)
    assert diff.has_changes is False


def test_has_changes_true_when_something_new() -> None:
    diff = compare([], [_event("a")])
    assert diff.has_changes is True


def test_deduplicate_keeps_first_per_key() -> None:
    events = [_event("a"), _event("b"), _event("a")]
    unique = deduplicate(events)
    assert [e.url for e in unique] == ["a", "b"]
