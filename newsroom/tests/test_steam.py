"""Tests for the Steam source parser (100%-off only)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from newsroom.models import PromotionType, Source
from newsroom.sources import steam

FIXTURE = Path(__file__).parent / "fixtures" / "steam_featured.json"


@pytest.fixture
def payload() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


def test_only_full_discounts_are_returned(payload: dict[str, Any]) -> None:
    events = steam.parse_specials(payload)
    titles = {e.title for e in events}
    assert titles == {"Free This Week", "Freebie No Expiry"}
    assert "Half Off Game" not in titles


def test_full_discount_event_fields(payload: dict[str, Any]) -> None:
    event = next(e for e in steam.parse_specials(payload) if e.title == "Free This Week")
    assert event.source is Source.STEAM
    assert event.promotion_type is PromotionType.FULL_DISCOUNT
    assert event.original_price == 19.99
    assert event.current_price == 0.0
    assert event.url == "https://store.steampowered.com/app/100"
    assert event.promotion_end is not None
    assert event.confidence.score == 100


def test_missing_expiry_reduces_confidence(payload: dict[str, Any]) -> None:
    event = next(e for e in steam.parse_specials(payload) if e.title == "Freebie No Expiry")
    assert event.promotion_end is None
    assert event.confidence.score == 70
    assert any("end date unavailable" in r.lower() for r in event.confidence.reasons)


def test_empty_payload_yields_no_events() -> None:
    assert steam.parse_specials({}) == []


def test_parse_appdetails_extracts_dev_and_publisher() -> None:
    payload = {
        "100": {
            "success": True,
            "data": {
                "developers": ["Studio A", "Studio B"],
                "publishers": ["Publisher A"],
            },
        }
    }
    assert steam.parse_appdetails(payload, 100) == ("Studio A", "Publisher A")


def test_parse_appdetails_handles_failure() -> None:
    assert steam.parse_appdetails({"100": {"success": False}}, 100) == (None, None)
    assert steam.parse_appdetails({}, 100) == (None, None)
