"""Tests for the Epic source parser.

All tests run against a saved fixture with a fixed ``now`` — no network. The
fixture covers one clean free game, one MSRP-less mystery giveaway, an ordinary
discount, an upcoming giveaway, a free DLC, a free bundle, a full-price game,
and an empty element, so every filter path is exercised.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from newsroom.models import PromotionType, Source
from newsroom.sources import epic

FIXTURE = Path(__file__).parent / "fixtures" / "epic_free_games.json"

# Inside the fixture's promotional windows (2026-06-04 .. 2026-06-11).
DURING_PROMO = datetime(2026, 6, 7, tzinfo=UTC)
# After every window has closed.
AFTER_PROMO = datetime(2026, 7, 1, tzinfo=UTC)


@pytest.fixture
def payload() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


def test_only_currently_free_games_are_returned(payload: dict[str, Any]) -> None:
    events = epic.parse_free_games(payload, now=DURING_PROMO)
    titles = {e.title for e in events}
    # The clean base game and the mystery giveaway; nothing else.
    assert titles == {"Sample Free Game", "Rogue Waters"}


def test_excludes_dlc_bundles_discounts_and_upcoming(payload: dict[str, Any]) -> None:
    titles = {e.title for e in epic.parse_free_games(payload, now=DURING_PROMO)}
    for excluded in (
        "Sample DLC Pack",  # ADD_ON
        "Sample Bundle",  # BUNDLE
        "Eternal Threads",  # 20% off, not free
        "The Ouroboros King",  # only upcoming
        "Full Price Game",  # no promotion
    ):
        assert excluded not in titles


def test_clean_free_game_is_fully_specified(payload: dict[str, Any]) -> None:
    event = next(
        e for e in epic.parse_free_games(payload, now=DURING_PROMO) if e.title == "Sample Free Game"
    )
    assert event.source is Source.EPIC
    assert event.promotion_type is PromotionType.GIVEAWAY
    assert event.original_price == 19.99
    assert event.current_price == 0.0
    assert event.url == "https://store.epicgames.com/en-US/p/sample-free-game"
    assert event.developer == "Sample Studio"
    assert event.publisher == "Sample Publisher LLC"
    assert event.promotion_end is not None
    assert event.confidence.score == 100


def test_mystery_giveaway_has_reduced_confidence(payload: dict[str, Any]) -> None:
    event = next(
        e for e in epic.parse_free_games(payload, now=DURING_PROMO) if e.title == "Rogue Waters"
    )
    # MSRP listed as 0 -> we cannot confirm it was a paid title.
    assert event.original_price == 0.0
    assert event.confidence.score == 70
    assert any("MSRP unavailable" in r for r in event.confidence.reasons)


def test_nothing_free_after_windows_close(payload: dict[str, Any]) -> None:
    assert epic.parse_free_games(payload, now=AFTER_PROMO) == []


def test_empty_payload_yields_no_events() -> None:
    assert epic.parse_free_games({}, now=DURING_PROMO) == []


def test_parse_epic_datetime_handles_z_suffix() -> None:
    parsed = epic._parse_epic_datetime("2026-06-11T15:00:00.000Z")
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed.hour == 15


def test_parse_epic_datetime_returns_none_for_garbage() -> None:
    assert epic._parse_epic_datetime("not-a-date") is None
    assert epic._parse_epic_datetime(None) is None


def test_upcoming_free_games_detected(payload: dict[str, Any]) -> None:
    upcoming = epic.parse_upcoming_free_games(payload, now=DURING_PROMO)
    titles = {g.title for g in upcoming}
    # The fixture's one game with a future 100%-off offer.
    assert titles == {"The Ouroboros King"}
    assert "Sample Free Game" not in titles  # that one is free *now*


def test_upcoming_have_future_start_dates(payload: dict[str, Any]) -> None:
    upcoming = epic.parse_upcoming_free_games(payload, now=DURING_PROMO)
    assert upcoming  # non-empty
    assert all(g.starts is not None and g.starts > DURING_PROMO for g in upcoming)
