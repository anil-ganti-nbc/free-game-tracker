"""Unit tests for the NewsEvent domain model and its validation rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from newsroom.models import (
    Category,
    Confidence,
    NewsEvent,
    PromotionType,
    Source,
)


def _valid_event(**overrides: object) -> NewsEvent:
    """Build a valid event, overriding fields as needed for a given test."""
    defaults: dict[str, object] = {
        "source": Source.EPIC,
        "title": "Some Game",
        "url": "https://store.epicgames.com/en-US/p/some-game",
        "promotion_type": PromotionType.GIVEAWAY,
        "original_price": 19.99,
        "current_price": 0.0,
        "confidence": Confidence(score=100, reasons=["MSRP changed from paid to free"]),
    }
    defaults.update(overrides)
    return NewsEvent(**defaults)  # type: ignore[arg-type]


def test_minimal_valid_event_defaults() -> None:
    event = _valid_event()
    assert event.category is Category.GAME_PROMOTION
    assert event.discovered_at.tzinfo is not None
    assert event.metadata == {}


def test_event_key_is_source_and_url() -> None:
    event = _valid_event()
    assert event.event_key == f"epic:{event.url}"


def test_confidence_requires_a_reason() -> None:
    with pytest.raises(ValidationError):
        Confidence(score=70, reasons=[])


def test_confidence_rejects_blank_reasons() -> None:
    with pytest.raises(ValidationError):
        Confidence(score=70, reasons=["   "])


def test_confidence_score_bounds() -> None:
    with pytest.raises(ValidationError):
        Confidence(score=101, reasons=["too high"])
    with pytest.raises(ValidationError):
        Confidence(score=-1, reasons=["too low"])


def test_current_price_may_not_exceed_original() -> None:
    with pytest.raises(ValidationError):
        _valid_event(original_price=10.0, current_price=15.0)


def test_promotion_end_before_start_is_rejected() -> None:
    start = datetime(2026, 7, 1, tzinfo=UTC)
    end = datetime(2026, 6, 1, tzinfo=UTC)
    with pytest.raises(ValidationError):
        _valid_event(promotion_start=start, promotion_end=end)


def test_is_ending_soon_true_within_window() -> None:
    end = datetime.now(UTC) + timedelta(hours=12)
    event = _valid_event(promotion_end=end)
    assert event.is_ending_soon(within_hours=48) is True


def test_is_ending_soon_false_without_end_date() -> None:
    event = _valid_event(promotion_end=None)
    assert event.is_ending_soon() is False


def test_is_expired_detects_past_end() -> None:
    end = datetime.now(UTC) - timedelta(hours=1)
    event = _valid_event(promotion_end=end)
    assert event.is_expired() is True
