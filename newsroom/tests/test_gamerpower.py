"""Tests for the GamerPower aggregator parser."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from newsroom.models import PromotionType, Source
from newsroom.sources import gamerpower

FIXTURE = Path(__file__).parent / "fixtures" / "gamerpower_giveaways.json"


@pytest.fixture
def payload() -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


def test_keeps_only_complementary_active_games(payload: list[dict[str, Any]]) -> None:
    events = gamerpower.parse_giveaways(payload)
    titles = {e.title for e in events}
    # Prime and Humble kept; Epic/Steam (first-party), loot (DLC), and the
    # expired itch entry are all excluded.
    assert titles == {"Prime Freebie", "Humble Giveaway"}


def test_first_party_platforms_are_excluded(payload: list[dict[str, Any]]) -> None:
    titles = {e.title for e in gamerpower.parse_giveaways(payload)}
    assert "Epic Weekly Free (already covered)" not in titles
    assert "Steam 100% Off (already covered)" not in titles


def test_prime_event_fields(payload: list[dict[str, Any]]) -> None:
    event = next(
        e for e in gamerpower.parse_giveaways(payload) if e.title == "Prime Freebie"
    )
    assert event.source is Source.GAMERPOWER
    assert event.promotion_type is PromotionType.GIVEAWAY
    assert event.original_price == 29.99
    assert event.current_price == 0.0
    assert event.promotion_end is not None
    assert event.metadata["platforms"] == "PC, Amazon Prime Gaming"
    # Secondary source: capped below first-party, with a verify-at-store reason.
    assert event.confidence.score == 90
    assert any("verify at store" in r.lower() for r in event.confidence.reasons)


def test_missing_worth_and_end_reduce_confidence(payload: list[dict[str, Any]]) -> None:
    event = next(
        e for e in gamerpower.parse_giveaways(payload) if e.title == "Humble Giveaway"
    )
    assert event.original_price is None
    assert event.promotion_end is None
    assert event.confidence.score == 50  # 90 - 20 (no end) - 20 (no worth)


def test_non_list_payload_is_safe() -> None:
    assert gamerpower.parse_giveaways({"error": "nope"}) == []
    assert gamerpower.parse_giveaways([]) == []


def test_end_date_offset_is_applied(
    payload: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The configured offset shifts a naive end date before treating it as UTC."""
    from datetime import UTC, datetime

    from newsroom.config import settings

    monkeypatch.setattr(settings, "gamerpower_utc_offset_hours", 5)
    event = next(
        e for e in gamerpower.parse_giveaways(payload) if e.title == "Prime Freebie"
    )
    # Fixture end_date "2026-07-30 23:59:00" + 5h -> 2026-07-31 04:59:00 UTC.
    assert event.promotion_end == datetime(2026, 7, 31, 4, 59, 0, tzinfo=UTC)
