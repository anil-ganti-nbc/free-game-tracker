"""Tests for the GOG source parser (paid games currently free)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from newsroom.models import PromotionType, Source
from newsroom.sources import gog

FIXTURE = Path(__file__).parent / "fixtures" / "gog_free.json"


@pytest.fixture
def payload() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


def test_only_paid_games_now_free_are_returned(payload: dict[str, Any]) -> None:
    events = gog.parse_free_games(payload)
    titles = {e.title for e in events}
    # F2P and the demo (base price 0) are excluded.
    assert titles == {"Paid Giveaway"}


def test_giveaway_event_fields(payload: dict[str, Any]) -> None:
    event = gog.parse_free_games(payload)[0]
    assert event.source is Source.GOG
    assert event.promotion_type is PromotionType.GIVEAWAY
    assert event.original_price == 9.99
    assert event.current_price == 0.0
    assert event.url == "https://www.gog.com/en/game/paid_giveaway"
    assert event.developer == "Dev A"
    assert event.publisher == "Pub A"
    # No end date from the catalog -> reduced confidence.
    assert event.promotion_end is None
    assert event.confidence.score == 70


def test_empty_payload_yields_no_events() -> None:
    assert gog.parse_free_games({}) == []
