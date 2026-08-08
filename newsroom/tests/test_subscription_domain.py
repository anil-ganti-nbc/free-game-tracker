import typing
from datetime import UTC, datetime

from newsroom.models import (
    Category,
    Confidence,
    EventType,
    NewsEvent,
    PromotionType,
    Source,
)


def _base_event() -> dict[str, typing.Any]:
    return {
        "source": Source.EPIC,
        "title": "Sub Game",
        "url": "https://store.epicgames.com/sub",
        "promotion_type": PromotionType.GIVEAWAY,
        "confidence": Confidence(score=100, reasons=["Test"]),
        "category": Category.SUBSCRIPTION,
        "event_type": EventType.CATALOG_ADDITION,
        "service": "PS Plus",
    }


def test_legacy_event_key_unchanged() -> None:
    # A base legacy event without subscription category
    event = NewsEvent(
        source=Source.EPIC,
        category=Category.GAME_PROMOTION,
        title="Legacy",
        url="https://store.epicgames.com/legacy",
        promotion_type=PromotionType.GIVEAWAY,
        confidence=Confidence(score=100, reasons=["Test"]),
    )
    assert event.event_key == "epic:https://store.epicgames.com/legacy"


def test_subscription_key_differs_by_tier() -> None:
    e1 = NewsEvent(**{**_base_event(), "tiers": ["Premium"]})
    e2 = NewsEvent(**{**_base_event(), "tiers": ["Extra"]})
    assert e1.event_key != e2.event_key


def test_subscription_key_differs_by_addition_removal() -> None:
    e1 = NewsEvent(**{**_base_event(), "event_type": EventType.CATALOG_ADDITION})
    e2 = NewsEvent(**{**_base_event(), "event_type": EventType.CATALOG_REMOVAL})
    assert e1.event_key != e2.event_key


def test_normalization_removes_dupes_and_ignores_blanks() -> None:
    event = NewsEvent(**{**_base_event(), "tiers": ["Premium", "Extra", "Premium", " ", ""]})
    assert event.tiers == ["Extra", "Premium"]


def test_different_platforms_change_key() -> None:
    e1 = NewsEvent(**{**_base_event(), "platforms": ["PS5"]})
    e2 = NewsEvent(**{**_base_event(), "platforms": ["PS4"]})
    assert e1.event_key != e2.event_key


def test_different_dates_change_key() -> None:
    dt1 = datetime(2026, 1, 1, tzinfo=UTC)
    dt2 = datetime(2026, 2, 1, tzinfo=UTC)
    e1 = NewsEvent(**{**_base_event(), "available_from": dt1})
    e2 = NewsEvent(**{**_base_event(), "available_from": dt2})
    assert e1.event_key != e2.event_key
