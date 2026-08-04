"""Tests for the surfacing quality gate."""

from __future__ import annotations

from newsroom.models import Confidence, NewsEvent, PromotionType, Source
from newsroom.quality import filter_events, passes_quality_gate


def _event(*, score: int = 100, price: float | None = 19.99) -> NewsEvent:
    return NewsEvent(
        source=Source.EPIC,
        title="Game",
        url=f"https://store.epicgames.com/p/{score}-{price}",
        promotion_type=PromotionType.GIVEAWAY,
        original_price=price,
        current_price=0.0,
        confidence=Confidence(score=score, reasons=["free"]),
    )


def test_default_gate_passes_everything() -> None:
    assert passes_quality_gate(_event(score=10, price=None)) is True


def test_min_confidence_rejects_low_scores() -> None:
    assert passes_quality_gate(_event(score=50), min_confidence=70) is False
    assert passes_quality_gate(_event(score=70), min_confidence=70) is True


def test_require_known_price_rejects_missing_or_zero() -> None:
    assert passes_quality_gate(_event(price=None), require_known_price=True) is False
    assert passes_quality_gate(_event(price=0.0), require_known_price=True) is False
    assert passes_quality_gate(_event(price=5.0), require_known_price=True) is True


def test_unknown_price_allowed_when_not_required() -> None:
    assert passes_quality_gate(_event(price=None), require_known_price=False) is True


def test_min_price_floor() -> None:
    assert passes_quality_gate(_event(price=4.99), min_price=10.0) is False
    assert passes_quality_gate(_event(price=14.99), min_price=10.0) is True


def test_users_chosen_gate_combo() -> None:
    """confidence>=70 and known price: the configured 'no nothingburgers' combo."""
    keep = _event(score=100, price=19.99)
    drop_low_conf = _event(score=50, price=19.99)  # GamerPower unpriced-style
    drop_no_price = _event(score=70, price=None)  # unlisted value
    drop_zero_price = _event(score=70, price=0.0)  # Epic "mystery" placeholder
    survivors = filter_events(
        [keep, drop_low_conf, drop_no_price, drop_zero_price],
        min_confidence=70,
        require_known_price=True,
    )
    assert survivors == [keep]
