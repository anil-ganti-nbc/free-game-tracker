"""Tests for the Steam breakout (well-reviewed new release) parsers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from newsroom.sources import steam_breakouts as sb

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 7, 20, tzinfo=UTC)


def _appdetails(name: str, date: str, app_type: str = "game") -> dict[str, Any]:
    return {
        "42": {
            "success": True,
            "data": {
                "type": app_type,
                "name": name,
                "release_date": {"coming_soon": False, "date": date},
            },
        }
    }


def test_candidate_appids_from_new_releases() -> None:
    payload = {"new_releases": {"items": [{"id": 10}, {"id": 20}, {"name": "no id"}]}}
    assert sb.candidate_appids(payload) == [10, 20]


def test_parse_release_reads_name_and_date() -> None:
    parsed = sb.parse_release(_appdetails("Cool Game", "Jul 15, 2026"), 42)
    assert parsed is not None
    name, release, is_game = parsed
    assert name == "Cool Game"
    assert release == datetime(2026, 7, 15, tzinfo=UTC)
    assert is_game is True


def test_parse_release_handles_day_first_format() -> None:
    parsed = sb.parse_release(_appdetails("Euro Game", "15 Jul, 2026"), 42)
    assert parsed is not None
    assert parsed[1] == datetime(2026, 7, 15, tzinfo=UTC)


def test_parse_release_skips_unparseable_or_coming_soon() -> None:
    assert sb.parse_release(_appdetails("Vague", "2026"), 42) is None
    coming = _appdetails("Soon", "Q1 2026")
    coming["42"]["data"]["release_date"]["coming_soon"] = True
    assert sb.parse_release(coming, 42) is None


def test_parse_review_summary() -> None:
    payload = json.loads(
        (FIXTURES / "steam_appreviews_overwhelming.json").read_text(encoding="utf-8")
    )
    parsed = sb.parse_review_summary(payload)
    assert parsed is not None
    desc, total, pct = parsed
    assert desc == "Overwhelmingly Positive"
    assert total == 2000
    assert pct == 95.0


def test_tier_meets_threshold() -> None:
    assert sb.tier_meets("Overwhelmingly Positive", "Very Positive") is True
    assert sb.tier_meets("Very Positive", "Very Positive") is True
    assert sb.tier_meets("Positive", "Very Positive") is False
    assert sb.tier_meets("Mixed", "Very Positive") is False


def test_within_window() -> None:
    assert sb.within_window(datetime(2026, 7, 15, tzinfo=UTC), NOW, 14) is True
    assert sb.within_window(datetime(2026, 7, 1, tzinfo=UTC), NOW, 14) is False  # 19 days
    assert sb.within_window(datetime(2026, 7, 25, tzinfo=UTC), NOW, 14) is False  # future
